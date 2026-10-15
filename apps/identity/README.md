# MyOTA identity service

The administrative permission catalogue exposes `observability.view` for
Grafana metrics and dashboards. The Gateway validates each session through the
live Identity API and derives scopes from current role assignments. The retired
`operations.read` permission is removed from stored role definitions and is
not returned by the current-account API.

MyOTA is a programme-agnostic platform for outdoor activation programmes. MPOTA is represented as a configured programme, not as the platform itself. No rules or charter text are copied from POTA or any other programme: every programme supplies its own configuration, policy, eligibility, awards and public charter.

This repository owns amateur-radio-aware accounts and authentication. It is
independent of Keycloak and does not treat an external OIDC provider as the
source of truth. The service owns accounts/persons, operator/SWL
participation, one primary callsign plus additional callsigns, verification
lifecycle, roles/scopes, sessions, recovery, privacy, security events, and
optional per-programme OIDC mappings.

## What works now

- Amateur-radio-aware identity: operator/SWL participation, multiple callsigns, one primary callsign, lifecycle and verification fields.
- The identity service does not own programmes, entities, activity/QSOs,
  awards, or admin-web presentation; those boundaries are defined in the
  [repository map](https://github.com/myota-platform/myota-docs/blob/main/docs/repository-map.md).
- The current slice includes login, account administration,
  callsign verification fields, scoped roles, privacy export/deactivation,
  and security-event primitives.

Public participant registration is disabled until verified-email setup and
registration abuse controls are implemented and enabled. Account creation
requires `identity.accounts.create`; new accounts receive the `PARTICIPANT`
role and stay in `PENDING_SETUP` without a password. Granting additional roles
also requires `identity.roles.assign`; callers can grant only roles whose
permissions are a strict subset of their current permissions, and cannot
change their own roles. Invitation and credential setup are still pending the
email-delivery workstream.

The email worker resolves addresses only through the internal
`GET /v1/identity/internal/email-recipients/{accountId}` API. Identity issues
that worker a five-minute token with the fixed `identity.email.resolve` scope
from the Secret-backed `MYOTA_EMAIL_SERVICE_CLIENT_SECRET`; callers cannot
select scopes. The endpoint returns only the current deliverable address and
accepts only active accounts. Missing, pending-setup, deactivated, and
unaddressable accounts share the same HTTP 404 response. The public Gateway rejects `/v1/identity/internal/`. Deploy must
provision the client credential as a runtime Secret before the endpoint can be
used. Addresses must not appear in logs, telemetry, or NATS payloads.

Global operators are exempt from the general per-account/source login-attempt
throttle so repeated legitimate administrator sign-ins do not lock out the
platform. The separate temporary account lock after repeated invalid passwords
still applies to global operators as a brute-force safeguard.

Account administration also exposes the Phase 1 resource aliases: `PATCH
/v1/identity/accounts/{accountId}`, `PATCH
/v1/identity/roles/{roleCode}`, `PUT
/v1/identity/accounts/{accountId}/role-assignments`, and `PUT
/v1/identity/accounts/{accountId}/primary-callsign`. The older action routes
remain compatibility aliases. See the [Phase 1 API resource update record](https://github.com/myota-platform/myota-docs/blob/main/docs/api-phase1-resource-updates.md).

The unit-test adapter can run in memory. Durable runtime loads Identity-owned
accounts, credentials, role definitions and assignments, sessions, revocations,
recovery tokens, login limits, callsign evidence, security events, and OIDC
mappings from their PostgreSQL tables inside each request transaction. Writes
are serialized with a transaction-scoped advisory lock across replicas; reads
use a repeatable-read snapshot. Startup and requests fail closed unless the
restartable `service-state-jsonb-v1` backfill marker exists. The legacy
`service_state` row is retained for migration recovery and is not read or
written by Identity runtime code. Apply Core migrations `002` and `003` before
rolling out this runtime. Production secrets remain deployment-managed; do not
use the test adapter as a production data store.

## Test and run locally

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 run_identity.py
```

The standalone entry point listens on port 8001 and needs explicit database
configuration for durable storage. For the complete durable stack, use
[myota-deploy with Colima](https://github.com/myota-platform/myota-deploy#run-the-vertical-slice):
identity uses plain PostgreSQL `myota_core`, not PostGIS or `myota_activity`.
The [observability access guide](https://github.com/myota-platform/myota-docs/blob/main/docs/observability/overview.md) documents the current Grafana authorization boundary.

The remaining Internet-facing identity gates are listed in the [charter gap
analysis](https://github.com/myota-platform/myota-docs/blob/main/docs/charter-gap-analysis.md),
including production key management, abuse controls, user self-service, and
security review.

The durable runtime exposes bounded aggregate gauges at `/metrics` for user
bounded request counters and duration histograms, plus aggregate gauges for
user counts by fixed participation type, callsigns, active role assignments,
retained security events, and currently locked accounts. Request labels use
only HTTP method, declared route template, and status code. Domain gauges omit
account, callsign, email, credential, and event identifiers. The OTel Collector
scrapes `/metrics` every 15 seconds.

## Architecture

Read the [MyOTA charter](https://github.com/myota-platform/myota-docs/blob/main/docs/project-charter.md)
for the platform purpose and policy boundaries. MPOTA remains sample data
only; this service must support any programme without inheriting another
programme's rules.

## Source project

The original `ea7klk/mpota` repository remains untouched; see the
[migration strategy](https://github.com/myota-platform/myota-docs/blob/main/docs/migration-from-mpota.md).
