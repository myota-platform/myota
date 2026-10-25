"""JetStream email delivery worker with redacted PostgreSQL state."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import signal
import sys
import threading
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from psycopg import Error as PostgresError

from email_core import (
    EmailCommand,
    InvalidCommand,
    Recipient,
    RecipientUnavailable,
    Sender,
    SMTPConfig,
    SMTPDeliveryError,
    deliver_smtp_async,
    render_message,
    secret_from_env,
)
from email_observability import EmailTelemetry, HealthMetricsServer, JsonFormatter

LOG = logging.getLogger("myota.email")
MAX_DELIVERIES = 8
ACK_WAIT_SECONDS = 90
LEASE_SECONDS = 60
MAX_ACK_PENDING = 1
MAX_WAITING = 1
STREAM = "MYOTA_EMAIL_WORK"
DURABLE = "email-delivery-v1"
SUBJECT = "myota.work.email.send.v1"


class RetryableDeliveryError(RuntimeError):
    """A failure that may succeed after bounded retry."""


@dataclass(frozen=True)
class WorkerConfig:
    database_url: str
    identity_url: str
    identity_client_secret: str
    sender: Sender
    smtp: SMTPConfig

    @classmethod
    def from_env(cls) -> WorkerConfig:
        database_url = secret_from_env("EMAIL_DATABASE_URL")
        identity_url = os.environ.get(
            "IDENTITY_INTERNAL_URL", "http://identity:8001"
        ).rstrip("/")
        secret = secret_from_env("MYOTA_EMAIL_SERVICE_CLIENT_SECRET")
        sender = Sender(
            os.environ.get("EMAIL_SENDER_ADDRESS", ""),
            os.environ.get("EMAIL_SENDER_DISPLAY_NAME", "MyOTA"),
        )
        if not database_url:
            raise ValueError("EMAIL_DATABASE_URL is required")
        if len(secret) < 32:
            raise ValueError("email service client credential is unavailable")
        if not identity_url.startswith(("http://", "https://")):
            raise ValueError("Identity URL must use HTTP or HTTPS")
        if not sender.address:
            raise ValueError("EMAIL_SENDER_ADDRESS is required")
        return cls(database_url, identity_url, secret, sender, SMTPConfig.from_env())


class IdentityRecipientResolver:
    """Resolve current recipient data only through the protected Identity API."""

    def __init__(self, base_url: str, client_secret: str, timeout: float = 5):
        self.base_url = base_url.rstrip("/")
        self.client_secret = client_secret
        self.timeout = timeout
        self._token = ""
        self._token_expires = 0.0

    def _request(self, path: str, *, body: dict | None = None, token: str = ""):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404) and path != "/v1/identity/auth/service-token":
                raise RecipientUnavailable("recipient is unavailable") from None
            raise RetryableDeliveryError("Identity lookup failed") from None
        except (OSError, TimeoutError, json.JSONDecodeError):
            raise RetryableDeliveryError("Identity lookup failed") from None

    async def resolve(self, account_id: str) -> Recipient:
        now = asyncio.get_running_loop().time()
        if not self._token or now >= self._token_expires:
            status, result = self._request(
                "/v1/identity/auth/service-token",
                body={"service": "email-service", "clientSecret": self.client_secret},
            )
            if status != 200 or not isinstance(result.get("accessToken"), str):
                raise RetryableDeliveryError("Identity authentication failed")
            self._token = result["accessToken"]
            self._token_expires = now + min(
                max(30, int(result.get("expiresIn", 300)) - 30), 270
            )
        status, result = self._request(
            f"/v1/identity/internal/email-recipients/{uuid.UUID(account_id)}",
            token=self._token,
        )
        address = result.get("deliverableAddress") if status == 200 else None
        if not isinstance(address, str) or not address:
            raise RecipientUnavailable("recipient is unavailable")
        return Recipient(address=address, active=True, eligible=True)


class DeliveryStore:
    """PostgreSQL delivery ledger; raw commands, addresses and bodies are absent."""

    def __init__(self, database_url: str):
        from psycopg_pool import ConnectionPool

        self.pool = ConnectionPool(
            database_url,
            min_size=1,
            max_size=4,
            open=True,
            kwargs={"connect_timeout": 5},
        )

    def close(self) -> None:
        self.pool.close()

    def migrate(self) -> None:
        """Apply the idempotent service-owned schema before readiness."""
        migration = Path(__file__).with_name("migrations") / "001_email_delivery.sql"
        statements = [
            statement.strip()
            for statement in migration.read_text(encoding="utf-8").split(";")
            if statement.strip()
        ]
        with self.pool.connection() as connection, connection.transaction():
            for statement in statements:
                connection.execute(statement)

    def ping(self) -> bool:
        try:
            with self.pool.connection() as connection:
                return connection.execute("SELECT 1").fetchone() == (1,)
        except PostgresError:
            return False

    def claim(self, command: EmailCommand) -> str:
        with self.pool.connection() as connection, connection.transaction():
            connection.execute(
                """INSERT INTO email_delivery
                         (work_id, template_id, status, attempts, lease_until)
                       VALUES (%s, %s, 'PENDING', 0, NULL)
                       ON CONFLICT (work_id) DO NOTHING""",
                (command.work_id, command.template_id),
            )
            record = connection.execute(
                """SELECT status, lease_until FROM email_delivery
                       WHERE work_id = %s FOR UPDATE""",
                (command.work_id,),
            ).fetchone()
            status, lease_until = record
            if status in ("DELIVERED", "DEAD_LETTER"):
                return status
            if (
                status == "PROCESSING"
                and lease_until
                and lease_until > datetime.now(timezone.utc)
            ):
                return "IN_PROGRESS"
            connection.execute(
                """UPDATE email_delivery
                       SET status='PROCESSING', attempts=attempts+1,
                           lease_until=now() + make_interval(secs => %s),
                           updated_at=now()
                       WHERE work_id=%s""",
                (LEASE_SECONDS, command.work_id),
            )
            connection.execute(
                """INSERT INTO email_delivery_attempt
                         (work_id, outcome, attempted_at)
                       VALUES (%s, 'started', now())""",
                (command.work_id,),
            )
            return "CLAIMED"

    def delivered(self, work_id: str) -> None:
        with self.pool.connection() as connection:
            connection.execute(
                """UPDATE email_delivery SET status='DELIVERED', delivered_at=now(),
                     lease_until=NULL, last_error_code=NULL, updated_at=now()
                   WHERE work_id=%s""",
                (work_id,),
            )
            connection.execute(
                """UPDATE email_delivery_attempt SET outcome='delivered'
                   WHERE work_id=%s AND outcome='started'
                     AND attempted_at=(SELECT max(attempted_at)
                                       FROM email_delivery_attempt WHERE work_id=%s)""",
                (work_id, work_id),
            )

    def retry(self, work_id: str, error_code: str) -> int:
        with self.pool.connection() as connection, connection.transaction():
            row = connection.execute(
                """UPDATE email_delivery SET status='PENDING', lease_until=NULL,
                         last_error_code=%s, updated_at=now()
                       WHERE work_id=%s RETURNING attempts""",
                (error_code, work_id),
            ).fetchone()
            connection.execute(
                """UPDATE email_delivery_attempt SET outcome='retryable_failure',
                         error_code=%s
                       WHERE work_id=%s AND outcome='started'
                         AND attempted_at=(SELECT max(attempted_at)
                                           FROM email_delivery_attempt WHERE work_id=%s)""",
                (error_code, work_id, work_id),
            )
            return int(row[0])

    def dead_letter(self, work_id: str | None, error_code: str) -> None:
        with self.pool.connection() as connection, connection.transaction():
            if work_id:
                connection.execute(
                    """UPDATE email_delivery SET status='DEAD_LETTER',
                             lease_until=NULL, last_error_code=%s, updated_at=now()
                           WHERE work_id=%s""",
                    (error_code, work_id),
                )
                connection.execute(
                    """UPDATE email_delivery_attempt SET outcome='dead_letter',
                             error_code=%s
                           WHERE work_id=%s AND outcome='started'
                             AND attempted_at=(SELECT max(attempted_at)
                                               FROM email_delivery_attempt WHERE work_id=%s)""",
                    (error_code, work_id, work_id),
                )
            if work_id:
                connection.execute(
                    """INSERT INTO email_dead_letter
                             (work_id, error_code, recorded_at)
                           VALUES (%s, %s, now())
                           ON CONFLICT (work_id, error_code) DO UPDATE
                             SET recorded_at=now(), redrive_requested_at=NULL,
                                 redrive_actor=NULL, redrive_reason=NULL,
                                 resolved_at=NULL""",
                    (work_id, error_code),
                )
            else:
                connection.execute(
                    """INSERT INTO email_dead_letter
                             (work_id, error_code, recorded_at)
                           VALUES (NULL, %s, now())
                           ON CONFLICT DO NOTHING""",
                    (error_code,),
                )

    def request_redrive(
        self, work_id: str, error_code: str, actor: str, reason: str
    ) -> bool:
        """Reset one dead-letter ledger row before producer-outbox replay."""
        canonical_id = str(uuid.UUID(work_id))
        if error_code not in {"recipient_unavailable", "delivery_exhausted"}:
            raise ValueError(
                "only identified recipient or exhausted deliveries can be redriven"
            )
        if not re.fullmatch(r"[A-Za-z0-9@._:-]{1,120}", actor):
            raise ValueError("redrive actor must be a bounded audit identifier")
        if not isinstance(reason, str) or not 12 <= len(reason.strip()) <= 500:
            raise ValueError("redrive reason must be between 12 and 500 characters")
        with self.pool.connection() as connection, connection.transaction():
            updated = connection.execute(
                """UPDATE email_delivery
                          SET status='PENDING', lease_until=NULL,
                              last_error_code=NULL, updated_at=now()
                        WHERE work_id=%s AND status='DEAD_LETTER'
                        RETURNING work_id""",
                (canonical_id,),
            ).fetchone()
            if updated is None:
                return False
            connection.execute(
                """INSERT INTO email_dead_letter_redrive
                         (work_id, error_code, actor, reason, requested_at)
                       VALUES (%s, %s, %s, %s, now())""",
                (canonical_id, error_code, actor, reason.strip()),
            )
            audit = connection.execute(
                """UPDATE email_dead_letter
                          SET redrive_requested_at=now(), redrive_actor=%s,
                              redrive_reason=%s
                        WHERE work_id=%s AND error_code=%s
                          AND resolved_at IS NULL
                        RETURNING id""",
                (actor, reason.strip(), canonical_id, error_code),
            ).fetchone()
            if audit is None:
                raise RuntimeError(
                    "matching unresolved dead-letter audit row not found"
                )
            return True


def _backoff_seconds(attempt: int) -> int:
    return min(300, 2 ** min(max(attempt - 1, 0), 8))


async def handle_message(
    message: Any,
    store: DeliveryStore,
    resolver: IdentityRecipientResolver,
    config: WorkerConfig,
    telemetry: EmailTelemetry | None = None,
) -> None:
    telemetry = telemetry or EmailTelemetry()
    try:
        command = EmailCommand.parse(message.data)
    except InvalidCommand:
        store.dead_letter(None, "invalid_command")
        telemetry.record("invalid_command", "unknown")
        await message.term()
        return

    state = store.claim(command)
    if state in ("DELIVERED", "DEAD_LETTER"):
        telemetry.record("duplicate", command.template_id)
        await message.ack()
        return
    if state == "IN_PROGRESS":
        await message.nak(delay=2)
        return
    started = perf_counter()
    try:
        with telemetry.span(getattr(message, "headers", None)) as span:
            if span is not None:
                span.set_attribute("email.template_id", command.template_id)
            try:
                recipient = await resolver.resolve(command.recipient_account_id)
                rendered = render_message(command, recipient, config.sender)
                # One message is processed at a time. Both external operations
                # are timeout-bounded and the durable allows >2x their maximum
                # combined duration.
                smtp_started = perf_counter()
                try:
                    await deliver_smtp_async(config.smtp, rendered)
                except SMTPDeliveryError:
                    telemetry.observe_smtp_duration(perf_counter() - smtp_started)
                    telemetry.record_smtp_availability(False)
                    raise
                else:
                    telemetry.observe_smtp_duration(perf_counter() - smtp_started)
                    telemetry.record_smtp_availability(True)
            except RecipientUnavailable:
                if span is not None:
                    from opentelemetry.trace import Status, StatusCode

                    span.set_status(Status(StatusCode.ERROR, "recipient unavailable"))
                raise
            except Exception:
                if span is not None:
                    from opentelemetry.trace import Status, StatusCode

                    span.set_status(Status(StatusCode.ERROR, "delivery failed"))
                raise
    except RecipientUnavailable:
        telemetry.observe_duration(command.template_id, perf_counter() - started)
        store.dead_letter(command.work_id, "recipient_unavailable")
        telemetry.record("dead_letter", command.template_id)
        await message.term()
        return
    except Exception as error:  # noqa: BLE001 - sanitize provider and SMTP error details
        telemetry.observe_duration(command.template_id, perf_counter() - started)
        metadata = getattr(message, "metadata", None)
        delivered = int(getattr(metadata, "num_delivered", 1) or 1)
        if delivered >= MAX_DELIVERIES:
            store.dead_letter(command.work_id, "delivery_exhausted")
            telemetry.record("dead_letter", command.template_id)
            outcome = "dead_letter"
            await message.term()
        else:
            attempts = store.retry(command.work_id, "transient_delivery_failure")
            failure_outcome = (
                "smtp_failure"
                if isinstance(error, SMTPDeliveryError)
                else "identity_failure"
                if isinstance(error, RetryableDeliveryError)
                else "delivery_failure"
            )
            telemetry.record(failure_outcome, command.template_id)
            outcome = failure_outcome
            await message.nak(delay=_backoff_seconds(max(delivered, attempts)))
        LOG.warning(
            "email delivery attempt failed",
            extra={"outcome": outcome, "error_code": "transient_delivery_failure"},
        )
        return

    # A process crash after SMTP acceptance and before this commit can duplicate
    # delivery. State is committed before the JetStream acknowledgement.
    store.delivered(command.work_id)
    telemetry.record("delivered", command.template_id)
    telemetry.observe_duration(command.template_id, perf_counter() - started)
    await message.ack()


async def run_worker() -> None:
    from nats.aio.client import Client as NATS

    config = WorkerConfig.from_env()
    store = DeliveryStore(config.database_url)
    store.migrate()
    resolver = IdentityRecipientResolver(
        config.identity_url, config.identity_client_secret
    )
    telemetry = EmailTelemetry()
    ready = threading.Event()
    health = HealthMetricsServer(
        telemetry,
        lambda: ready.is_set() and store.ping(),
        port=int(os.environ.get("EMAIL_HEALTH_PORT", "9108")),
    )
    health.start()
    nc = NATS()
    subscription = None
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    try:
        await nc.connect(
            os.environ.get("NATS_URL", "nats://nats:4222"),
            name="myota-email-service",
            max_reconnect_attempts=10,
            reconnect_time_wait=1,
            connect_timeout=5,
        )
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        js = nc.jetstream()
        info = await js.consumer_info(STREAM, DURABLE)
        validate_consumer_config(info.config)
        subscription = await js.pull_subscribe_bind(stream=STREAM, durable=DURABLE)
        await telemetry.update_queue(js, info)
        ready.set()
        while not stop.is_set():
            try:
                messages = await subscription.fetch(1, timeout=2)
            except asyncio.TimeoutError:
                continue
            try:
                consumer_info = await js.consumer_info(STREAM, DURABLE)
                await telemetry.update_queue(js, consumer_info)
            except Exception:  # noqa: BLE001 - metrics must not block message work
                # Metrics must not interrupt message delivery on a transient
                # management API failure.
                LOG.debug("email queue metrics unavailable")
            for message in messages:
                await handle_message(message, store, resolver, config, telemetry)
    finally:
        ready.clear()
        try:
            if subscription is not None:
                await subscription.unsubscribe()
            if nc.is_connected:
                await nc.drain()
        finally:
            store.close()
            health.close()
            telemetry.shutdown()


def request_redrive_from_cli(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Request audited email recovery")
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--error-code", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--reason", required=True)
    options = parser.parse_args(arguments)
    try:
        database_url = secret_from_env("EMAIL_DATABASE_URL")
    except ValueError:
        parser.error("EMAIL_DATABASE_URL secret is unavailable")
    if not database_url:
        parser.error("EMAIL_DATABASE_URL is required")
    store = DeliveryStore(database_url)
    try:
        requested = store.request_redrive(
            options.work_id, options.error_code, options.actor, options.reason
        )
        if requested:
            print(
                "Audited redrive recorded; replay the same work ID from its producer outbox."
            )
            return 0
        print("No unresolved matching email dead letter was found.", file=sys.stderr)
        return 2
    finally:
        store.close()


def validate_consumer_config(config: Any) -> None:
    """Fail closed if the deployment durable differs from the bounded policy."""
    from nats.js.api import AckPolicy

    if (
        config.filter_subject != SUBJECT
        or config.ack_policy != AckPolicy.EXPLICIT
        or config.ack_wait != ACK_WAIT_SECONDS
        or config.max_deliver != MAX_DELIVERIES
        or config.max_ack_pending != MAX_ACK_PENDING
        or config.max_waiting != MAX_WAITING
        or config.deliver_subject
    ):
        raise RuntimeError(
            "email delivery durable does not match the registered pull policy"
        )


if __name__ == "__main__":
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    if len(sys.argv) > 1 and sys.argv[1] == "redrive":
        raise SystemExit(request_redrive_from_cli(sys.argv[2:]))
    asyncio.run(run_worker())
