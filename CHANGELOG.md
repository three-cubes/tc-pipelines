# Changelog

All notable changes to `three-cubes/tc-pipelines` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
for the consumer-facing `@vN` workflow/action references.

## [Unreleased]

## [1.18.1] — 2026-08-12

### Fixed

- **`pytest-durations-refresh.yml` builds the same node tree as the gate.** Its
  `pnpm-install-args` defaulted to `--frozen-lockfile` while
  `python-quality-gate.yml` defaults to `--frozen-lockfile --ignore-scripts`. A
  consumer that states the value in neither call — the common case, since both
  inputs are optional — therefore ran package lifecycle scripts during a refresh
  that its gate skips, building a different node tree and timing a suite the
  shards never execute. That is the divergence the durations map exists to
  remove, so the mismatch defeated the workflow's own purpose. The defaults now
  match.

## [1.18.0] — 2026-08-12

### Added

- **`pytest-durations-refresh.yml` — regenerate a shard-balance map on a runner.**
  `pytest-shards > 1` splits on `.test_durations`, and nothing produced that file:
  consumers hand-maintained it, in practice from a workstation. Those timings do
  not scale uniformly to a runner — compute-bound tests stay proportional while
  subprocess-heavy ones (git, docker, node shell-outs) cost far more — so the map
  under-weights exactly the tests that come to dominate a shard, and the split
  balances against fiction. Measured on a consumer at 8 shards: a map claiming
  977s against 2346s of real work, splitting 1.61x off ideal, so the slowest shard
  set the critical path while the fastest idled.

  The reusable runs the suite through the consumer's own gate step and injects
  `--store-durations` via `PYTEST_ADDOPTS`, so the command, markers and coverage
  flags stay whatever `[tool.tc_fitness]` declares. `pre-steps`/`post-steps` are
  forwarded, so a consumer that generates fixtures or starts a service for its
  gate times the same suite here rather than a differently prepared one.

  It fails closed rather than shipping a map it did not produce: the checked-in
  map is cleared before the suite runs (a consumer commits that file, so a
  refresh writing nothing would otherwise re-upload the stale copy as fresh), a
  `--shard` selection is refused (pytest-split cannot store and split in one run
  — the map would describe one shard's slice and rebalance the suite onto it),
  and the result must be a non-empty object with a non-zero total. Output is an
  artifact, never a push, so a balance-critical input is never rewritten
  unreviewed.

## [1.17.0] — 2026-08-11

### Added

- **Protected GHCR apply transport for `azure-vm-deploy.yml` (EXE-61).** An
  optional, closed `ghcr-actions-token` reusable-workflow secret switches only
  the apply leg to a uniquely named Azure Managed Run Command. The repository
  token reaches the VM as one FD-backed protected parameter, is removed from
  the step's exported environment, and the uniquely named command resource is
  deleted before smoke and by a manifest-backed `always()` cleanup step. Managed
  output retains the existing fatal-marker gate,
  snapshot, retry, smoke, and opt-in output behavior. Callers that omit the
  secret keep the existing `az vm run-command invoke` path. Opted-in callers
  remain responsible for granting `packages: write`; the reusable workflow can
  only maintain or downgrade the caller's token permission.
- **Pre-snapshot remote admission for `azure-vm-deploy.yml` (EXE-61).** Consumers
  can opt into a `preflight-script` that runs on every target before the first
  snapshot or apply and must emit one content-addressed
  `PREFLIGHT_RECEIPT_DIGEST`. A failed preflight blocks all mutation while
  retaining its receipt for reporting. The paired optional
  `failure-cleanup-script` thaws resources when snapshot/apply fails after a
  successful preflight. The reusable now surfaces preflight status, receipt
  digest, and exact snapshot resource IDs. Existing callers remain unchanged
  because both scripts default to empty.

### Fixed

- **Newline-safe Azure preflight and failure-cleanup transport (EXE-63).**
  `azure-vm-deploy.yml` now composes caller-supplied multiline scripts and the
  remote success proof as separate newline-delimited fragments. A caller block
  ending in a newline or shell comment can no longer create a leading `;`,
  consume the proof command, or fail a successful preflight before apply.
- **Fail-closed Azure VM apply completion and usable GHCR token opt-in
  (EXE-61).** Reusable callers now map the configuration-time
  `secrets.GITHUB_TOKEN` into `ghcr-actions-token`; the previous documented
  `${{ github.token }}` mapping evaluated empty outside an execution step.
  Managed and legacy Run Command paths now share a parent-shell exit sentinel,
  so an `exec`-based apply or an Azure extension false green cannot suppress a
  non-zero remote exit and allow smoke or deployment success to continue.
- **`auto-merge-on-green.yml` resolves the PR from `head-sha` itself.** A
  `workflow_run` caller has no `github.event.pull_request`, so it previously ran
  a local `resolve` job to map commit→PR via `commits/{sha}/pulls` — but that job
  used the default `GITHUB_TOKEN` scoped to `contents: read`, so the PR lookup
  `403`'d ("Resource not accessible by integration"), `resolve` failed, the merge
  job was skipped, and every PR silently fell back to **manual merge**. The
  reusable now performs the lookup itself when `pr-number` is empty, using the
  three-cubes-agent App token it already mints (which carries `pull-requests`
  access). Callers drop their local `resolve` job and pass only
  `head-sha: ${{ github.event.workflow_run.head_sha }}`. **Backward compatible:**
  a caller that still passes `pr-number` skips the lookup unchanged.

### Added

- **`python-quality-gate.yml` change-gated pytest shards (SGO-280).** A new
  optional `code-change-filter` input (extended-regex over changed paths) gates
  the pytest shard fan-out: on a **docs/config-only** PR (no changed path matches)
  the N-way `quality-shard` matrix + `coverage-combine` are **skipped** and a
  single `quality` catalogue lane carries the fan-in `gate` instead; on a code
  change the shards run as normal. The decision is the pure, unit-tested
  [`actions/detect-code-changes`](actions/detect-code-changes/) composite
  (`decide-code-changed.sh`), consumed by a new `detect-changes` job. **Backward
  compatible:** an empty filter (the default) makes `code-changed` always `true`,
  so every downstream `if:` reduces to its prior form — byte-identical for
  consumers that set no filter. Fails **open** (shards run) on any indeterminate
  diff, so a detection glitch never skips tests. The static example caller
  exercises the new input shape. Pair with the diff-scoped smoke wiring below so
  the fallback lane also skips pytest itself on docs-only.
- **`make fix` shift-left in the bootstrap skeleton (SGO-280).** The rendered
  `Makefile` now carries a `fix:` target that runs the deterministic auto-fixers
  (`uv run ruff check --fix` + `uv run ruff format` + `uv lock`), so the local
  loop **corrects** lint/format/lockfile drift rather than only reporting it at
  `make check` time; `ruff` is added to the skeleton's dev group so the affordance
  is live. `make check` stays the verifier (unchanged).
- **`python-quality-gate.yml` diff-scoped smoke wiring.** Callers can opt in to
  `write-changed-files: true`, which writes a newline-delimited repo-relative
  PR/push diff file, then pair it with `tc-fitness-args: run
  --changed-files-from .tc-fitness-changed-files` to run the tc-fitness
  `<60s` changed-file smoke tier instead of a full unscoped gate on every PR.
  The static example caller now exercises the new input shape.
- **`.DS_Store` is ignored** so macOS Finder metadata stays out of repo diffs.
- **`require-work-item` reusable workflow (PLA-313 / SP-C-5).** The fail-closed
  merge-boundary enforcement of the invariant **NO WORK WITHOUT A WORK ITEM**:
  [`.github/workflows/require-work-item.yml`](.github/workflows/require-work-item.yml)
  (`workflow_call`) FAILS a PR unless its head branch (org convention
  `<user>/<team>-<number>-<slug>`) or body resolves to a **real, open/in-progress**
  Linear issue, verified via the Linear GraphQL API using the KV-fetched key
  (secret-free via WIF, like `verify-and-close`). Bypasses: a **human maintainer**
  author, or an explicit `no-work-item` label with a rationale **and** a
  CODEOWNERS-gated (code-owner-approved) sign-off for genuine hotfixes.
  Fail-closed: an unresolved id or an unreadable work-item source blocks the PR.
  Publishes the stable required-status-check context **`require-work-item`** for a
  ruleset to gate on. Injection-safe (every input + `github.event.*` env-bound;
  GraphQL via `jq --arg`). Docs:
  [`governance/loop/require-work-item.md`](governance/loop/require-work-item.md);
  static call-graph shapes added to `example-callers.yml`.
- **Canonical per-agent GitHub App governance (SGO-163).** Promoted from
  tc-agent-zone into `governance/`: the per-agent App set
  [`governance/agent-app-manifests/`](governance/agent-app-manifests/)
  (`tc-agent-builder`/`shape`/`consultant`/`growth`, tiered permissions with the
  `Administration=read` / `Secrets=none` HITL boundary intact) and the
  [`governance/agent-sdlc-access-and-hitl.md`](governance/agent-sdlc-access-and-hitl.md)
  standard (capability vs enforcement). Indexed from `STANDARDS.md` §4 +
  `governance/README.md`.

### Changed

- **`example-callers.yml` de-serialised one-file-per-reusable (parallel-dev
  friction fix).** The monolithic self-check every reusable's PR appended to (and
  collided on) is split: each reusable now owns an `example-<reusable>.yml`
  `workflow_call` file that statically validates its own call shape, and
  `example-callers.yml` is a thin `workflow_dispatch` dispatcher that fans
  `run-for-real` out to them. Adding a reusable adds a NEW file instead of editing
  a shared one, so additions no longer serialize. Every existing example job and
  the run-for-real gating are preserved; actionlint + yamllint stay green.
