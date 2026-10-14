# MyOTA programme service

MyOTA is a programme-agnostic platform for outdoor activation programmes. MPOTA is represented as a configured programme, not as the platform itself. No rules or charter text are copied from POTA or any other programme: every programme supplies its own configuration, policy, eligibility, awards and public charter.

This repository owns programme configuration and shared entity-category master
data. It publishes programme-owned policy inputs, themes, content, locales,
jurisdictions, assignments, and optional OIDC mappings for the other services
to consume. Awards and activity execution belong to myota-activity-service;
entities and imports belong to myota-geodata-service.

## What works now

- Programme policy/content effective dates are normalized to UTC before
  publication, persistence and event emission. Legacy unqualified date-times
  mean UTC, never server local time. Offset-bearing instants are preserved;
  invalid dates are rejected. Tests run in a deliberately non-UTC timezone.
  See the [UTC policy](https://github.com/myota-platform/myota-docs/blob/main/docs/utc-time-policy.md).
- Identity, geodata, activity, and public/admin web capabilities are separate
  repositories; this service exposes their programme policy inputs.
- Programme configuration: shared entity category assignments, programme-owned rules, minimum QSOs, awards, theme and optional OIDC settings.
- Shared category master data with stable codes, geometry kinds, descriptions, active/inactive lifecycle, reusable across programmes, and explicit assignment APIs for administration.
- Entity imports and community proposals belong to geodata and are distinct
  sources of candidates, not successive programme lifecycle steps.
- The current slice provides category master data and assignments, programme
  rules/themes/content/OIDC fields, and configuration-gap tracking.

Phase 1 adds `PATCH /v1/programmes/{slug}`, idempotent `PUT`/`DELETE` category
membership resources, and `PATCH` resources for programme content and policy
draft lifecycle transitions. Legacy action routes remain available as
deprecated aliases; see the [Phase 1 API resource update record](https://github.com/myota-platform/myota-docs/blob/main/docs/api-phase1-resource-updates.md).

## Configuration gap baseline

The service currently exposes the vertical-slice primitives, but programme
configuration is not yet a complete governance and policy control plane. In
particular, the editor still needs programme lifecycle/version publication,
owner and legal metadata, locale/default/fallback management, jurisdiction and
approver-scope configuration, schema-driven activation/QSO/geodata/privacy
policy forms, OIDC administration, notification/public-output defaults, and a
policy simulator with historical snapshots.

The authoritative list, ownership boundaries, priorities, and non-goals are
maintained in
[`myota-docs/docs/programme-configuration-gap-analysis.md`](https://github.com/myota-platform/myota-docs/blob/main/docs/programme-configuration-gap-analysis.md).
The `oidc` and `locales` fields already exist in the bootstrap data model, but
their complete administration workflow is still pending. Generic policy JSON
drafts are compatibility scaffolding until the programme-owned schemas are
implemented.

The unit-test adapter may run in memory. Durable deployment uses plain
PostgreSQL `myota_core`; only geodata needs PostGIS. Core migrations are
orchestrated by `myota-deploy`, with integration mirrors in `myota-platform`.

The durable runtime exposes aggregate programme, entity-type catalogue, and
assignment gauges at `/metrics`, together with bounded HTTP request
counters and duration histograms. Request labels use only HTTP method, declared
route template, and status code; gauges contain no programme slugs, entity
identifiers, or user data. The OTel Collector scrapes `/metrics` every 15
seconds.

## Test and run locally

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 run_programmes.py
```

The standalone entry point listens on port 8002; configure database and
authentication settings explicitly. For the full durable local environment,
start Colima and use [myota-deploy](https://github.com/myota-platform/myota-deploy#run-the-vertical-slice).
Administration is at port 8090 and uses APIs, never direct database access.

## Architecture

Read the [project charter](https://github.com/myota-platform/myota-docs/blob/main/docs/project-charter.md)
and [repository map](https://github.com/myota-platform/myota-docs/blob/main/docs/repository-map.md).
The [programme configuration gap analysis](https://github.com/myota-platform/myota-docs/blob/main/docs/programme-configuration-gap-analysis.md)
is the authoritative backlog for this service and its admin UI.

## Source project

The original `ea7klk/mpota` repository remains untouched; see the
[migration strategy](https://github.com/myota-platform/myota-docs/blob/main/docs/migration-from-mpota.md).
