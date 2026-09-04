# Improving a fitness gate or pipeline recommendation

Change the gate or the pipeline **at its one canonical home**, ship it as an immutable tag, and let each consumer repin on its own schedule. This is the mechanics of shipping a change; the **bar** a repo's gate must clear before it runs autonomously is [`gate-hardening.md`](../gate-hardening.md).

## Converge up — one home each

- **Gates are tc-fitness CORE checks.** The runnable gate engine ([tc-fitness](https://github.com/three-cubes/tc-fitness)) owns every check; a repo selects and configures checks through its `[tool.tc_fitness]` block, it does not carry its own copy.
- **Pipelines are tc-pipelines reusables + composite actions.** This repo owns the reusable `workflow_call` workflows and the composites; a consumer calls them, it does not re-implement them.

Improve the check or the workflow **in that home** and every repo converges up. Forking a parallel gate or inlining a pipeline in a consumer repo is the drift this model exists to end — [`STANDARDS.md §6`](../STANDARDS.md) is the anti-reinvention rule.

## Add or improve a gate (tc-fitness)

1. **Write the check in tc-fitness.** Add or extend a CORE check under `src/tc_fitness/core_checks/`, paired with a contract/unit test that proves both the pass and the fail path.
2. **Canary the candidate on a real consumer — BEFORE the tag exists.** Run a real consumer's gate against the CANDIDATE engine (the fix branch/SHA, not a tag) and block the release if it reds. This is the step the v0.13.0 empty-roots regression skipped: nothing ran a consumer's gate against the candidate, so every repin adopted a broken engine. Use the `fitness-engine-canary.yml` reusable (which drives `governance/scripts/fitness-engine-canary.sh`) — it repins the consumer's pin to the candidate ref, runs the consumer gate, and **exits with the consumer gate's exit code**, so a red consumer gate blocks the release. Wire it as a REQUIRED step in the engine-release pipeline between here and the tag; do not tag until the canary is green.
3. **Release an immutable tag `vX.Y.Z`.** Keep it **additive**: an existing check's signature and verdict stay byte-identical, and any new surface is **opt-in with safe defaults**, so a consumer that repins without configuring it sees no verdict change.
4. **Repin each consumer on its own schedule.** Bump the `three-cubes-fitness` pin in the consumer's `pyproject.toml`, bind the check via a `[tool.tc_fitness.core_checks.<name>]` block, and register it in the repo's catalogue. Before landing the bump, **diff the fitness ledger** (`tc-fitness run --all` + `--staged`) before and after and confirm it is byte-identical (sha256) — verdicts must not drift. See [`process-shared-repo-pr-review-and-merge.md`](process-shared-repo-pr-review-and-merge.md) §Update the production pins and [`common-standards-adoption-playbook.md`](common-standards-adoption-playbook.md).

The pin bump touches the gate's own definition, so it is a control-plane change: it holds for a `@three-cubes/maintainers` review before it merges.

## Improve the pipeline (tc-pipelines)

1. **Change the reusable in place** — the workflow (`python-quality-gate.yml`, `azure-vm-deploy.yml`, …) or a composite action under `.github/actions/`.
2. **SHA-pin every `uses:`** to a full commit SHA (Sonar `S7637`), including a reference to this repo's own composites. A floating major such as `@v1` only stays correct while something advances that tag on every release; nothing does, so it froze and a step loaded a revision of a composite that no longer emitted the output its workflow read — silently, because the workflow and the composite sit side by side and every local check compares against the local file. Pinned by `governance/scripts/tests/test_uses_ref_pinning.py`.
3. **Commit the action, then pin its callers to that immutable commit.** The target-content contract verifies that each caller executes the reviewed local action content. This lets one release carry both the change and its working call path. The full rule, including why the SHAs are repeated and what a consumer repin touches, is [`supply-chain-pinning.md`](supply-chain-pinning.md).
4. **Roll out through the major pin.** A breaking input/output change cuts a new major (`@v2`) and leaves `@v1` working; consumers move to the new tag on their own schedule (`VERS-D1`).

Exercise the caller before merge: a change-detection filter can gate a `uses:` job off on the very PR that changes it, so a broken `workflow_call` contract can reach `main` and fail at workflow startup. Force a triggering change in the same PR.

For a change to merge admission, release or deployment orchestration, also
follow [`ci-release-deployment-architecture.md`](ci-release-deployment-architecture.md).
In particular, do not replace post-merge validation with a lightweight
attestation until the target ruleset has enabled merge queue and the consumer's
`merge_group` run has proven the required contexts on an exact synthetic merge.

### Pre-evaluation normalisation

`python-quality-gate.yml` exposes `pre-evaluation-normalize` for deterministic,
safe source repairs that must happen before any evaluator reads the checkout.
It runs after the requested Python/Node toolchains are installed and before
changed-file capture, repo-specific `pre-steps`, and `tc-fitness run`. Typical
usage is a repo-owned script that runs safe linter fixes and formatting, such as
Ruff's `--fix` mode. The input is forwarded through every unsharded, sharded,
and non-shard lane, plus `pytest-durations-refresh.yml`, so no quality lane or
timing map can observe a different source state.

The reusable gate re-syncs the Python project after this command so
non-editable installs cannot execute a stale site-packages copy. Its
diff-scoped changed-file handoff unions the committed range with modified,
staged, and untracked checkout paths created by the normalizer. When coverage
combining or a changed-line floor is enabled, the coverage job provisions the
same optional Node surface, repeats the normalizer, and re-syncs before it
generates or scores coverage XML. These are part of the reusable contract, not
consumer conventions.

The command is deliberately opt-in and empty by default. It may modify only the
runner checkout; it must not deploy, write remotely, use credentials, or fetch
from the network. A consumer that opts in must invoke the exact same
repo-owned command in `make check` before its local `tc-fitness run`, and carry
a contract test that locks the local command to the reusable input. This keeps
the fast local loop and every CI lane aligned without making a formatter choice
an organisation-wide mandatory dependency.

## Every repo's harness must reference this canon

The `harness_canon_reference` gate (tc-fitness v0.11.0) fails any repo whose harness does not reference [`governance/STANDARDS.md`](../STANDARDS.md) — the canonical engineering-standards index. Keep that reference in place so an agent editing a gate always lands on the canonical home, not a repo-local fork.
