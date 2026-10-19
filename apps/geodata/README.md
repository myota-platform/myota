# Geodata service

Geodata owns the platform-wide spatial catalogue, PostGIS data, imports,
provenance, review, and location enrichment. It exposes an API and separate
workers for import processing, enrichment, and retention. Programme eligibility
and awards are owned by other services.

## Development

From this directory:

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
python3 -m unittest discover -s tests -v
python3 run_geodata.py
```

The API listens on port `8003`. Durable operation requires PostgreSQL/PostGIS,
NATS, and the configured object store. Copy `.env.example` for local settings;
never commit real credentials. The container build context is this directory.

The CI workflow also runs PostGIS concurrency, JetStream recovery, and upload
session checks with disposable dependencies. A passing unit suite alone does
not establish capacity or deployment qualification; see the [Geodata CI
workflow](../../.github/workflows/geodata.yml).

## Further documentation

- [Geodata architecture, roadmaps, and evidence](https://github.com/myota-platform/myota-docs/tree/main/docs/geodata)
- [Current system state](https://github.com/myota-platform/myota-docs/blob/main/docs/architecture/current-state.md)
- [Geodata API contract](../../contracts/openapi.yaml)
- [Geodata migration source](migrations/README.md)
- [Deployment and migration ownership](../../deploy/README.md)
