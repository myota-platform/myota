# Database migrations and ownership

The deployment provisions three independent database targets. Identity and
Programme share `myota_core`; Activity owns `myota_activity`; Geodata owns
`myota_geo` with PostGIS. Cross-service relationships use opaque identifiers
and events. The migration runner never copies application rows between these
databases.

The monorepo is the deployment migration source of truth:

- Core: `deploy/db/migrations/core/`, including the Core baseline and the
  numbered Identity relational-auth migrations `002` and `003`.
- Activity: `apps/activity/migrations/001_activity_baseline.sql`, mirrored at
  `deploy/db/migrations/activity/001_activity_baseline.sql`.
- Geodata: `apps/geodata/migrations/001_geodata_baseline.sql`, mirrored at
  `deploy/db/migrations/geo/001_geodata_baseline.sql`.

Deploy owns the migration runner and rollout ordering; service-owned schemas
remain with their owning applications. The runner checks each migration's
SHA-256 checksum, applies a fresh baseline transactionally, adopts an
already-ready schema only after a database-specific sentinel check, and leaves
readiness false on failure. It fails closed on checksum drift or an unready
database that already contains application relations. Only baseline files are
compared with the baseline-ledger checksum; each numbered forward migration
has its own ledger entry and checksum in `public.myota_schema_migration`.
Applied baseline files are immutable.

The `myota-platform` Testing branch mirrors the runner and deployment migration
SQL. Its Identity migration files and corrected baseline-checksum guard are
kept synchronized with this monorepo. Former repository copies are migration
history or mirrors, not independent deployment sources.

A baseline is schema-only and contains no domain rows. The [database baseline
inventory and rebuild procedure](https://github.com/myota-platform/myota-docs/blob/main/docs/operations/databases/baseline-migration-inventory.md)
records captured schema evidence and data-preserving backup/restore gates. The
[Identity auth PostgreSQL restore evidence](https://github.com/myota-platform/myota-docs/blob/testing/docs/domain/identity/evidence/postgresql-auth-restore-2026-10-15.md)
records the Test-only auth migration and isolated restore check. Backups and
capacity planning remain independent per database. Only Geodata requires
PostGIS; chart-managed StatefulSets are single-replica and not highly
available.
