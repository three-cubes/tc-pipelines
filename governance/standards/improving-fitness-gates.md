# Improving a fitness gate or pipeline recommendation

Change the gate or the pipeline **at its one canonical home**, ship it as an immutable tag, and let each consumer repin on its own schedule. This is the mechanics of shipping a change; the **bar** a repo's gate must clear before it runs autonomously is [`gate-hardening.md`](../gate-hardening.md).

## Converge up — one home each

- **Gates are tc-fitness CORE checks.** The runnable gate engine ([tc-fitness](https://github.com/three-cubes/tc-fitness)) owns every check; a repo selects and configures checks through its `[tool.tc_fitness]` block, it does not carry its own copy.
- **Pipelines are tc-pipelines reusables + composite actions.** This repo owns the reusable `workflow_call` workflows and the composites; a consumer calls them, it does not re-implement them.

Improve the check or the workflow **in that home** and every repo converges up. Forking a parallel gate or inlining a pipeline in a consumer repo is the drift this model exists to end — [`STANDARDS.md §6`](../STANDARDS.md) is the anti-reinvention rule.

## Add or improve a gate (tc-fitness)

1. **Write the check in tc-fitness.** Add or extend a CORE check under `src/tc_fitness/core_checks/`, paired with a contract/unit test that proves both the pass and the fail path.
2. **Release an immutable tag `vX.Y.Z`.** Keep it **additive**: an existing check's signature and verdict stay byte-identical, and any new surface is **opt-in with safe defaults**, so a consumer that repins without configuring it sees no verdict change.
3. **Repin each consumer on its own schedule.** Bump the `three-cubes-fitness` pin in the consumer's `pyproject.toml`, bind the check via a `[tool.tc_fitness.core_checks.<name>]` block, and register it in the repo's catalogue. Before landing the bump, **diff the fitness ledger** (`tc-fitness run --all` + `--staged`) before and after and confirm it is byte-identical (sha256) — verdicts must not drift. See [`process-shared-repo-pr-review-and-merge.md`](process-shared-repo-pr-review-and-merge.md) §Update the production pins and [`common-standards-adoption-playbook.md`](common-standards-adoption-playbook.md).

The pin bump touches the gate's own definition, so it is a control-plane change: it holds for a `@three-cubes/maintainers` review before it merges.

## Improve the pipeline (tc-pipelines)

1. **Change the reusable in place** — the workflow (`python-quality-gate.yml`, `sonar-scan.yml`, `azure-vm-deploy.yml`, …) or a composite action under `.github/actions/`.
2. **SHA-pin every third-party `uses:`** to a full commit SHA (Sonar `S7637`); the org self-pins its own composites to `@v1`.
3. **Tag the change** and roll it out through the major pin. A breaking input/output change cuts a new major (`@v2`) and leaves `@v1` working; consumers move to the new tag on their own schedule (`VERS-D1`).

Exercise the caller before merge: a change-detection filter can gate a `uses:` job off on the very PR that changes it, so a broken `workflow_call` contract can reach `main` and fail at workflow startup. Force a triggering change in the same PR.

## Every repo's harness must reference this canon

The `harness_canon_reference` gate (tc-fitness v0.11.0) fails any repo whose harness does not reference [`governance/STANDARDS.md`](../STANDARDS.md) — the canonical engineering-standards index. Keep that reference in place so an agent editing a gate always lands on the canonical home, not a repo-local fork.
