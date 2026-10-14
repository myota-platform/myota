# MyOTA monorepo instructions

This file consolidates the workspace instructions and the organization guidance
from the former `.github/AGENTS.md`. All implementation source belongs here;
`myota-docs` remains the documentation source of truth and organization
`.github` remains the governance source of truth.

## Repository map and ownership

- `apps/identity/`, `apps/programmes/`, `apps/activity/`, and
  `apps/geodata/` own their service process, tests, and database access.
- `web/admin/` and `web/participant/` remain distinct browser applications.
- `contracts/` owns shared API/event contracts and generated clients.
- `deploy/` owns Helm, Compose, deployment scripts, and owner-specific
  database migration execution. Preserve Core, Activity, and Geodata database
  boundaries.
- `integration/` owns cross-service smoke and compatibility checks.
- `packages/` may contain only stable shared primitives. Do not merge domain
  persistence, authorization, or upload policy into a shared package.
- Keep gateway, APIs, and workers as separate processes. Keep NATS as bounded
  durable transport, not business state or a long-term archive.
- Former `myota-deploy/services/` and `myota-platform/` runtime mirrors are
  migration inputs, not canonical owners. Delete mirrors only after parity is
  verified and builds consume these canonical paths.

## Branch and deployment policy

All application, contract, deployment, and workflow changes use short-lived
`feature/<name>` or `fix/<name>` branches created from `testing`. Open a PR
into `testing`; do not push implementation commits directly to `testing` or
`main`. Require applicable style, test, contract, image-build, and Helm
render checks to pass. Missing, skipped, cancelled, or failed checks are not
passes. Enable or complete auto-merge only after gates pass.

A successful `testing` branch push publishes mutable `testing` tags and
immutable `testing-<commit-sha>` tags for changed artifacts and reconciles the
isolated `myota-test` Helm release through the current digest-sync flow. This
is the only testing deployment target. Never use a testing image for
production. Promote validated work to `main` through a release PR from
`testing`; production uses release digests and its protected path. Do not
migrate or rewrite former repository branch history.

Documentation-only updates stay in `myota-docs`; organization guidance and
the issue index stay in `.github`. Keep their links and this repository map
in sync.

## Safety, tests, and delivery

Preserve API behavior, data ownership, security, compatibility, and failure
handling. Treat proposals as proposals until implemented and verified. Do not
perform schema redesign or language rewrites as a side effect of repository
moves. Never commit secrets; if a new Kubernetes secret manifest is needed,
put it under `runtime-secrets/` for safe later application and keep secret
values out of Git.

Run focused checks and report exact commands/results, changed paths, remaining
gaps, and evidence. Host system tests must be non-destructive and clean up
fixtures afterwards. Mark checklists complete only when verified. Commit
related changes coherently with meaningful multiline messages when useful.

## Consolidated source instructions

The following are retained from the workspace root `AGENTS.md` and former
`.github/AGENTS.md`. Where old repository lists or branch wording conflict
with the monorepo policy above, the path/branch policy above is the updated
equivalent; the remaining guidance applies.

### Workspace root instructions

# Agent instructions

These instructions apply to work across the MyOTA workspace. Follow any more
specific repository instructions in the repository being changed, provided they
do not conflict with the user's instructions.

## Secrets management

- In case any service needs a new secret to be created, do it in a .yaml file in the directory runtime-secrets that can be safely applied to Kubernetes later

## Github issues

- When creating Github issues, create them in the appropiate repository
- If an issue has several steps, use a checkboxed list. 
- Add useful labels to the issues. 
- Create the issues in user story style.
- Add exit criteria to a task with a checkboxed list as well, and also complete them when met
- The only allowed edit to the issue main body is completing these checkmarks when a task is complete
- If a work item affects several repositories, create reciprocal links to all issues
- Log work done on an issue in sucessive comments. Only add comments, never edit a previous one. 
- Close issues when work on them is completed.
- Keep a list of opne issues in https://github.com/myota-platform/.github/blob/main/profile/README.md as it is currentl done and update when creating or closing issues. 


## Plan and scope work

- For phased work, use one self-contained, copyable prompt per phase. Align each
  prompt with that phase's checkbox tasks and exit criteria. Wrap longer prompt
  text for readability; reusable prompts may live in a dedicated prompt file
  linked from the roadmap.
- Establish the context and scope before implementation. Identify owning
  repositories and services, read the relevant roadmap and decisions, and
  distinguish authoritative sources from synchronized mirrors.
