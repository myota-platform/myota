"""Privacy-bounded email command validation, rendering, and SMTP delivery.

This module deliberately does not connect to NATS or Identity yet. The
contract, durable consumer, recipient API, and deployment topology remain
separate gates; adapters can use the small interfaces below without putting
recipient data in the command or telemetry.
"""

from __future__ import annotations

import asyncio
import json
import os
import smtplib
import ssl
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from html import escape
from pathlib import Path
from typing import Protocol

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from referencing import Registry, Resource

_CONTRACT_ROOT = Path(__file__).resolve().parent / "contracts" / "schemas"
if not _CONTRACT_ROOT.exists():
    _CONTRACT_ROOT = Path(__file__).resolve().parents[2] / "contracts" / "schemas"
_WORK_SCHEMA = json.loads(
    (_CONTRACT_ROOT / "work-command.schema.json").read_text(encoding="utf-8")
)
_EMAIL_SCHEMA = json.loads(
    (_CONTRACT_ROOT / "work" / "email-send-v1.schema.json").read_text(encoding="utf-8")
)
_EMAIL_SCHEMA_REGISTRY = Registry().with_resource(
    _WORK_SCHEMA["$id"], Resource.from_contents(_WORK_SCHEMA)
)
_EMAIL_VALIDATOR = Draft202012Validator(
    _EMAIL_SCHEMA,
    registry=_EMAIL_SCHEMA_REGISTRY,
    format_checker=FormatChecker(),
)
MAX_COMMAND_BYTES = _EMAIL_SCHEMA["x-max-payload-bytes"]
EMAIL_WORK_TYPE = "email.send.v1"
SUPPORTED_TEMPLATES = set(
    _EMAIL_SCHEMA["allOf"][1]["properties"]["payload"]["properties"]["templateId"][
        "enum"
    ]
)


def secret_from_env(name: str, values: dict[str, str] | None = None) -> str:
    """Read a secret from either an environment value or a mounted file."""
    env = values if values is not None else os.environ
    inline = env.get(name, "")
    path = env.get(f"{name}_FILE", "")
    if inline and path:
        raise ValueError(f"{name} and {name}_FILE cannot both be configured")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").rstrip("\r\n")
        except (OSError, UnicodeError):
            raise ValueError(f"{name} secret file is unavailable") from None
    return inline


class InvalidCommand(ValueError):
    """A command is malformed or outside the checked-in email contract."""


class RecipientUnavailable(RuntimeError):
    """The Identity-owned account cannot receive this email."""


class SMTPDeliveryError(RuntimeError):
    """A redacted, retryable failure talking to the configured SMTP server."""


@dataclass(frozen=True)
class EmailCommand:
    work_id: str
    created_at: str
    producer: str
    recipient_account_id: str
    template_id: str
    template_data: dict[str, str]
    correlation_id: str | None = None

    @classmethod
    def parse(cls, raw: bytes) -> EmailCommand:
        if len(raw) > MAX_COMMAND_BYTES:
            raise InvalidCommand("command exceeds the contract payload limit")
        try:
            envelope = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidCommand("command is not valid JSON") from exc
        try:
            _EMAIL_VALIDATOR.validate(envelope)
        except ValidationError as exc:
            raise InvalidCommand(
                "command does not match the email work contract"
            ) from exc
        work_id = _uuid(envelope["workId"], "workId")
        payload = envelope["payload"]
        recipient_id = _uuid(payload["recipientAccountId"], "recipientAccountId")
        template_id = payload["templateId"]
        data = payload["templateData"]
        created_at = envelope["createdAt"]
        producer = envelope["producer"]
        correlation_id = envelope.get("correlationId")
        return cls(
            work_id=work_id,
            created_at=created_at,
            producer=producer,
            recipient_account_id=recipient_id,
            template_id=template_id,
            template_data=dict(data),
            correlation_id=correlation_id,
        )


