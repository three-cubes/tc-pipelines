---
type: standard
status: proposed
date: 2026-05-17
owner: platform
applies_to:
  - all-pull-requests
  - all-direct-pushes-to-main
  - quality-harness
sources:
  - the quality-ratchet ADR
  - the ToolPack + capability ADR
  - the agent-actionable-feedback standard
purpose: >
  Operational playbook for the touched-file quality ratchet. Defines the gate
  inventory and the evidence each gate reads, the developer workflow when a
  ratchet gate fires, the exact override shape and its audit policy, the
  CI/local parity model, and the coverage ratchet's modes and baseline
  lifecycle.
---

# Quality Ratchet Operational Standard

> Touch a file and you own its quality floor: after your change, that file's
> measured quality must be at least what it was before. This standard tells you
> what to do when a ratchet gate fires.
>
> The architectural decision lives in the repo's quality-ratchet ADR.
> This document is the **operational** surface — workflows, exact text shapes,
> and the evidence model. Every ratchet runs in-repo: evidence-based ratchets
> read committed measurement files, and strict gates admit no exception ledger
> and evaluate the current source or live merge-base evidence. No gate needs a
> hosted scan, so local and CI agree by construction.

## Where this fits

| Layer | Surface | Where |
|-------|---------|-------|
| Architectural decision | the quality-ratchet ADR | the repo's decisions tree |
| Operational playbook | this standard | governance standards |
| Gate implementations | the CORE checks below + the consumer's coverage ratchet check | tc-fitness + each repo |
| Committed baselines | `.architecture/baseline/` | each repo |
| Override declaration | commit message or PR body | per-change |
| Audit trail | the scorecard result JSON (`quality_ratchet_overrides`) | weekly retro |

## 1. Authoring a fix — the workflow when a gate fires

### Find the gate that fired

| Axis | Gate | Evidence it compares against |
|---|---|---|
| Per-file line coverage | the coverage ratchet check | `.architecture/baseline/coverage-baseline.xml` |
| Changed-line coverage | `new_code_coverage` (CORE) | none — absolute floor (100% by default, `DEFAULT_FLOOR_PCT` in the check) |
| Cognitive complexity | `cognitive_complexity` (CORE) | live merge-base function scores — no stored baseline |
| Duplicate strings | `no_duplicate_string` (CORE) | none — every finding blocks |
| Commented-out code | `no_commented_out_code` (CORE) | none — every finding blocks |
| Surviving mutants | `mutation_survival_ratchet` (CORE) | recorded survivor report — see `mutation-testing-survival-ratchet.md` |
| IaC misconfiguration | `checkov_iac_security` (CORE) | none — every finding blocks |

Every FAIL line names the file, the before/after measurement, and ends in
`fix:` and `next:` per the agent-actionable-feedback standard:

```text
FAIL coverage_ratchet
  - scripts/checks/foo.py: coverage dropped 85.0% -> 70.0% (delta -15.0%); fix: add tests covering the removed lines OR add `coverage-ratchet-acknowledged: scripts/checks/foo.py — <specific reason>` to the commit message; next: pytest --cov=scripts --cov-report=term-missing scripts/checks/foo.py
```

Run a single gate directly, by its catalogue id, to see its per-file verdict:

```bash
uv run --frozen tc-fitness run --gate <catalogue-id>
```

…you have four valid responses. Choose the one that fits your situation.

### Response A — Fix the regression

Default. For coverage, cover the lines `--cov-report=term-missing` names. For
complexity, extract helpers until the function clears the threshold. For a
duplicate string or commented-out code, refactor or delete. Refactor for real —
inline `# noqa`/`NOSONAR` is **forbidden** by ADR-010 D7.

This is the **expected** path for legacy debt. The ratchet's purpose is to
convert the legacy backlog into a touch-driven work queue.

### Response B — Restore main's baseline

If a refactor removed test seams, or you pulled in a change that regressed a
measurement you did not intend to touch, restore `main`'s version of the
affected lines and apply your intended change separately.

This is the "I accidentally regressed" path. Often the cleanest fix is
`git checkout origin/main -- <path>` followed by re-applying your intended diff.

### Response C — Declare an override

Use this **only** when the touch is legitimately decoupled from the regression.
See §2 below for the exact shape and audit policy.

### Response D — Revert the touch

If you don't strictly need to touch `<path>` for your PR's goal, drop the
change. Untouched files don't trip the ratchet.

This is the right choice for "I edited it just to bump a comment" — the
ratchet's signal is that comment-only touches on a file with debt are not free.

