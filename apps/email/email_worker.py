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
from datetime import datetime
from email.message import EmailMessage
from html import escape
from typing import Protocol

MAX_COMMAND_BYTES = 8 * 1024
EMAIL_WORK_TYPE = "email.send.v1"
SUPPORTED_TEMPLATES = {
    "account-created-participant.v1",
    "account-created-administrator.v1",
}


class InvalidCommand(ValueError):
    """A command is malformed or outside the checked-in email contract."""


class RecipientUnavailable(RuntimeError):
    """The Identity-owned account cannot receive this email."""


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
            raise InvalidCommand("command exceeds the 8192-byte contract limit")
        try:
            envelope = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidCommand("command is not valid JSON") from exc
        if not isinstance(envelope, dict):
            raise InvalidCommand("command envelope must be an object")
        allowed = {
            "envelopeVersion",
            "workId",
            "workType",
            "createdAt",
            "producer",
            "aggregate",
            "correlationId",
            "causationId",
            "payload",
        }
        required = {
            "envelopeVersion",
            "workId",
            "workType",
            "createdAt",
            "producer",
            "payload",
        }
        if set(envelope) - allowed or required - set(envelope):
            raise InvalidCommand("command envelope fields do not match contract")
        if envelope["envelopeVersion"] != 1 or envelope["workType"] != EMAIL_WORK_TYPE:
            raise InvalidCommand("unsupported work contract version")
        work_id = _uuid(envelope["workId"], "workId")
        payload = envelope["payload"]
        if not isinstance(payload, dict) or set(payload) != {
            "recipientAccountId",
            "templateId",
            "templateData",
        }:
            raise InvalidCommand("email payload fields do not match contract")
        recipient_id = _uuid(payload["recipientAccountId"], "recipientAccountId")
        template_id = payload["templateId"]
        if template_id not in SUPPORTED_TEMPLATES:
            raise InvalidCommand("unsupported email template")
        data = payload["templateData"]
        if not isinstance(data, dict):
            raise InvalidCommand("templateData must be an object")
        if template_id == "account-created-participant.v1":
            _exact_text_fields(data, {"displayName": (1, 120)})
        else:
            _exact_text_fields(
                data,
                {
                    "createdAccountName": (1, 120),
                    "createdAccountRole": (1, 20),
                },
            )
            if data["createdAccountRole"] not in {"PARTICIPANT", "ADMINISTRATOR"}:
                raise InvalidCommand("unsupported created-account role")
        created_at = envelope["createdAt"]
        if not isinstance(created_at, str) or not created_at.endswith("Z"):
            raise InvalidCommand("createdAt must be a UTC timestamp")
        try:
            datetime.fromisoformat(created_at)
        except ValueError as exc:
            raise InvalidCommand("createdAt must be an RFC3339 timestamp") from exc
        producer = envelope["producer"]
        if not isinstance(producer, str) or not producer.strip() or len(producer) > 80:
            raise InvalidCommand("producer must be a bounded non-empty string")
        correlation_id = envelope.get("correlationId")
        if correlation_id is not None and (
            not isinstance(correlation_id, str) or len(correlation_id) > 200
        ):
            raise InvalidCommand("correlationId exceeds the contract limit")
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


def _exact_text_fields(data: dict, fields: dict[str, tuple[int, int]]) -> None:
    if set(data) != set(fields):
        raise InvalidCommand("template fields do not match the allowlist")
    for name, (minimum, maximum) in fields.items():
        value = data[name]
        if not isinstance(value, str) or not minimum <= len(value) <= maximum:
            raise InvalidCommand("template field is outside its size limit")


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
            password=values.get("EMAIL_SMTP_PASSWORD", ""),
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
    await asyncio.to_thread(deliver_smtp, config, message)
