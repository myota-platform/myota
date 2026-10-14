# Contract generation and API compatibility

`contracts/openapi.yaml` is the canonical HTTP contract. The repository-root
`openapi.yaml` and `myota-platform/contracts/openapi.yaml` are generated
mirrors. Synchronize them with
`python3 scripts/sync_contract_mirrors.py --platform-root ../myota-platform`;
do not edit a mirror independently.

The checked-in Python and TypeScript client façades cover the current
resource-oriented endpoints. Contract CI verifies their required methods,
compares the canonical OpenAPI operations with deployed service route
registries, and rejects drift in generated files. The reviewed semantic
duplicate baseline records the remaining intentional lifecycle commands:
award decisions, callsign verification/retirement, and content/policy-draft
submission, review, and publication. These remain explicit because they
represent audited domain transitions.

The event registry and JSON Schemas in `contracts/event-registry.json` and
`contracts/schemas/` are authoritative here. Deploy's runtime routing catalog
is generated from these files. The registry contains 68 source-backed domain
facts: 19 Identity, 12 Programme, 10 Activity, and 27 Geodata facts, plus 11
selected work commands. The unsupported
Geodata deletion-failure fact was removed because the worker retries from its
durable lease and emits no terminal failure event. Fact payload schemas remain
source-derived inventories; runtime enforcement still requires the documented
projection, prohibited-field, size, compatibility, and consumer checks.

Geodata preprocessing still carries internal `_records` and `_status` in
its source-derived event shape. Introduce and review a minimal versioned
projection before enforcement. The Operations Service is retired; it owned no domain-fact producer or payload schema.

The proposed `email.send.v1` work command uses an Identity account reference
and a versioned allowlisted account-created template. It excludes email
addresses, message bodies, credentials, recovery tokens, and arbitrary HTML.
Its contract does not authorize runtime publication; the owner transaction,
recipient-resolution API, service consumer, and deployment remain separate
gates tracked by the email workstream.

Geodata entity categories use the shared master-data catalogue. `entityTypes`
is the ordered category set, and the first category is the compatibility
primary. Imports are programme-independent and create preprocessed records;
administrator promotion explicitly creates CANDIDATE or APPROVED entities.

API invariants remain service-owned authorization, database transactions,
idempotency, audit, and event behavior. Changes to the not-yet-live v1 surface
are applied directly in the canonical contract, owning handlers, checked-in
clients, and mirrors. Preserve explicit commands when they carry distinct
audited transitions; do not add mechanical aliases without a concrete client
need.

The event registry audit is
`python3 scripts/audit_workspace_event_sources.py --workspace-root ..`.
The [REST API consolidation record](https://github.com/myota-platform/myota-docs/blob/main/docs/domain/api/rest-consolidation-plan.md)
documents the completed route cleanup and preserved command boundary.
