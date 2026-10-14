# MyOTA monorepo instructions

These instructions combine the MyOTA workspace guidance and the useful
organization guidance from the former `.github/AGENTS.md`. Follow them with
the applicable roadmap, architecture decisions, and repository-specific
instructions. If instructions conflict, follow the user's current direction
and preserve required safety and quality gates.

## Ownership and architecture

- `apps/identity/`, `apps/programmes/`, `apps/activity/`, and
  `apps/geodata/` own their service processes, tests, and database access.
- `web/admin/` and `web/participant/` remain distinct browser applications.
- `contracts/` owns shared API/event contracts and generated clients.
- `deploy/` owns Helm, Compose, deployment scripts, and migration execution.
  Preserve Core, Activity, and Geodata database boundaries.
- `integration/` owns cross-service compatibility and smoke checks.
- Keep gateway, APIs, and workers as separate processes. Keep NATS as bounded
  durable transport, not business state or a long-term archive.
- Put only stable shared primitives in `packages/`. Keep domain persistence,
  authorization, and upload policy with their owning services.
- Treat former repository copies as migration inputs or synchronized mirrors
  until parity is verified and builds use the monorepo paths. Do not delete
  mirrors based on assumptions.
- `myota-docs` remains the documentation source of truth. The organization
  `.github` repository remains the governance source of truth.

## Scope and decisions

- Before phased work, read the relevant roadmap and decisions, identify the
  owning components, and distinguish authoritative sources from mirrors.
- Use one self-contained, copyable implementation prompt per phase. Align it
  with that phase's tasks and exit criteria; wrap text for readability.
- Stay within the authorized phase. Record missing prerequisites or decisions
  rather than treating proposals as implemented.
- Preserve data ownership, API behavior, security, compatibility, and failure
  handling. Do not introduce schema redesigns or language rewrites as side
  effects of repository changes.

## Branches, quality gates, and deployment

- Make application, contract, deployment, and workflow changes on short-lived
  `feature/<name>` or `fix/<name>` branches created from `testing`.
- Open a pull request into `testing`; do not push implementation commits
  directly to `testing` or `main`.
- Require applicable style, lint, test, contract, image-build, and Helm-render
  checks to pass. Missing, skipped, cancelled, or failed checks are not passes.
  Enable or complete auto-merge only after configured gates pass; never bypass
  a gate.
- Feature and pull-request builds must not publish artifacts. A successful
  `testing` branch push publishes mutable `testing` and immutable
  `testing-<commit-sha>` tags for changed artifacts. Deploy the unique digest
  to the isolated `myota-test` release through the configured digest-sync
  flow. Never deploy a Testing image to production.
- Promote validated work to `main` through a release pull request from
  `testing`, with required checks enforced. Production uses release digests.
- Preserve branch history. Reconcile divergent branches through pull requests;
  do not reset or force-push them. Do not migrate former repository branches.
- Put documentation-only changes in `myota-docs` and governance changes in
  `.github`. Keep relevant links and the repository map current. The former
  `.github/profile/README.md` open-issues index is retired; do not maintain
  or link to it as an issue tracker.

## Issues and phased work

- Create issues in the repository that owns the work. Use user stories,
  meaningful labels, checkboxed task lists, and checkboxed exit criteria.
- Keep implementation detail and acceptance criteria in the owning task issue.
  Link related issues across components; use parent issues and task checklists
  to coordinate cross-component work.
- Do not rewrite issue bodies to report progress. Add successive comments for
  implementation updates, mark checkboxes only when verified, and close an
  issue only after its exit criteria are met.
- Update the relevant documentation and evidence, especially in `myota-docs`,
  and keep links from `.github` accurate.

## Secrets, checks, and delivery

- Never commit secret values. When a Kubernetes Secret manifest is needed,
  place a safe-to-apply YAML manifest under `runtime-secrets/` and keep
  credentials out of Git.
- Run focused checks appropriate to the change. Report exact commands and
  results, changed paths, remaining gaps, and evidence.
- Host-system checks must be non-destructive and clean up fixtures afterward.
  Mark checklists complete only after verification.
- Commit related changes coherently with meaningful messages, using a
  multiline message when it clarifies scope or rationale.
