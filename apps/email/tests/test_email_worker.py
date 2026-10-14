from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from email_core import (
    EmailCommand,
    InvalidCommand,
    Recipient,
    RecipientUnavailable,
    Sender,
    SMTPConfig,
    deliver_smtp,
    render_message,
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
