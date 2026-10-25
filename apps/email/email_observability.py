"""Bounded email-worker metrics, tracing setup, and health endpoints."""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.exposition import CONTENT_TYPE_LATEST

OUTCOMES = (
    "delivered",
    "duplicate",
    "dead_letter",
    "invalid_command",
    "smtp_failure",
    "identity_failure",
    "delivery_failure",
)
TEMPLATES = (
    "account-created-participant.v1",
    "account-created-administrator.v1",
    "unknown",
)


class JsonFormatter(logging.Formatter):
    """Emit only explicitly selected, bounded fields; never serialize extras."""

    def format(self, record: logging.LogRecord) -> str:
        value: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "severity": record.levelname,
            "service": "myota-email-service",
            "message": record.getMessage(),
        }
        outcome = getattr(record, "outcome", None)
        if outcome in OUTCOMES:
            value["outcome"] = outcome
        error_code = getattr(record, "error_code", None)
        if error_code in {
            "invalid_command",
            "recipient_unavailable",
            "delivery_exhausted",
            "transient_delivery_failure",
        }:
            value["error_code"] = error_code
        return json.dumps(value, separators=(",", ":"))


class EmailTelemetry:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.attempts = Counter(
            "myota_email_delivery_attempts_total",
            "Email work outcomes recorded by the consumer.",
            ("outcome", "template"),
            registry=self.registry,
        )
        self.duration = Histogram(
            "myota_email_delivery_duration_seconds",
            "Time spent resolving and delivering one email command.",
            ("template",),
            registry=self.registry,
        )
        self.smtp_duration = Histogram(
            "myota_email_smtp_delivery_duration_seconds",
            "Time spent in the bounded SMTP delivery operation.",
            registry=self.registry,
        )
        self.smtp_available = Gauge(
            "myota_email_smtp_last_delivery_available",
            "Whether the last SMTP transaction succeeded (initially unknown/0).",
            registry=self.registry,
        )
        self.pending = Gauge(
            "myota_email_queue_pending_messages",
            "Messages pending on the email delivery durable.",
            registry=self.registry,
        )
        self.ack_pending = Gauge(
            "myota_email_queue_ack_pending_messages",
            "Messages currently awaiting acknowledgement on the durable.",
            registry=self.registry,
        )
        self.oldest_age = Gauge(
            "myota_email_queue_oldest_message_age_seconds",
            "Age of the oldest pending email work command.",
            registry=self.registry,
        )
        self.queue_max_messages = Gauge(
            "myota_email_queue_max_messages",
            "Configured finite message limit for the email JetStream stream.",
            registry=self.registry,
        )
        try:
            configured_max = int(os.environ.get("EMAIL_QUEUE_MAX_MESSAGES", "0"))
        except ValueError:
            configured_max = 0
        self.queue_max_messages.set(max(0, configured_max))
        self._tracer = None
        self._trace_provider = None
        self._meter_provider = None
        self._logger_provider = None
        self._otel_attempts = None
        self._otel_duration = None
        self._otel_smtp_duration = None
        self._configure_otel()

    def _configure_otel(self) -> None:
        enabled = os.environ.get("MYOTA_OTEL_ENABLED", "0").strip().lower()
        if enabled in {"", "0", "false", "no", "off"}:
            return
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
                OTLPLogExporter,
            )
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
            from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            endpoint = os.environ.get(
                "OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317"
            )
            resource = Resource.create(
                {
                    "service.name": os.environ.get(
                        "OTEL_SERVICE_NAME", "myota-email-service"
                    ),
                    "service.namespace": "myota",
                    "deployment.environment": os.environ.get(
                        "MYOTA_ENV", "development"
                    ),
                    "service.instance.id": os.environ.get("HOSTNAME", "local"),
                }
            )
            self._trace_provider = TracerProvider(resource=resource)
            self._trace_provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(
                        endpoint=endpoint, insecure=not endpoint.startswith("https://")
                    )
                )
            )
            trace.set_tracer_provider(self._trace_provider)
            self._tracer = trace.get_tracer("myota.email")
            reader = PeriodicExportingMetricReader(
                OTLPMetricExporter(
                    endpoint=endpoint, insecure=not endpoint.startswith("https://")
                ),
                export_interval_millis=int(
                    os.environ.get("MYOTA_OTEL_METRIC_INTERVAL_MS", "15000")
                ),
            )
            self._meter_provider = MeterProvider(
                resource=resource, metric_readers=[reader]
            )
            self._logger_provider = LoggerProvider(resource=resource)
            self._logger_provider.add_log_record_processor(
                BatchLogRecordProcessor(
                    OTLPLogExporter(
                        endpoint=endpoint, insecure=not endpoint.startswith("https://")
                    )
                )
            )
            logging.getLogger("myota.email").addHandler(
                LoggingHandler(
                    level=logging.NOTSET, logger_provider=self._logger_provider
                )
            )
            meter = self._meter_provider.get_meter("myota.email")
            self._otel_attempts = meter.create_counter(
                "myota.email.delivery.attempts",
                unit="{attempt}",
                description="Email delivery outcomes recorded by the worker",
            )
            self._otel_duration = meter.create_histogram(
                "myota.email.delivery.duration",
                unit="s",
                description="Time spent resolving and delivering one message",
            )
            self._otel_smtp_duration = meter.create_histogram(
                "myota.email.smtp.delivery.duration",
                unit="s",
                description="Time spent in one SMTP delivery operation",
            )
        except Exception as exc:  # noqa: BLE001 - telemetry must fail open
            logging.getLogger("myota.email").warning(
                "OpenTelemetry setup failed; continuing with Prometheus metrics",
                extra={"error_code": type(exc).__name__},
            )
            self._tracer = None

    def span(self, headers: Any = None):
        """Return a context manager that extracts W3C trace context if present."""
        if self._tracer is None:
            from contextlib import nullcontext

            return nullcontext(None)
        try:
            from opentelemetry import propagate

            carrier = {}
            if headers:
                for key, value in headers.items():
                    if isinstance(key, str) and isinstance(value, str):
                        carrier[key.lower()] = value
            return self._tracer.start_as_current_span(
                "email.delivery",
                context=propagate.extract(carrier),
                record_exception=False,
                set_status_on_exception=False,
            )
        except Exception:  # noqa: BLE001 - fall back to a local span context
            return self._tracer.start_as_current_span(
                "email.delivery",
                record_exception=False,
                set_status_on_exception=False,
            )

    def record(self, outcome: str, template: str) -> None:
        if outcome not in OUTCOMES:
            return
        safe_template = template if template in TEMPLATES else "unknown"
        self.attempts.labels(outcome=outcome, template=safe_template).inc()
        if self._otel_attempts is not None:
            self._otel_attempts.add(
                1, {"email.outcome": outcome, "email.template_id": safe_template}
            )

    def observe_duration(self, template: str, seconds: float) -> None:
        if template not in TEMPLATES:
            template = "unknown"
        duration = max(0.0, seconds)
        self.duration.labels(template=template).observe(duration)
        if self._otel_duration is not None:
            self._otel_duration.record(duration, {"email.template_id": template})

    def observe_smtp_duration(self, seconds: float) -> None:
        duration = max(0.0, seconds)
        self.smtp_duration.observe(duration)
        if self._otel_smtp_duration is not None:
            self._otel_smtp_duration.record(duration)

    def record_smtp_availability(self, available: bool) -> None:
        self.smtp_available.set(1 if available else 0)

    async def update_queue(self, js: Any, consumer_info: Any) -> None:
        pending = max(0, int(getattr(consumer_info, "num_pending", 0)))
        ack_pending = max(0, int(getattr(consumer_info, "num_ack_pending", 0)))
        self.pending.set(pending)
        self.ack_pending.set(ack_pending)
        age = 0.0
        if pending + ack_pending > 0:
            ack_floor = getattr(consumer_info, "ack_floor", None)
            first_pending_seq = int(getattr(ack_floor, "stream_seq", 0)) + 1
            try:
                oldest = await js.get_msg("MYOTA_EMAIL_WORK", seq=first_pending_seq)
            except Exception:  # noqa: BLE001 - queue metrics are best effort
                oldest = None
            first_timestamp = getattr(oldest, "time", None)
        else:
            first_timestamp = None
        if isinstance(first_timestamp, datetime):
            if first_timestamp.tzinfo is None:
                first_timestamp = first_timestamp.replace(tzinfo=timezone.utc)
            age = max(
                0.0,
                (datetime.now(timezone.utc) - first_timestamp).total_seconds(),
            )
        self.oldest_age.set(age)

    def registry_to_text(self) -> str:
        return generate_latest(self.registry).decode("utf-8")

    def shutdown(self) -> None:
        for provider, timeout_millis in (
            (self._trace_provider, None),
            (self._meter_provider, 3000),
            (self._logger_provider, None),
        ):
            if provider is not None:
                try:
                    if timeout_millis is None:
                        provider.shutdown()
                    else:
                        provider.shutdown(timeout_millis=timeout_millis)
                except Exception:  # noqa: BLE001 - exporter shutdown is best effort
                    logging.getLogger("myota.email").warning(
                        "OpenTelemetry shutdown failed"
                    )


class HealthMetricsServer:
    def __init__(
        self,
        telemetry: EmailTelemetry,
        ready: Callable[[], bool],
        host: str = "0.0.0.0",
        port: int = 9108,
    ) -> None:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                path = self.path.split("?", 1)[0]
                if path == "/healthz":
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"ok\n")
                    return
                if path == "/readyz":
                    status = 200 if ready() else 503
                    self.send_response(status)
                    self.end_headers()
                    self.wfile.write(b"ready\n" if status == 200 else b"not ready\n")
                    return
                if path == "/metrics":
                    body = generate_latest(outer.telemetry.registry)
                    self.send_response(200)
                    self.send_header("Content-Type", CONTENT_TYPE_LATEST)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_error(404)

            def log_message(self, _format: str, *_args: Any) -> None:
                return

        self.telemetry = telemetry
        self._server = ThreadingHTTPServer((host, port), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="email-health-metrics",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=3)
