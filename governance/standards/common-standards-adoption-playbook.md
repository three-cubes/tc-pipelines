## Adopt the common `tc_fitness` engineering standards + framework in a consuming repo

_Goal: a consuming repo fully converges on the shared engine + the common engineering/test/CI standards, self-served by the repo owner. Everything below is generic to "the shared engine" / "a sibling consuming repo" — no private-infra names (the private-infra-pattern check applies)._

### Why
The convergence made **one shared quality engine** (`tc_fitness`) + **one shared CI library** (the shared tc-pipelines repo) that all consuming repos use. The model is **shared machinery, per-repo domain**: a repo keeps its own catalogue (descriptive rule names), check implementations, and baselines; the dispatch runner, parse-once context, staged-selection, ratchet, gate, and `RuleEntry` schema all come from the package. Convergence means a consuming repo stops carrying its own copies and inherits improvements automatically.

### ✅ The baseline (example: a fully-converged consumer)
- The repo consumes **`tc_fitness`** (e.g. pinned `@v0.4.1`) as a **true pure consumer**: `run_checks.py` is `main_cli(RULES, …, dispatch="subprocess", parallel_subprocess=True)` — **zero private-symbol imports**, and the subprocess argv-exceptions (`script_path_override` / `static_extra_args` / env-gated args) live on `RuleEntry` rows, not hand-coded.
- Adopted the donated engine features: the 6 stale-baseline checks use `tc_fitness.lib.gate(fail_on_stale=True)`; `branch_naming` is a thin shim over `tc_fitness.checks.branch_naming`.
- `run_checks.py --all` → "All 113 architecture fitness functions passed".

### ⬜ What to adopt to fully converge (the playbook)

**1. Engineering-canon currency** — propagate the cross-repo lessons into the repo's CLAUDE.md / standards.
> Mirror kairix's doc-currency PR as the model. Lessons to ensure are captured:
- **Reusable-workflow callers must be exercised before merge** — change-detection can gate a `uses:` job OFF on a workflow-only PR, so a broken `workflow_call` contract reaches main and breaks CI at *startup*. Force a triggering change in the same PR. (We hit this — see gotcha #1 below and the new kairix runbooks.)
- **Inject the slow dep via an existing seam — never real `time.sleep`/network/subprocess in a test.** A high-cost test that survives a prod mutation (low bug-catching power) is a delete/soak candidate.
- **Tests write scratch/probe files under `tmp_path` only, never the live tree; narrow whole-tree detector scans to the staged set; add a sweep fixture.** (Orphaned probe files in the tree are picked up by full-tree scanners → intermittent flakes.)
- **Re-tiering gotcha:** a per-function `@pytest.mark.soak` *stacks* with a module-level `unit` marker — to move a test off the per-commit path, put it in a dedicated soak module.
- **Reusable workflows stay secret-free** (callers pass secrets); public artefacts don't name private sibling repos.
- Reference model: kairix `CLAUDE.md`, `docs/architecture/ENGINEERING.md §3.7`, `docs/architecture/fitness-functions.md` (Limits section), and the two new runbooks `docs/operations/runbooks/how-to-consume-a-shared-reusable-workflow.md` + `runbook-ci-startup-failure.md`.

**2. CI reusable-workflow adoption** — wire the repo's `ci.yml` / `sonar.yml` / `5-mutation-testing.yml` onto the shared tc-pipelines `@v1` reusables (`setup-uv-cached` composite, `python-quality-gate.yml`, `sonar-scan.yml` artifact-handoff, `mutation-gate.yml`, `docker-build-publish.yml`, `fresh-install-smoke.yml`).
- **⚠️ Blocker first:** the `sonar-scan.yml@v1` caller broke kairix `ci.yml` at **`startup_failure`** (a `workflow_call` input/secret contract mismatch, undiagnosed — reverted in kairix). **Diagnose the contract and validate the caller on a python-touching PR before merging** (gotcha #1). The `setup-uv-cached` composite is the safe first adoption; `sonar-scan` artifact-handoff requires moving coverage production into an upstream job that uploads the coverage + test-results artifacts.
- The repo's mutation gate needs its real runner landed before consuming `mutation-gate.yml`.

**3. Test-cost / test-health audit** — run the same audit on the repo's suite that kairix just did (~459s→~250s on the per-commit path):
- Profile with `uv run python -m pytest -m '<your per-commit markers>' --durations=50`.
- For the costliest tests: inject existing seams instead of real sleep/network; delete/soak high-cost-low-bug-power tests; fix any orphan-probe/full-tree-scan isolation flakes with narrowing + `tmp_path` + sweep fixtures.
- Reference: the kairix test-cost-triage report for the pattern + the per-recommendation playbook.

**4. Stay on the engine** — when the engine cuts a new version (v0.4.2+ adds factories/features), repin + adopt additively, and **diff the fitness ledger (`run_checks.py --all` + `--staged`) before/after the pin bump** to confirm verdicts are byte-identical.

### 🪤 Gotchas to encode in the consuming repo's CLAUDE.md
1. **Reusable-workflow `startup_failure`** — see CI adoption above; the cause was the caller's `with:`/`secrets:` not matching the reusable's `workflow_call` contract. Symptom: "This run likely failed because of a workflow file issue." Fix: revert the job to inline, or correct the contract; always test the caller on a triggering PR.
2. **ruff F401/noqa CI trap** — the repo's CI Quality-gate runs `ruff check scripts/ tests/ --ignore=…,F401,…`, so a `# noqa: F401` becomes a redundant-noqa **RUF100 error**. **Never add `# noqa: F401`**; for an intentional re-export use the explicit-alias form `from x import y as y` (`PLC0414` is not in the repo's select list).
3. **Pre-existing ruff-format drift (~74 files)** — `safe-commit.sh`'s tree-wide `ruff format --check` fails because the local ruff (0.15.x) is newer than the config-pinned hook ruff (v0.7.4). **Recommendation: a one-time `uv run ruff format scripts/ tests/ tools/` cleanup commit** (using the pinned ruff via pre-commit) to clear the drift so `safe-commit.sh` runs clean. Until then, use the canonical pinned pre-commit gate + `uv run ruff check scripts/ tests/ --ignore=T201,I,E501,F401,F841,E401,W291,F821` (mirrors CI's lint exactly).
4. **`branch_naming` slug regex forbids dots** — e.g. a `v0.4.1` slug is rejected; use `v0-4-1`. Shape: `<user>/<team>-<number>-<slug>`, slug = `[a-z0-9][a-z0-9_-]*`.
5. **Shared-repo PR merge** — the org `main` rulesets require a review the author can't self-provide; admin-merge only when the *required* checks are green (`codecov/patch` is non-required and may flag on a flag basis).

### 📍 Where things live
- Shared engine: package `three-cubes-fitness`, import `tc_fitness`, pinned `@v0.4.1`.
- Shared CI: the tc-pipelines repo → `@v1` reusables + composites.
- The reference implementation: kairix `CLAUDE.md` + `docs/architecture/{ENGINEERING.md, fitness-functions.md, test-discipline-hardening.md}` + `docs/operations/runbooks/`.

### Suggested order
(1) the engineering-canon currency propagation → (2) the one-time ruff-format-drift cleanup (unblocks the local commit gate) → (3) the test-cost/health audit on the repo's suite → (4) the CI reusable wiring (sonar-scan first, behind a forced caller-test, after diagnosing the startup_failure contract).
