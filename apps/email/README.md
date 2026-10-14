# MyOTA asynchronous email worker

This app is the consumer side of the versioned `email.send.v1` command. The
command contains an Identity account reference and bounded template data; the
worker must resolve the current deliverable address through Identity and must
not query Identity's database. SMTP is at least once: acceptance by the SMTP
server followed by a worker crash can cause a duplicate.

`email_core.py` currently provides strict contract-shaped validation,
allowlisted escaped message rendering, bounded TLS-only SMTP configuration,
and a blocking SMTP adapter exposed through an async helper. The NATS durable,
recipient-resolution endpoint, PostgreSQL delivery/idempotency state, retry
and dead-letter handling, telemetry server, and deployment wiring are not yet
implemented. The service is not deployable or authorized to publish email
until those gates and their issues are complete.

Configuration reads the SMTP server, account, sender identity, TLS mode, and
timeouts from runtime settings. `EMAIL_SMTP_PASSWORD` must be provided through
a Secret-backed environment variable. Do not put SMTP credentials, recipient
addresses, message bodies, tokens, or template values in logs, traces, metrics,
NATS headers, or delivery diagnostics.

Run focused unit tests from the monorepo root with:

```text
PYTHONPATH=apps/email python3 -m unittest discover -s apps/email/tests -v
```
