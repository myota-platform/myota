# MyOTA

MyOTA is an API-first platform for outdoor activation programmes. This
repository is the application-source monorepo. Services and browser apps remain
separately built and deployed.

## Repository map

- `apps/` — Identity, Programmes, Activity, Geodata, and email delivery.
- `web/` — separate Admin and participant apps.
- `contracts/` — HTTP and event contracts, schemas, and clients.
- `deploy/` — Compose, Helm, migrations, and runtime configuration.
- `integration/` — cross-service checks.

## Run locally

```bash
cp deploy/.env.example deploy/.env
cp apps/geodata/.env.example apps/geodata/.env
docker compose -f deploy/compose.yaml up --build
```

See the [deployment guide](deploy/README.md) for local setup and deployment
commands. Component READMEs describe their local checks. The [MyOTA docs](https://github.com/myota-platform/myota-docs) hold the architecture, product policies, operations guides, and qualification evidence. Repository workflow and branch rules are in [`AGENTS.md`](AGENTS.md).