## 2. Using the override

The override is one line per file, in the commit message or PR body. The
keyword names the ratchet it acknowledges:

```
coverage-ratchet-acknowledged: <relative/path/to/file> — <specific reason>
mutation-ratchet-acknowledged: <relative/path/to/file> — <specific reason>
```

The separator is an em-dash or a hyphen. The reason is **vague** — and the
override does not clear the failure — when it is shorter than 40 characters
(`OVERRIDE_MIN_REASON_LEN` in tc-fitness `ratchet.py`) or starts with
`wip|minor|todo|skip|later|n/a|out of scope|will fix later`.

Examples that **pass** the override-reason quality check:

- `coverage-ratchet-acknowledged: scripts/legacy/foo.py — pure rename, no logic change; rewrite scheduled in #221 for sprint W14`
- `coverage-ratchet-acknowledged: infra/scripts/bootstrap.sh — vendored upstream pin bump, no edits in-flight; upstream cleanup tracked at https://upstream/issues/42`

Examples that **fail** the quality check (and the human-UX judge surface will flag):

- `coverage-ratchet-acknowledged: foo.py — WIP`
- `coverage-ratchet-acknowledged: foo.py — minor`
- `coverage-ratchet-acknowledged: foo.py — later`
- `coverage-ratchet-acknowledged: foo.py — out of scope`
- `coverage-ratchet-acknowledged: foo.py — N/A`

### Rules

- One declaration line per overridden file. Multiple files = multiple lines.
- The reason must be specific (concrete, falsifiable, links a tracking issue when applicable).
- The override is logged to the scorecard audit log under `quality_ratchet_overrides[]` with `{pr, file, reason, author, date}`.
- The override applies only to its own change; each PR's overrides cover only its own diff.
- The override allows the merge; the regressed measurement stays recorded until a later change raises it.

### Audit policy

The override generates a **chronic-overrider signal** when any of the following is true in a trailing 30-day window:

- Same author overrides ≥3 times.
- Same file is overridden ≥3 times.
- ≥40% of an author's PRs include an override.

Signals surface in the weekly retro — they are **not** a gate. The platform owner reviews patterns and decides whether to:

- Tighten the reason-quality rubric.
- Split a chronically-overridden file (the file is the smell, not the override).
- Schedule a focused-cleanup PR to flush the backlog on that file.

## 3. CI / local parity

The gate produces the same result in CI and on a developer's laptop. `make
check` and CI both run the same `tc-fitness run` catalogue, and every ratchet
reads only in-repo evidence:

- **Committed baselines** (coverage, mutation survival) live under
  `.architecture/baseline/`, so the comparison is deterministic across CI
  runners and developer laptops without a network round-trip.
- **Merge-base evidence** (cognitive complexity, changed-line coverage) is
  computed from `git merge-base` against the configured trunk ref; a
  remote-tracking trunk ref is refreshed before the merge base is resolved.
- **Absolute gates** (duplicate strings, commented-out code, IaC
  misconfiguration) evaluate the current source and block on every finding.

Run the full gate before every push; CI is the gate of record and re-runs on
the merge commit.

### Local debugging recipe

```bash
# 1. See the per-file diff the ratchet will evaluate
git diff --name-only "$(git merge-base origin/main HEAD)"

# 2. Run the full catalogue
make check

# 3. Inspect the uncovered lines on a touched file
pytest --cov=scripts --cov-report=term-missing scripts/checks/foo.py
```

## 4. Coverage ratchet

The coverage ratchet applies the touched-file shape to per-file line coverage.
Implementation: the consumer's coverage ratchet check. Config:
`pyproject.toml [tool.coverage.ratchet]`.

### What it does

When a PR's `git diff` touches a `.py` file, that file's line coverage after
the PR must be `>=` its line coverage before the PR. The before-coverage is
read from a committed baseline at
`.architecture/baseline/coverage-baseline.xml`; the after-coverage from the
working tree's freshly-generated `coverage.xml`.

The `new_code_coverage` CORE check is the **absolute target** on the changed
lines. The coverage ratchet is the **touch bar** — it stops PRs from making
existing files worse while the changed-line floor holds new code to its bar.
Both can fire; both must pass.

### Data flow

```
pytest --cov=scripts --cov=tools --cov-report=xml
      |
      v
coverage.xml  ----compare----  .architecture/baseline/coverage-baseline.xml
      |                                  ^
      v                                  |
