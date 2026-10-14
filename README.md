# MyOTA

MyOTA is an API-first platform for outdoor activation programmes. This is the
application-source monorepo: services, frontends, contracts, deployment, and
integration checks share a repository while remaining separately built and
deployed.

## Repository layout

- `apps/` — Identity, Programme, Activity, and Geodata services; the future
  email worker placeholder is under `apps/email/`.
- `web/` — independent Admin and participant web applications.
- `contracts/` — OpenAPI, event schemas, and generated clients.
- `deploy/` — Compose, Helm, database migrations, and operational scripts.
- `integration/` — cross-service compatibility and smoke tests.

Service processes, data ownership, APIs, and release boundaries remain
independent. See the canonical architecture and current-state records in
[myota-docs](https://github.com/myota-platform/myota-docs).

Snapshots are taken from former repositories' `main` branches only; no
testing or feature branch history is imported. `myota-docs` and `.github`
remain separate.