def _uuid(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise InvalidCommand(f"{field} must be a UUID")
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise InvalidCommand(f"{field} must be a UUID") from exc


@dataclass(frozen=True)
class Recipient:
    """Short-lived address resolved by Identity; never serialized or logged."""

    address: str
    active: bool
    eligible: bool


class RecipientResolver(Protocol):
    async def resolve(self, account_id: str) -> Recipient: ...


@dataclass(frozen=True)
class Sender:
    address: str
    display_name: str


def render_message(
    command: EmailCommand, recipient: Recipient, sender: Sender
) -> EmailMessage:
    if not recipient.active or not recipient.eligible:
        raise RecipientUnavailable("recipient is not eligible for delivery")
    if not _valid_address(recipient.address) or not _valid_address(sender.address):
        raise ValueError("configured or resolved email address is invalid")
    if any(c in sender.display_name for c in "\r\n"):
        raise ValueError("sender display name is invalid")

    message = EmailMessage()
    message["From"] = f"{sender.display_name} <{sender.address}>"
    message["To"] = recipient.address
    if command.template_id == "account-created-participant.v1":
        name = command.template_data["displayName"]
        message["Subject"] = "Your MyOTA account is ready"
        message.set_content(
            f"Hello {name},\n\nYour MyOTA participant account has been created.\n"
        )
        message.add_alternative(
            "<p>Hello "
            + escape(name)
            + ",</p><p>Your MyOTA participant account has been created.</p>",
            subtype="html",
        )
    elif command.template_id == "account-created-administrator.v1":
        name = command.template_data["createdAccountName"]
        role = command.template_data["createdAccountRole"].lower()
        message["Subject"] = "A MyOTA account was created"
        message.set_content(f"Hello,\n\nA {role} account for {name} was created.\n")
        message.add_alternative(
            "<p>Hello,</p><p>A "
            + escape(role)
            + " account for "
            + escape(name)
            + " was created.</p>",
            subtype="html",
        )
    else:  # Defensive if a caller constructs EmailCommand without parse().
        raise InvalidCommand("unsupported email template")
    return message


def _valid_address(address: str) -> bool:
    if (
        not isinstance(address, str)
        or len(address) > 254
        or any(c in address for c in "\r\n")
    ):
        return False
    local, separator, domain = address.rpartition("@")
    return bool(separator and local and domain and " " not in address)


@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    username: str
    password: str
    tls_mode: str
    timeout_seconds: float

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> SMTPConfig:
        values = env if env is not None else os.environ
        try:
            port = int(values["EMAIL_SMTP_PORT"])
            timeout = float(values.get("EMAIL_SMTP_TIMEOUT_SECONDS", "10"))
        except (KeyError, ValueError) as exc:
            raise ValueError(
                "SMTP port and timeout configuration are required"
            ) from exc
        config = cls(
            host=values.get("EMAIL_SMTP_HOST", "").strip(),
            port=port,
            username=values.get("EMAIL_SMTP_USERNAME", ""),
            password=secret_from_env("EMAIL_SMTP_PASSWORD", values),
            tls_mode=values.get("EMAIL_SMTP_TLS_MODE", "starttls").lower(),
            timeout_seconds=timeout,
        )
        if (
            not config.host
            or not config.username
            or not config.password
            or not 1 <= config.port <= 65535
            or not 1 <= config.timeout_seconds <= 30
            or config.tls_mode not in {"starttls", "implicit"}
        ):
            raise ValueError("SMTP configuration is incomplete or outside bounds")
        return config


def deliver_smtp(config: SMTPConfig, message: EmailMessage) -> None:
    """Send one message with TLS; callers must store outcome before ACKing."""
    context = ssl.create_default_context()
    if config.tls_mode == "implicit":
        client = smtplib.SMTP_SSL(
            config.host, config.port, timeout=config.timeout_seconds, context=context
        )
    else:
        client = smtplib.SMTP(config.host, config.port, timeout=config.timeout_seconds)
    with client:
        client.ehlo()
        if config.tls_mode == "starttls":
            client.starttls(context=context)
            client.ehlo()
        client.login(config.username, config.password)
        client.send_message(message)


async def deliver_smtp_async(config: SMTPConfig, message: EmailMessage) -> None:
    try:
        await asyncio.to_thread(deliver_smtp, config, message)
    except (OSError, smtplib.SMTPException, ssl.SSLError, TimeoutError):
        raise SMTPDeliveryError("SMTP delivery failed") from None
