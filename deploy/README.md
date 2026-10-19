# Deployment

`deploy/` owns Compose, Helm/Fleet configuration, migration execution, and
observability provisioning. Service source lives under `apps/`; browser apps
live under `web/`.

## Local Compose

From the repository root, create the ignored local environment files and start
the stack:

```bash
cp deploy/.env.example deploy/.env
cp apps/geodata/.env.example apps/geodata/.env
docker compose -f deploy/compose.yaml up --build
```

The stack uses three independent databases: Core PostgreSQL, Activity
PostgreSQL, and Geodata PostGIS. NATS carries durable work and events; SeaweedFS
provides S3-compatible object storage. Compose publishes the Gateway and Admin
web on ports 8080 and 8090.

To use the published images instead of building locally:

```bash
docker compose -f deploy/compose.yaml -f deploy/compose.images.yaml up \
  --no-build --pull always -d
```

The optional local observability profile is enabled with:

```bash
docker compose -f deploy/compose.yaml --profile observability up -d --build
```

Do not commit either `.env` file. See [Compose configuration](compose.yaml) and
[image configuration](compose.images.yaml) for the complete service settings.

## Checks and deployment

Run deployment tests from this directory:

```bash
cd deploy
python3 -m pip install -r requirements.txt -r requirements-dev.txt
python3 -m unittest discover -s tests -v
```

Use the [Helm chart guide](helm/myota/README.md) for chart details, the
[deployment runbook](helm/myota/DEPLOYMENT.md) for the production Fleet/K3s
procedure, and the [test deployment guide](helm/myota-test/README.md) for the
isolated test release. CI runs Helm rendering and lint checks.

The migration runner is owned here; database schemas remain owned by their
services. See [database migration ownership](db/README.md).

## Source boundary

`apps/<service>/` is the canonical service source. `deploy/services/` still
contains runtime copies used by parts of the Compose and deployment image
paths. Keep those copies synchronized until the remaining consumers have been
moved; do not edit a copy as an independent source. Component image workflows
and local Compose do not yet use identical build paths for every service.

Cross-service architecture, operational policy, and current deployment
qualification live in the [MyOTA documentation repository](https://github.com/myota-platform/myota-docs).
