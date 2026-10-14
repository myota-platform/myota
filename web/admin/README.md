# MyOTA Administration Web

Authenticated, programme-aware administration surface for the MyOTA Outdoor
Activation Platform. This is intentionally separate from the public
`myota-web` experience: administrator navigation, review queues, audit context,
and account controls do not leak into the participant-facing application.

MyOTA's purpose, motivation, and policy boundary are documented in the
[project charter](https://github.com/myota-platform/myota-docs/blob/main/docs/governance/project-charter.md).
The public Explorer and participant workflows are deliberately tracked as
remaining work in the [charter gap analysis](https://github.com/myota-platform/myota-docs/blob/main/docs/governance/charter-gap-analysis.md);
the admin web should not absorb those participant-only responsibilities.

## Initial slice

- Signed-token login, refresh and logout through the identity service.
- Role-aware global-admin shell with programme context and breadcrumb/audit context.
- Dashboard for service health, programmes, review queue, active work and security events.
- Programme create/update/archive and policy/theme editing.
- Geodata candidate review, community proposals as candidate sources and a
  separate Geodata imports page; there is no separate PROPOSED lifecycle state.
- Separate Geodata review and Entity management workspaces: review keeps filters,
  map, source comparison, status changes, and review decisions; management keeps
  the filtered catalogue, Leaflet popups, name/location/category editing,
  Website/Description entry and maintenance,
  geometry editing, GIS administration, audit history, and permanent deletion
  warnings. Missing location metadata can be explicitly queued for asynchronous
  reverse-geocoding from the current geometry; Entity Management polls the
  selected entity while that lookup is queued and refreshes the visible fields
  when the worker completes.
- Entity Catalogue opens a keyboard-accessible, tabbed editor without scrolling
  the page: name/categories, location, geometry, source comparison and audit/deletion.
  Previous/next navigation preserves filters, pagination and the independent bulk
  selection. Unsaved changes require confirmation before closing or switching
  entities; saving one section preserves drafts in the others. Geometry has a
  focused Leaflet/Geoman map with explicit vertex editing/replacement drawing.
  Review decisions remain on the separate review page. See the
  [catalogue guide](https://github.com/myota-platform/myota-docs/blob/main/docs/domain/administration/entity-catalogue-editor.md).
- Identity account search, multi-role user editing, least-privilege role creation/editing, privacy export and deactivation.
- Paged, filtered geodata review and protected geometry editing; permanent
  deletion of any lifecycle status requires global-administrator authorization
  and explicit QSO/award-impact confirmation.
- Geodata review page selection with current-page select-all, audited bulk approval, and global-administrator bulk deletion with QSO/activation impact confirmation.
- Leaflet-based geodata review with a persistent viewport queue, explicit geometry edit mode, Leaflet-Geoman point/way/polygon drawing, and source/audit-aware inspection.
- Read-only Entity map page with explicitly paged stored geometries with lifecycle styling, clustered Leaflet markers, and popups for name, location metadata, shared categories, and programme memberships.
- Database-backed multi-category selection for new candidates and reviewed entities; the first category remains the compatibility primary value.
- Asynchronous geodata import submission for pasted or uploaded datasets, optional paste text when a file is selected, and clickable import-run summaries with entity counts, provenance, and errors.
- Pre-processing queue validation with candidate-name Leaflet map previews,
  per-entity candidate/approved/reject decisions, automatic next-item review,
  terminal promotion-result handling with retry, confirmed cancellation for
  waiting uploads and active preprocessing, and explicit import finalization
  that discards staged records while retaining the run summary.
- Resumable owner-scoped file uploads with pause/resume, checked parts, separate
  transfer/verification stages and fresh sessions when a completed file is submitted again.
- Automatic worker-status refresh, authoritative counts, older active runs and
  cross-page candidate selection; history remains paged below the workspace.
- Revision-checked entity edits with conflict/reload guidance, not silent overwrites.

- Activation/QSO operational list with protected activity-read scope.
- Programme-owned hunter/activator award drafts, nested conditions, configurable levels, print profiles, draggable certificate fields, asset registration, and request/issuance visibility through the shared activity API on port 8004.
- Keyboard-friendly responsive layout with visible status, error and loading states.
- Authenticated observability access at `/observability/`; the Admin UI refreshes
  its access token before navigating, and its reverse proxy validates that
  token on every Grafana request. GLOBAL_OPERATOR/GLOBAL_ADMIN have Grafana
  Editor access; authorized observability readers have Viewer access.
  Prometheus, Alertmanager and Tempo remain private cluster services.
- SeaweedFS monitoring uses the OpenTelemetry-backed Grafana dashboard. The
  former `/object-storage` Admin route redirects to its provisioned SeaweedFS
  dashboard; object-storage upload workflows are unchanged.

The UI is programme-agnostic and does not encode any programme rules. It only
edits configuration supplied by each programme.

The [scaling delivery/evidence checklist](https://github.com/myota-platform/myota-docs/blob/main/docs/geodata-horizontal-scaling-roadmap.md#latest-delivery-and-evidence--7-october-2026)
links the current upload, concurrency and worker integration. The

The former Admin NATS/JetStream inspection page has been retired. Use the authenticated Grafana Metrics & dashboards workspace; its Surveyor dashboards are documented in the [NATS monitoring migration](https://github.com/myota-platform/myota-docs/blob/main/docs/observability/nats-surveyor-migration.md).

### Observability access

After signing in, choose **Platform health → Metrics & dashboards** in the sidebar.
Grafana is served from `/observability/` on the same host. The UI refreshes its MyOTA access token before navigation and mirrors the
short-lived token into a SameSite=Strict cookie scoped only to that path.
Nginx sends that bearer token to the Gateway's internal Grafana auth endpoint,
which revalidates the token and current roles through the live Identity API.
Sign-out clears both the browser token and the helper cookie. Grafana uses a
distinct stable account ID per user. Current GLOBAL_OPERATOR/GLOBAL_ADMIN
roles map to Editor and can create dashboards and panels; other observability
readers map to Viewer. Incoming identity/role headers are overwritten by Nginx.
Prometheus and Alertmanager are not exposed as separate public services.
All provisioned dashboards default to the last 30 minutes and refresh every
30 seconds. Editors can save UI changes, but later source provisioning updates
overwrite those changes; use Save as copy for independently maintained dashboards.
The Nginx proxy refreshes its gateway and Grafana service DNS lookups every ten
seconds, so it follows new Kubernetes ClusterIPs without requiring an admin-web
restart.

## Vue application

### Administration workspaces

Navigation is grouped into Start, Entities, Programmes, People, Activity and
Platform health. The searchable sidebar, route guards and page headings use
one permission-aware workspace definition from the resolved identity `/me`
response. Existing URLs stay valid; Entity categories remains `/master-data`.
Users & access separates Users, Roles & permissions and Security events into
tabs. Programme-owned pages have one local selector and a read-only header
context; shared entities/imports remain platform-wide, including unassigned.

Shared headings provide refresh, action spacing and consistent feedback.
Published versions and immutable identifiers are visibly read-only. User saves
preserve existing programme/jurisdiction/category grants, and cleared password
fields cannot accidentally reapply an earlier reset. Permission-specific
dashboard requests show unavailable counts as unknown rather than zero.
Category and award controls reflect the actual owning API permissions; UI
checks never replace server authorization. Map exploration reports loaded/total
records and offers bounded additional pages instead of silently omitting them.

See the [workspace guide](https://github.com/myota-platform/myota-docs/blob/main/docs/domain/administration/navigation-reorganization.md)
and [delivery evidence](https://github.com/myota-platform/myota-docs/blob/main/docs/domain/administration/evidence/admin-workspaces-2026-10-09.md).

All dates/times use UTC, regardless of browser timezone. Effective-date controls
are explicitly labeled UTC; shared helpers normalize offset-bearing values and
serialize new inputs with `Z`, preserving unchanged seconds. NATS/storage sample
displays also identify UTC. See the [UTC policy](https://github.com/myota-platform/myota-docs/blob/main/docs/platform/utc-time-policy.md).

Programme editing loads the full detail record and preserves programme-owned
metadata. Award design includes the six default fields, named PNG/JPEG uploads
through the activity API, background/signature selectors, and transient mock-data
PDF previews in a separate window. See the
[editor/design guide](https://github.com/myota-platform/myota-docs/blob/main/docs/domain/awards/admin-designer.md).
Browser regression coverage includes existing-record saves and artwork uploads.

The current application is the complete Vue 3 +
TypeScript + Vite administration application. All administration routes use
typed Vue components; Pinia owns the small amount of cross-page client state,
and API requests remain service-owned and isolated in `src/lib/api.ts`.

Leaflet, MarkerCluster, and Geoman are pinned under `public/vendor` so the
application can use the same map runtime in development, production builds,
and the local Compose deployment without a separate compatibility server.

Local validation on this branch:

```bash
npm install
npm run typecheck
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

Browser regressions use actual Vue/Leaflet/Geoman with isolated API fixtures,
block public tile traffic, and never mutate live entities. The publishing
workflow runs them and retains desktop/mobile screenshot evidence. A separate
read-only live check is available in `scripts/verify-catalogue-live.mjs`; it
accepts a short-lived access-token JSON object through stdin (never a password
or command-line token) and blocks non-GET API requests.

## Map tiles and editing

The review map uses vendored, pinned Leaflet and Leaflet-Geoman assets. The
default raster tile source is the configurable
`https://tile.openstreetmap.org/{z}/{x}/{y}.png`. The map displays the required
OpenStreetMap attribution and a “Report a map issue” link, requests tiles only
for the visible viewport, does not prefetch or provide offline tiles, and lets
the browser honor tile caching headers. The nginx response and HTML referrer
policy are `strict-origin-when-cross-origin`, which sends a valid origin
referrer to the tile server. Browsers supply their own User-Agent header;
client-side JavaScript cannot set or spoof it. If a deployment proxies tiles,
that proxy must provide an identifiable User-Agent and follow the provider’s
terms. See the [OpenStreetMap Tile Usage Policy](https://operations.osmfoundation.org/policies/tiles/)
before changing the tile provider or request behavior.

Programme configuration details, including the shared Entity Categories JSON
compatibility format and geometry type rules, are documented in
[`docs/programme-configuration.md`](docs/programme-configuration.md).

## Local run

For local development, install dependencies and start Vite. Its development
proxy listens on `http://localhost:8090` and sends API requests to
`http://localhost:8080` by default:

```bash
npm install
npm run dev
```

For a production-style local preview, run `npm run build` followed by
`npm run preview`. The deployment Compose manifest starts this UI on
`http://localhost:8090`.

Award background and signature binaries are selected from the asset catalogue
and uploaded through the authenticated activity API, which writes SeaweedFS/S3. Local Compose
provides SeaweedFS for those assets; certificate rendering produces a PDF when the
registered background and signature are available, otherwise the immutable
issuance render specification can be retried later.
