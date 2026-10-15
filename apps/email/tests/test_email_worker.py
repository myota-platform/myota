from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from email_core import (
    EmailCommand,
    InvalidCommand,
    Recipient,
    RecipientUnavailable,
    Sender,
    SMTPConfig,
    SMTPDeliveryError,
    deliver_smtp,
    render_message,
    secret_from_env,
)
from email_observability import EmailTelemetry, HealthMetricsServer, JsonFormatter
from email_worker import (
    WorkerConfig,
    handle_message,
)


def command(template_id="account-created-participant.v1", template_data=None):
    if template_data is None:
        template_data = {"displayName": "<Alice & Bob>"}
    return {
        "envelopeVersion": 1,
        "workId": "d62842cf-2282-4f86-9890-a3b29745cf11",
        "workType": "email.send.v1",
        "createdAt": "2026-10-14T12:00:00Z",
        "producer": "myota-identity",
        "payload": {
            "recipientAccountId": "566b8475-bda2-4a2d-8ab8-d7a9a93c0041",
            "templateId": template_id,
            "templateData": template_data,
        },
    }


class EmailWorkerTests(unittest.TestCase):
    def test_parse_accepts_allowlisted_participant_template(self):
        parsed = EmailCommand.parse(json.dumps(command()).encode())
        self.assertEqual(parsed.work_id, "d62842cf-2282-4f86-9890-a3b29745cf11")
        self.assertEqual(parsed.template_data, {"displayName": "<Alice & Bob>"})

    def test_worker_persists_delivery_before_acknowledging(self):
        events = []

        class Store:
            def claim(self, parsed):
                events.append("claim")
                return "CLAIMED"

            def delivered(self, work_id):
                events.append("delivered")

        class Message:
            data = json.dumps(command()).encode()
            metadata = SimpleNamespace(num_delivered=1)

            async def ack(self):
                events.append("ack")

            async def nak(self, **kwargs):
                events.append("nak")

            async def term(self):
                events.append("term")

        resolver = SimpleNamespace(
            resolve=AsyncMock(
                return_value=Recipient("alice@example.test", active=True, eligible=True)
            )
        )
        config = WorkerConfig(
            "postgresql://unused",
            "http://identity",
            "x" * 32,
            Sender("noreply@example.test", "MyOTA"),
            SMTPConfig("smtp.example.test", 587, "user", "secret", "starttls", 5),
        )
        with patch("email_worker.deliver_smtp_async", new_callable=AsyncMock):
            asyncio.run(handle_message(Message(), Store(), resolver, config))

        self.assertEqual(events, ["claim", "delivered", "ack"])

    def test_redelivery_of_completed_work_is_acknowledged_without_resend(self):
        class Store:
            def claim(self, parsed):
                return "DELIVERED"

        class Message:
            data = json.dumps(command()).encode()
            metadata = SimpleNamespace(num_delivered=2)

            def __init__(self):
                self.acked = False

            async def ack(self):
                self.acked = True

            async def nak(self, **kwargs):
                raise AssertionError("completed work must not be retried")

            async def term(self):
                raise AssertionError("completed work must not be terminated")

        message = Message()
        resolver = SimpleNamespace(resolve=AsyncMock())
        config = WorkerConfig(
            "postgresql://unused",
            "http://identity",
            "x" * 32,
            Sender("noreply@example.test", "MyOTA"),
            SMTPConfig("smtp.example.test", 587, "user", "secret", "starttls", 5),
        )
        asyncio.run(handle_message(message, Store(), resolver, config))

        self.assertTrue(message.acked)
        resolver.resolve.assert_not_awaited()

    def test_transient_failure_persists_retry_before_delayed_nak(self):
        events = []

        class Store:
            def claim(self, parsed):
                return "CLAIMED"

            def retry(self, work_id, code):
                events.append(("retry", code))
                return 1

        class Message:
            data = json.dumps(command()).encode()
            metadata = SimpleNamespace(num_delivered=1)

            async def ack(self):
                raise AssertionError("failed delivery cannot be acknowledged")

            async def nak(self, **kwargs):
                events.append(("nak", kwargs["delay"]))

            async def term(self):
                raise AssertionError("transient delivery cannot be terminated")

        resolver = SimpleNamespace(
            resolve=AsyncMock(side_effect=RuntimeError("private address"))
        )
        config = WorkerConfig(
            "postgresql://unused",
            "http://identity",
            "x" * 32,
            Sender("noreply@example.test", "MyOTA"),
            SMTPConfig("smtp.example.test", 587, "user", "secret", "starttls", 5),
        )
        asyncio.run(handle_message(Message(), Store(), resolver, config))

        self.assertEqual(events, [("retry", "transient_delivery_failure"), ("nak", 1)])

    def test_retry_exhaustion_persists_dead_letter_then_terminates(self):
        events = []

        class Store:
            def claim(self, parsed):
                return "CLAIMED"

            def retry(self, work_id, code):
                raise AssertionError("exhausted work must not be retried")

            def dead_letter(self, work_id, code):
                events.append(("dead_letter", work_id, code))

        class Message:
            data = json.dumps(command()).encode()
            metadata = SimpleNamespace(num_delivered=8)

            async def ack(self):
                raise AssertionError("exhausted work cannot be acknowledged")

            async def nak(self, **kwargs):
                raise AssertionError("exhausted work cannot be retried")

            async def term(self):
                events.append(("term",))

        resolver = SimpleNamespace(
            resolve=AsyncMock(side_effect=RuntimeError("private"))
        )
        config = WorkerConfig(
            "postgresql://unused",
            "http://identity",
            "x" * 32,
            Sender("noreply@example.test", "MyOTA"),
            SMTPConfig("smtp.example.test", 587, "user", "secret", "starttls", 5),
        )
        asyncio.run(handle_message(Message(), Store(), resolver, config))

        self.assertEqual(
            events,
            [
                (
                    "dead_letter",
                    "d62842cf-2282-4f86-9890-a3b29745cf11",
                    "delivery_exhausted",
                ),
                ("term",),
            ],
        )

    def test_smtp_failure_exposes_only_bounded_failure_metrics(self):
        class Store:
            def claim(self, parsed):
                return "CLAIMED"

            def retry(self, work_id, code):
                return 1

        class Message:
            data = json.dumps(command()).encode()
            metadata = SimpleNamespace(num_delivered=1)

            async def ack(self):
                raise AssertionError("SMTP failure cannot be acknowledged")

            async def nak(self, **kwargs):
                self.delayed = kwargs["delay"]

            async def term(self):
                raise AssertionError("transient SMTP failure is retried")

        resolver = SimpleNamespace(
            resolve=AsyncMock(
                return_value=Recipient("alice@example.test", active=True, eligible=True)
            )
        )
        config = WorkerConfig(
            "postgresql://unused",
            "http://identity",
            "x" * 32,
            Sender("noreply@example.test", "MyOTA"),
            SMTPConfig("smtp.example.test", 587, "user", "secret", "starttls", 5),
        )
        telemetry = EmailTelemetry()
        with patch("email_worker.deliver_smtp_async", new_callable=AsyncMock) as send:
            send.side_effect = SMTPDeliveryError("provider response with private data")
            message = Message()
            asyncio.run(handle_message(message, Store(), resolver, config, telemetry))

        metrics = telemetry.registry_to_text()
        self.assertEqual(message.delayed, 1)
        self.assertIn('outcome="smtp_failure"', metrics)
        self.assertIn("myota_email_smtp_delivery_duration_seconds_count", metrics)
        self.assertNotIn("alice@example.test", metrics)
        self.assertNotIn("private data", metrics)

    def test_redrive_audit_fields_are_bounded(self):
        from email_worker import DeliveryStore

        store = DeliveryStore.__new__(DeliveryStore)
        with self.assertRaisesRegex(ValueError, "audit identifier"):
            store.request_redrive(
                "d62842cf-2282-4f86-9890-a3b29745cf11",
                "delivery_exhausted",
                "operator\nforged",
                "retry after provider recovery",
            )
        with self.assertRaisesRegex(ValueError, "reason"):
            store.request_redrive(
                "d62842cf-2282-4f86-9890-a3b29745cf11",
                "delivery_exhausted",
                "operator@example.test",
                "retry",
            )

    def test_missing_recipient_is_recorded_then_terminated(self):
        events = []

        class Store:
            def claim(self, parsed):
                return "CLAIMED"

            def dead_letter(self, work_id, error_code):
                events.append(("dead_letter", work_id, error_code))

        class Message:
            data = json.dumps(command()).encode()
            metadata = SimpleNamespace(num_delivered=1)

            async def ack(self):
                raise AssertionError("unavailable recipient cannot be acknowledged")

            async def nak(self, **kwargs):
                raise AssertionError("unavailable recipient is not retryable")

            async def term(self):
                events.append(("term",))

        resolver = SimpleNamespace(
            resolve=AsyncMock(side_effect=RecipientUnavailable("unavailable"))
        )
        config = WorkerConfig(
            "postgresql://unused",
            "http://identity",
            "x" * 32,
            Sender("noreply@example.test", "MyOTA"),
            SMTPConfig("smtp.example.test", 587, "user", "secret", "starttls", 5),
        )
        asyncio.run(handle_message(Message(), Store(), resolver, config))

        self.assertEqual(
            events,
            [
                (
                    "dead_letter",
                    "d62842cf-2282-4f86-9890-a3b29745cf11",
                    "recipient_unavailable",
                ),
                ("term",),
            ],
        )

    def test_invalid_command_persists_redacted_record_before_termination(self):
        events = []

        class Store:
            def dead_letter(self, work_id, error_code):
                events.append(("dead_letter", work_id, error_code))

        class Message:
            data = b'{"password":"never store this"}'

            async def ack(self):
                raise AssertionError("invalid work cannot be acknowledged")

            async def nak(self, **kwargs):
                raise AssertionError("invalid work cannot be retried")

            async def term(self):
                events.append(("term",))

        asyncio.run(handle_message(Message(), Store(), None, None))

        self.assertEqual(events, [("dead_letter", None, "invalid_command"), ("term",)])

    def test_metrics_only_accept_bounded_outcomes_and_templates(self):
        telemetry = EmailTelemetry()
        telemetry.record("delivered", "account-created-participant.v1")
        telemetry.record("recipient alice@example.test", "untrusted-template")

        output = telemetry.registry_to_text()
        self.assertIn(
            'outcome="delivered",template="account-created-participant.v1"',
            output,
        )
        self.assertNotIn("alice@example.test", output)
        self.assertNotIn("untrusted-template", output)

    def test_json_logs_ignore_unapproved_extra_fields(self):
        import logging

        record = logging.LogRecord(
            "myota.email",
            logging.WARNING,
            __file__,
            1,
            "email delivery attempt failed",
            (),
            None,
        )
        record.recipient = "alice@example.test"
        record.outcome = "smtp_failure"
        rendered = JsonFormatter().format(record)

        self.assertIn('"outcome":"smtp_failure"', rendered)
        self.assertNotIn("alice@example.test", rendered)

    def test_health_endpoints_distinguish_liveness_and_readiness(self):
        import urllib.error
        import urllib.request

        ready = False
        server = HealthMetricsServer(
            EmailTelemetry(), lambda: ready, host="127.0.0.1", port=0
        )
        server.start()
        base = f"http://127.0.0.1:{server.port}"
        try:
            with urllib.request.urlopen(f"{base}/healthz") as response:
                self.assertEqual(response.status, 200)
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(f"{base}/readyz")
            self.assertEqual(error.exception.code, 503)
            ready = True
            with urllib.request.urlopen(f"{base}/readyz") as response:
                self.assertEqual(response.status, 200)
            with urllib.request.urlopen(f"{base}/metrics") as response:
                self.assertIn(b"myota_email_delivery_attempts_total", response.read())
        finally:
            server.close()

    def test_parse_accepts_allowlisted_admin_template(self):
        payload = command(
            "account-created-administrator.v1",
            {
                "createdAccountName": "New Admin",
                "createdAccountRole": "ADMINISTRATOR",
            },
        )
        parsed = EmailCommand.parse(json.dumps(payload).encode())
        self.assertEqual(parsed.template_id, "account-created-administrator.v1")

    def test_parse_rejects_address_tokens_and_arbitrary_fields(self):
        unsafe_cases = (
            {"displayName": "Alice", "emailAddress": "alice@example.test"},
            {"displayName": "Alice", "recoveryToken": "secret"},
            {"displayName": "Alice", "html": "<img src=x>"},
        )
        for data in unsafe_cases:
            with self.subTest(data=data), self.assertRaises(InvalidCommand):
                EmailCommand.parse(json.dumps(command(template_data=data)).encode())

    def test_parse_rejects_unknown_template_and_oversized_command(self):
        unknown = command("password-reset.v1", {"displayName": "Alice"})
        with self.assertRaises(InvalidCommand):
            EmailCommand.parse(json.dumps(unknown).encode())
        with self.assertRaises(InvalidCommand):
            EmailCommand.parse(b" " * (8 * 1024 + 1))

    def test_unknown_contract_version_is_dead_lettered_without_success_ack(self):
        payload = command()
        payload["workType"] = "email.send.v2"
        events = []

        class Store:
            def dead_letter(self, work_id, code):
                events.append(("dead_letter", work_id, code))

        class Message:
            data = json.dumps(payload).encode()

            async def ack(self):
                events.append(("ack",))

            async def term(self):
                events.append(("term",))

        config = WorkerConfig(
            "postgresql://unused",
            "http://identity",
            "x" * 32,
            Sender("noreply@example.test", "MyOTA"),
            SMTPConfig("smtp.example.test", 587, "user", "secret", "starttls", 5),
        )
        asyncio.run(
            handle_message(
                Message(), Store(), SimpleNamespace(), config
            )
        )

        self.assertEqual(
            events,
            [("dead_letter", None, "invalid_command"), ("term",)],
        )

    def test_render_escapes_user_content_in_html(self):
        parsed = EmailCommand.parse(json.dumps(command()).encode())
        message = render_message(
            parsed,
            Recipient("alice@example.test", active=True, eligible=True),
            Sender("noreply@example.test", "MyOTA"),
        )
        html = message.get_body(preferencelist=("html",)).get_content()
        self.assertIn("&lt;Alice &amp; Bob&gt;", html)
        self.assertNotIn("<Alice & Bob>", html)

    def test_render_fails_closed_for_inactive_recipient(self):
        parsed = EmailCommand.parse(json.dumps(command()).encode())
        with self.assertRaises(RecipientUnavailable):
            render_message(
                parsed,
                Recipient("alice@example.test", active=False, eligible=True),
                Sender("noreply@example.test", "MyOTA"),
            )

    def test_smtp_config_requires_password_and_verified_tls_mode(self):
        base = {
            "EMAIL_SMTP_HOST": "smtp.example.test",
            "EMAIL_SMTP_PORT": "587",
            "EMAIL_SMTP_USERNAME": "myota",
            "EMAIL_SMTP_PASSWORD": "secret",
        }
        config = SMTPConfig.from_env(base)
        self.assertEqual(config.tls_mode, "starttls")
        for extra in (
            {"EMAIL_SMTP_PASSWORD": ""},
            {"EMAIL_SMTP_TLS_MODE": "none"},
            {"EMAIL_SMTP_TIMEOUT_SECONDS": "60"},
        ):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                SMTPConfig.from_env({**base, **extra})

    def test_secrets_can_be_loaded_from_mounted_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "smtp-password"
            path.write_text("test-only-secret\n", encoding="utf-8")
            self.assertEqual(
                secret_from_env(
                    "EMAIL_SMTP_PASSWORD", {"EMAIL_SMTP_PASSWORD_FILE": str(path)}
                ),
                "test-only-secret",
            )
            with self.assertRaisesRegex(ValueError, "cannot both"):
                secret_from_env(
                    "EMAIL_SMTP_PASSWORD",
                    {
                        "EMAIL_SMTP_PASSWORD": "inline",
                        "EMAIL_SMTP_PASSWORD_FILE": str(path),
                    },
                )

    @patch("email_core.ssl.create_default_context")
    @patch("email_core.smtplib.SMTP")
    def test_smtp_uses_starttls_before_authentication(self, smtp_class, tls_context):
        config = SMTPConfig("smtp.example.test", 587, "user", "secret", "starttls", 5)
        parsed = EmailCommand.parse(json.dumps(command()).encode())
        message = render_message(
            parsed,
            Recipient("alice@example.test", active=True, eligible=True),
            Sender("noreply@example.test", "MyOTA"),
        )

        deliver_smtp(config, message)

        calls = [call[0] for call in smtp_class.return_value.method_calls]
        self.assertLess(calls.index("starttls"), calls.index("login"))
        smtp_class.return_value.send_message.assert_called_once_with(message)
        tls_context.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
