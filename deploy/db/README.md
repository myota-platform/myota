# Database migrations

The deployment provisions three independent databases: Core PostgreSQL for
Identity and Programmes, Activity PostgreSQL, and Geodata PostGIS. Services
own their schemas; cross-service references use IDs and events.

`deploy/db/migrations/run.sh` applies the deployment migration tree and checks
migration checksums. Core migrations live under `core/`. Activity and Geodata
migration sources live with their services under `apps/`; synchronized copies
under `activity/` and `geo/` are still consumed by the current deployment
runner. Update the app source first, then keep the deployment copy aligned.

Applied baseline files are immutable. Add numbered forward migrations for
schema changes. The [database operations guide](https://github.com/myota-platform/myota-docs/tree/main/docs/operations/databases)
contains the backup, restore, and rebuild procedures.