- **`agent-token` CLI + `github-app-token` action are per-agent-parametrised
  (SGO-163).** The CLI gains `--agent builder|shape|consultant|growth` (resolving
  the `github-app-<agent>-{id,key}` vault secrets and discovering the installation
  from the App JWT), a `--repo` installation scope, and `--git-config` (sets
  `git user.name/email` to the App's `[bot]` identity on mint). The composite
  action gains an allowlisted `agent:` input mapping to the same secret contract.
  Both default to the canonical `three-cubes-agent` App when unset — backward
  compatible with existing consumers. (`tc-agent-tools` → 0.2.0.)

### Added

- **`github-app-token` composite action** (`.github/actions/github-app-token`) —
  mints a short-lived GitHub App installation token for the `three-cubes-agent`
  App by reading its App ID + private key from `kv-tc-agents` over WIF, so agents
  authenticate as their own App identity with no GitHub-stored secret. Outputs
  `token` / `app-slug` / `installation-id`. Prereq: the consumer's WIF identity
  has Key Vault Secrets User on the vault (`ci-deploy-identity.bicep keyVaultName=…`).

### Changed

- **`python-quality-gate.yml` now calls the fitness engine.** The reusable
  Python gate shrinks to `checkout → setup-uv-cached → uv run tc-fitness run`.
  The gate's STEPS (ruff/bandit/mypy/pytest/coverage/detect-secrets targets and
  the run-* toggles) are no longer workflow inputs — each consuming repo
  declares them in a repo-local `[tool.tc_fitness]` config that the engine
  reads. The same binary + config is what `make check` runs locally, so
  local == CI by construction. Removed inputs: `ruff-lint-paths`,
  `ruff-lint-args`, `ruff-format-paths`, `bandit-paths`, `bandit-args`,
  `mypy-paths`, `mypy-args`, `compileall-paths`, `shellcheck-find-paths`,
  `pytest-args`, `coverage-paths`, `coverage-fail-under`,
  `normalize-coverage-script`, `detect-secrets-baseline`, and all Python-step
  `run-*` toggles. Added inputs: `tc-fitness-args`, `pre-steps`, `post-steps`,
  `upload-coverage-artifact`, `coverage-xml-path`, `coverage-artifact-name`.
  The Node/TS half (`run-node` + pnpm/node inputs) is retained — a separate
  ecosystem the Python engine does not orchestrate.
