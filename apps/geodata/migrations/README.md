# Geodata migrations

This directory is the canonical source for the `myota_geo` PostGIS schema.
`001_geodata_baseline.sql` creates the current schema; it contains no
application rows. Do not edit an applied baseline. Add numbered forward
migrations for later schema changes.

The current deployment runner reads the synchronized copy at
[`deploy/db/migrations/geo/`](../../../deploy/db/migrations/geo/). Update this
source first and keep that copy aligned until the runner consumes this
location directly.

See the [database migration guide](../../../deploy/db/README.md) and the
[Geodata roadmap and evidence](https://github.com/myota-platform/myota-docs/tree/main/docs/geodata).