- Preserve system boundaries and invariants, including data ownership, API
  behavior, security, compatibility, and failure handling. Label proposals as
  proposals until implemented and verified.
- Keep work within the authorized phase. Defer later-phase work. If a required
  prerequisite or approved decision is missing, report the gap and do not
  silently treat a proposal as an implemented decision.

## Evidence, documentation, and delivery

- Run focused checks appropriate to the changes and report exact results,
  changed files/repositories, remaining gaps, and supporting evidence.
- Mark a checklist item complete only after its acceptance criteria are
  verified. Document evidence in the owning repository and update relevant
  project documentation, especially `myota-docs` and `.github`. Keep links from
  `.github` to current documentation accurate.
- Test against the system deployed on this host when system-level verification
  is needed. Keep such tests non-destructive and remove test data afterward.
- Commit and push completed work with explicit, meaningful commit messages. Use
  a multiline commit message when it helps explain scope and rationale. Group
  related changes into coherent commits.

## Branch and pull-request policy

The detailed artifact-repository list, workflow, and exclusions are maintained
in [`.github/CONTRIBUTING.md`](https://github.com/myota-platform/.github/blob/main/CONTRIBUTING.md).

For repositories that build deployable artifacts:

1. Keep `main` as the default branch. Start work from `testing` on a short-lived
   `feature/<name>` or `fix/<name>` branch.
2. Open a pull request into `testing`; do not make direct work commits to
   `testing` or `main`.
3. Require the repository's style/lint, test, and artifact-build checks to pass.
   Missing, skipped, cancelled, or failed checks are not passes. Add missing
   quality checks before relying on a workflow as a gate.
4. Enable or complete auto-merge only after all configured required checks and
   branch protections pass. Reviews may be requested but are not a merge gate.
   Never bypass a configured gate.
5. Keep feature and pull-request builds non-publishing. After required checks
   pass on a `testing` branch push (including a merged pull request), publish
   both a mutable `testing` tag and a unique `testing-<commit-sha>` tag. Treat
   the unique tag or digest as the deployment identity; the `testing` alias is
   only a convenience pointer. Never publish testing output as `latest` or
   another release tag, and do not deploy from `testing`.
6. Preserve existing branch history. Reconcile stale or divergent branches
   through pull requests; do not reset or force-push them.
7. Promote validated work to `main` only through a release pull request from
   `testing`. Required checks remain enforced; reviews may be requested but
   are not required to merge.

The current policy applies to Activity, Admin Web, Deploy, Geodata, Identity,
Platform, Programme, and Web. `.github` and `myota-docs` are documentation and
governance repositories; `myota-contracts` does not build a deployable
artifact; Operations is retired from runtime and image publishing. See the
contributor guide before changing this scope. Documentation-only updates in
`.github` and `myota-docs` are committed and pushed to `main`.

### Former .github repository instructions

# Agent instructions

Before starting work, read the applicable workspace `AGENTS.md` when one is
available, plus the guidance in the repository being changed. These instructions
apply to work in this repository and do not replace repository-specific rules.

## Scope and decisions

- For phased work, use one self-contained, copyable prompt per phase, aligned
  with that phase's tasks and exit criteria. Keep prompt text readable; place
  longer reusable prompts in a dedicated file linked from the roadmap.
- Establish context and scope. Identify owning repositories and services, read
  the relevant roadmap and decisions, and distinguish authoritative sources
  from synchronized mirrors.
- Preserve system boundaries and invariants, including data ownership, API
  behavior, security, compatibility, and failure handling. Label proposals as
  proposals until implemented and verified.
- Keep work within the authorized phase. If a prerequisite or approved decision
  is missing, report the gap rather than treating a proposal as implemented.

## Evidence and delivery

- Run focused checks appropriate to the work. Report exact results, changed
  files and repositories, remaining gaps, and supporting evidence.
- Mark checklist items complete only after their acceptance criteria are
  verified. Update documentation and evidence in the owning repositories;
  maintain accurate links from `.github` to current project documentation.
- Test deployed systems only when needed, non-destructively, and clean up test
  data afterward.
- Commit and push completed work with meaningful messages. Group related
  changes into coherent commits and use multiline messages when they clarify
  scope or rationale.

## Artifact-repository branch policy

For implementation or CI work in repositories that build deployable artifacts,
follow [`CONTRIBUTING.md`](CONTRIBUTING.md). It defines the applicable
repositories and exclusions, feature/fix branches based on `testing`, pull
requests, quality gates, auto-merge conditions, and isolated testing artifacts.
Do not duplicate or weaken those repository-specific rules here.