coverage ratchet check             committed by hand from a
      |                            green-state pytest run
      v
PASS / FAIL / SKIP / establish-baseline
```

### Operator workflow when the gate fires

Apply the four responses in §1 and the override grammar in §2 with the
`coverage-ratchet-acknowledged:` keyword.

### Modes

| Mode | Trigger | Behaviour |
|------|---------|-----------|
| **Enforce** (active) | `coverage.xml` exists AND baseline file exists | Compare per-file; FAIL on regression. |
| **Establish baseline** | `coverage.xml` exists, baseline absent | PASS, print per-file coverage; commit `coverage.xml` to `.architecture/baseline/coverage-baseline.xml` in a follow-up PR to start enforcing. |
| **Skip** | `coverage.xml` absent, `COVERAGE_RATCHET_REQUIRED` unset | PASS with a `SKIP` line. |
| **Unavailable** | `coverage.xml` absent, `COVERAGE_RATCHET_REQUIRED=1` | Exit 2 — CI uses this to fail loudly if pytest never ran. |

### Enforce-mode activation

The baseline lives at `.architecture/baseline/coverage-baseline.xml` with provenance recorded in
`.architecture/baseline/coverage-baseline-meta.yaml`. The presence of the baseline file is the
implicit enforce-mode trigger — no config flag is required; the ratchet switches from
"establish-baseline mode" to "enforce mode" automatically when the file exists. Once enforcing, a
PR that drops per-file line coverage FAILs the gate. Files at 0% coverage are locked at 0% — the
ratchet only blocks regressions below the baseline floor; new tests that raise the floor are
welcome and refresh-the-baseline-eligible (see "Refreshing the baseline" below).

### Refreshing the baseline (when raising the floor)

The baseline only goes **up**. When you've intentionally added tests that
raise per-file coverage and want to lock in the new floor:

```bash
pytest --cov=scripts --cov=tools --cov=tests/lib --cov-report=xml tests/
cp coverage.xml .architecture/baseline/coverage-baseline.xml
# Update .architecture/baseline/coverage-baseline-meta.yaml:
#   - git_commit (git rev-parse HEAD)
#   - captured_at (date -u +%Y-%m-%dT%H:%M:%SZ)
#   - line_rate, branch_rate, classes_count (from the XML root attrs)
git add .architecture/baseline/coverage-baseline.xml \
        .architecture/baseline/coverage-baseline-meta.yaml
git commit -m "coverage(baseline): raise per-file floor after adding tests for <area>"
```

Refreshing the baseline downward (lowering the floor) requires an ADR
superseding the quality-ratchet ADR — this is intentional friction. The audit
policy in §2 applies to baseline refreshes too.

### Establishing the baseline

The one-time establish step:

```bash
pytest --cov=scripts --cov=tools --cov=tests/lib --cov-report=xml
mkdir -p .architecture/baseline
cp coverage.xml .architecture/baseline/coverage-baseline.xml
git add .architecture/baseline/coverage-baseline.xml
git commit -m "coverage(baseline): establish per-file coverage baseline"
```

The baseline is intentionally **committed** so the gate is deterministic
across CI runners and developer laptops without a network roundtrip.

## Stay inside the ratchet contract

- Address the rule by refactor; suppression markers (`# noqa`, `NOSONAR`) violate ADR-010 D7, and the ratchet implementations themselves stay suppression-free. `suppressions_have_rationale` and `no_production_suppressions` carry suppression discipline in the catalogue.
- Reserve `# pragma: no cover` for genuinely unreachable branches (e.g. `if TYPE_CHECKING:`); cover real lines with tests per ADR-010 D7.
- Write tests that assert observable behaviour; the judge surface samples for trivial `assert True` inflation and flags it.
- Reserve overrides for the rare exemption the audit allows (§2); routine use defeats the ratchet.
- Treat every committed baseline as monotonically increasing — raise it via passing tests; lower it only via an ADR.
- Let pre-commit and CI re-run on the merged ref; both rerun on the merge commit so the gate stays in force.

## References

- The quality-ratchet ADR — architectural decision and rationale.
- The ToolPack + capability ADR §D7 — no-suppressions principle.
- The agent-constitution-conformance ADR — two-tier + fitness-function gate pattern.
- The agent-actionable-feedback standard — `fix:`/`next:`/`run:` requirements.
- `mutation-testing-survival-ratchet.md` — the mutation-survival axis of the same ratchet pattern.
- The prior-art baseline-ratchet artefact — the pattern this gate generalises.
