# Geodata deployment migrations

The migration source is [`apps/geodata/migrations/`](../../../../apps/geodata/migrations/).
This directory is the copy consumed by the current deployment runner. Update
the app source first, then synchronize this tree; do not edit the copy alone.

Applied baseline files are immutable. Add numbered forward migrations for
schema changes. See [database migration ownership](../../README.md) and the
[Geodata migration source](../../../../apps/geodata/migrations/README.md).
