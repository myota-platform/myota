# MyOTA participant web

MyOTA is a programme-agnostic platform for outdoor activation programmes. MPOTA is represented as a configured programme, not as the platform itself. No rules or charter text are copied from POTA or any other programme: every programme supplies its own configuration, policy, eligibility, awards and public charter.

This repository owns the public, participant-facing browser experience. It is
separate from myota-admin-web: administration, moderation, imports, programme
editing, and role management stay in the web control plane.

## What works now

- Programme switching and programme-provided theme/content.
- Approved/candidate map distinction using entities returned by the geodata API.
- Entity and programme browsing foundations.
- Participant sign-in, published award progress, and hunter/activator level requests.
- Interactive map with visible OpenStreetMap attribution, drag panning and zoom
  controls; no built-in geodata seed entities are replayed at startup.
- Published programme awards with hunter/activator levels, server-side progress checks, participant sign-in, and award-level requests.
- OpenAPI and event contracts, ADRs, migration notes, health endpoints and local deployment manifests.

The current public experience is not yet the complete launch product. The next
participant milestones are the Explorer landing page, nearby search, entity
details, proposals, activation/QSO workflows, public activation history,
privacy-aware leaderboards, and production account/profile flows. They are
tracked in the [charter gap analysis](https://github.com/myota-platform/myota-docs/blob/main/docs/charter-gap-analysis.md)
and the [organization roadmap](https://github.com/myota-platform/.github/tree/main/profile).

## Run locally

This repository contains the static participant client in `web/`, not a
Python service or dev-server entry point. Start Colima and run the Compose
stack from [myota-deploy](https://github.com/myota-platform/myota-deploy#run-the-vertical-slice).
Open <http://127.0.0.1:8080> for the participant UI/gateway; administration is
the separate Vue application on port 8090. Both clients access service APIs
and never connect directly to databases or NATS.

The web client renders policy supplied by each programme. It does not copy
POTA/MPOTA rules or decide eligibility in the browser. MPOTA is sample data
only. Android and iOS roadmap work has the same participant-only scope; admin
workflows remain web-only.

## Container image artifact

The workflow assembles the static client into an unprivileged NGINX image and
publishes `ghcr.io/myota-platform/myota-web:testing` after checks pass on the
`testing` branch. It also publishes the immutable `testing-<commit-sha>` tag;
main builds publish `latest`, while feature and pull-request builds do not
publish. The image only serves the files in `web/`; it is not deployed by this
repository. Any future runtime deployment must provide the API routing and
same-origin configuration owned by `myota-deploy`.

## Architecture

Read the [project charter](https://github.com/myota-platform/myota-docs/blob/main/docs/project-charter.md)
and [repository map](https://github.com/myota-platform/myota-docs/blob/main/docs/repository-map.md)
for product motivation and ownership boundaries.

## Source project

The original `ea7klk/mpota` repository remains untouched; see the
[migration strategy](https://github.com/myota-platform/myota-docs/blob/main/docs/migration-from-mpota.md).
