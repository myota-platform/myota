# MyOTA asynchronous email worker

The worker consumes the registered `email.send.v1` command from the
`MYOTA_EMAIL_WORK` stream and shared `email-delivery-v1` pull durable. It
validates the bounded envelope and one of the allowlisted templates, resolves
the current recipient through Identity's service-token-protected API, renders
escaped text and HTML, and submits through SMTP with verified STARTTLS or
implicit TLS. It has no inbound send API and no access to Identity storage.
The worker loads the canonical JSON Schema from `contracts/schemas/work` at
startup; the image includes that schema and its shared envelope schema. Contract
changes trigger the consumer validation workflow.

The accepted ownership, privacy, retry/recovery, and operator guidance is in
the canonical [email delivery architecture and operations record](https://github.com/myota-platform/myota-docs/blob/main/docs/operations/messaging/email-delivery.md)
and [ADR-0010](https://github.com/myota-platform/myota-docs/blob/main/docs/architecture/decisions/0010-asynchronous-email-delivery.md).

## Runtime behavior

`email_worker.py` uses the service-owned PostgreSQL delivery ledger to claim
stable work IDs and deduplicate completed deliveries. It commits `DELIVERED`
before acknowledging JetStream. Retryable failures record a bounded error code
before a delayed NAK; unavailable recipients and exhausted deliveries are
recorded in a redacted dead-letter table before termination. An SMTP acceptance
followed by process failure before the ledger commit can cause a duplicate; the
service provides at-least-once delivery, not exactly once.

The initial schema is in `migrations/001_email_delivery.sql` and is applied
idempotently before the worker becomes ready. The readiness endpoint requires a
validated NATS durable and a reachable PostgreSQL database. `/healthz` reports
process liveness, `/readyz` reports dependency readiness, and `/metrics` exposes
bounded outcomes, latency, and queue gauges on port 9108. When
`MYOTA_OTEL_ENABLED=1`, the worker exports spans and metrics through OTLP. NATS
W3C trace headers are extracted; spans, logs, and metric labels exclude
addresses, account IDs, work IDs, SMTP data, and template values.

For an authorized recovery, use the worker's `redrive` command with an
operator-supplied audit identity and reason. It records the request and resets
only the ledger row. Then republish the same stable work ID through its
producer-owned outbox. The worker does not retain the email command, recipient,
or message content for recovery. Use cluster access controls and audit logs to
authorize this operation; do not put sensitive data in the reason.

## Configuration

`EMAIL_DATABASE_URL` is the service-owned `myota_email` database. The other
required settings are `IDENTITY_INTERNAL_URL`,
`MYOTA_EMAIL_SERVICE_CLIENT_SECRET`, `EMAIL_SENDER_ADDRESS`,
`EMAIL_SENDER_DISPLAY_NAME`, `EMAIL_SMTP_HOST`, `EMAIL_SMTP_PORT`,
`EMAIL_SMTP_USERNAME`, `EMAIL_SMTP_PASSWORD`, `EMAIL_SMTP_TLS_MODE`, and
`EMAIL_SMTP_TIMEOUT_SECONDS`. In Kubernetes, only the SMTP password and the
Identity client credential belong in Secrets; sender, account, host, port, TLS
mode, and timeouts are ordinary configuration. No values or credentials belong
in Helm values or rendered manifests.

## Focused checks

From the repository root:

```text
PYTHONPATH=apps/email python3 -m unittest discover -s apps/email/tests -v
```

The current checks use fake SMTP and mocked NATS/Identity/ledger boundaries;
they do not send real email. Helm deployment, database integration, and full
stack telemetry qualification remain separate deployment gates.