- **`python-quality-gate.yml` now uploads the engine-produced coverage XML**
  as the `coverage-data` artifact, completing the artifact-handoff to
  `sonar-scan.yml` from within the converged single job.
- Self-pinned both composites and the reusable gate to
  `three-cubes/tc-pipelines/actions/setup-uv-cached@v1` (was `@main`),
  honouring the repo's own "pin @vN" principle.

### Added

- **`meta-quality-gate.yml`** — the reusable self-CI gate for framework /
  non-Python repos (the second org GHA shape, complementing
  `python-quality-gate.yml`). Toggleable legs: actionlint, yamllint (relaxed
  org config), a top-level LICENSE/SPDX assertion, and branch naming. All
  caller inputs are env-bound before any shell body (injection-safe).
- **`actions/license-present`** — single-sourced composite asserting a
  top-level LICENSE file declares the expected SPDX id (whole-repo provenance,
  distinct from the engine's per-file header check). Drives the meta gate's
  license leg.
- **ci-workflows dogfoods its own meta gate** — the self-check `ci.yml` now
  thin-calls `./.github/workflows/meta-quality-gate.yml` (local-path ref)
  instead of three inline actionlint/yamllint/license jobs, so the repo runs the
  gate it ships.
- **`example-callers.yml` now exercises `python-quality-gate.yml`** via a
  kairix-shaped and a taz-shaped static caller — closing the only reusable
  `workflow_call` contract not previously validated by the call-graph self-check.
- `LICENSE` — Apache-2.0 (was an undeclared `Proprietary` marker on a public
  repo). Matched across `fitness-engine` and `platform-templates`.
- `CHANGELOG.md` (this file).
- Self-CI: `yamllint` over the workflows/actions and a LICENSE-presence
  assertion, alongside the existing `actionlint` pass.

## [1.3.0] — 2026-06-22

### Changed

- **Renamed `ci-workflows` → `tc-pipelines`** and **merged in `platform-templates`**
  (history-preserving) — one repo under the Three Cubes Golden Path for both the
  CI/quality reusables and the Azure-VM deploy reusables. Consumers pin
  `tc-pipelines@v1` (the `v1` floating major moved to the merged HEAD).

### Added

- Azure-VM deploy surfaces from the former `platform-templates`:
  `azure-vm-deploy.yml`, the `wif-azure-login` / `snapshot-azure-vm-disk` /
  `apply-on-vm-via-runcommand` / `smoke-systemctl` composites, and
  `infra/bicep/ci-deploy-identity.bicep`. Internal `uses:` refs are
  self-contained within `tc-pipelines` (no cross-repo reach into the archived
  `platform-templates`).

## [1.0.0] — 2026-06-14

First tagged baseline of the org-shared CI surface (kairix#499 Phase 4).

### Added

- Reusable workflows: `python-quality-gate.yml`, `sonar-scan.yml`,
  `release.yml`, `mutation-gate.yml`, `docker-build-publish.yml`,
  `fresh-install-smoke.yml`, and the `example-callers.yml` static
  call-graph self-check.
- Composite actions: `setup-uv-cached` (pinned uv + cached venv install seam)
  and `pre-commit-cached` (synced venv + pre-commit run).
- `ci.yml` self-check running `actionlint`.

[Unreleased]: https://github.com/three-cubes/tc-pipelines/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/three-cubes/tc-pipelines/releases/tag/v1.0.0
