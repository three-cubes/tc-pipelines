---
type: standard
status: draft
date: 2026-05-29
owner: platform
applies_to:
  - all-pull-requests
  - quality-harness
  - per-package-ratchet
related:
  - the quality-ratchet ADR
  - the quality-ratchet standard
  - the testing-strategy standard
  - the agent-actionable-feedback standard
  - the actor-model + test-pyramid architecture
sources:
  - https://mutmut.readthedocs.io/
  - https://stryker-mutator.io/docs/stryker-js/introduction/
  - the coverage-theatre lesson (PR #290 closure)
  - the mutation-testing programme tracking issue
purpose: >
  Design the mutation-testing survival-rate ratchet as the structural answer
  to coverage theatre. Specifies tool selection per language, target survival
  rates, baseline shape, integration with the existing quality-ratchet
  pattern, sequencing, and cost discipline. Implementation lands in a
  follow-up PR; this doc is the contract that implementation must satisfy.
---

# Mutation testing — the survival-rate ratchet

> Mutation testing closes the gap between "tests EXECUTE the code" (line
> coverage) and "tests CATCH bugs in the code" (mutation survival). A
> surviving mutant is a real defect class the suite cannot detect. The
> ratchet shape is the same as ADR-014 / quality-ratchet.md — per-package
> baselines that may only shrink.
>
> **This document is design only.** No fitness function ships in this PR;
> no baseline file is populated; no CI wiring is added.

## 1. Why mutation testing

Branch coverage on `main` is ~34%. The PR #290 episode (2026-05-23) lifted
coverage to 82% via 1,583 monkeypatched tests that caught nothing. The
canonical lesson: **coverage % is not a goal — defect-catching power is.**
Mutation testing is the structural instrument for that goal because:

- **A mock returning the same value regardless of input is exactly what
  mutation testing surfaces.** Mutate the production-side comparison
  operator; if the mock-driven test still passes, the mutant survived and
  the test is shown to be vacuous.
- Surviving mutants name *defect classes* (boundary off-by-one, wrong
  comparison, wrong constant, wrong return-on-empty) — not abstract gaps.
- Mutation testing is the gate that would have blocked PR #290 from
  passing.

The ratchet shape (touched files, baseline shrinks only) is identical to
the SonarCloud and coverage ratchets in `quality-ratchet.md`. This doc
extends that pattern to a third data source.

## 2. Per-language tooling

### Python — `mutmut`

| Aspect | Choice |
|---|---|
| Tool | `mutmut` (v3+) |
| Runner integration | `mutmut run --paths-to-mutate <pkg>/` then `pytest` on the affected test files |
| Operators (default set we enable) | arithmetic, comparison, conditional-boundary, conditional-negation, increment, literal-mutation, string-literal-mutation, return-value, unary-operator |
| Operators we exclude | docstring-mutation, comment-mutation, type-annotation-mutation (no behavioural signal) |
| Config file | `mutmut.ini` at repo root |
| Per-package scope | Each Python package (MCP server, `scripts/`, `tools/`) has its own `[mutmut.<pkg>]` section |

`mutmut` is preferred over `cosmic-ray` because the kairix repo already
adopted it (a cross-repo tooling convention worth matching).

### TypeScript / JavaScript — `stryker`

| Aspect | Choice |
|---|---|
| Tool | `@stryker-mutator/core` + `@stryker-mutator/vitest-runner` (vitest is the canonical TS runner per ADR-015) |
| Runner integration | `pnpm exec stryker run --mutate <pattern>` against the touched files only |
| Operators (default set we enable) | ArithmeticOperator, ArrayDeclaration, ArrowFunction, AssignmentOperator, BlockStatement, BooleanLiteral, ConditionalExpression, EqualityOperator, LogicalOperator, OptionalChaining, StringLiteral, UnaryOperator, UpdateOperator |
| Operators we exclude | Regex (high false-positive rate — regex mutation rarely corresponds to a real defect class) |
| Config file | `stryker.conf.json` per pnpm package (plugins, MCP servers) |
| Per-package scope | Each TS package declares `mutate: ["src/**/*.ts"]` in its `stryker.conf.json` |

### Bash

No canonical mutation-testing tool exists for shell. The ratchet emits
`skipped: bash` in the per-package report for any package whose primary
language is bash. Detection: presence of `*.sh` and absence of
`pyproject.toml` / `package.json`. Defer until a tool emerges.

## 3. Survival rate — definition and targets

Survival rate is the inverse of mutation score, expressed per package:

```
survival_rate = survived / (killed + survived) * 100
mutation_score = 100 - survival_rate
```

`killed` includes test failures AND timeouts (a timeout is treated as
killed because the mutation made the program non-terminating —
behaviourally distinct from the original). `no_coverage` mutants (lines
not exercised at all) are NOT counted in either bucket and surface
separately as a coverage signal.

### Targets (per-package, ratcheted by quarter)

| Quarter | Target survival rate | Rationale |
|---|---|---|
| Q1 (sprint of landing) | <=60% | Pilot baseline. Most legacy packages will start above 60%. Goal: don't regress. |
| Q2 | <=50% | First ratchet. Forces ~10 percentage-points of test improvement. |
| Q3 | <=40% | Industry baseline for a healthy suite. |
| Q4+ | <=20% | Aspirational. Reaching <=20% means the suite catches 4-in-5 mutations. |

These are **ceilings on the touched-file ratchet**, not pass/fail gates
on the absolute number. The ratchet semantics: a file's survival rate
**after** the PR may not exceed its survival rate **before** the PR. The
quarterly ceiling additionally sets the floor that new files must enter
at.

## 4. Mutation operators — upstream reference

Full operator lists live upstream:

- Python (`mutmut`): https://mutmut.readthedocs.io/en/latest/#mutations
- TS/JS (`stryker`): https://stryker-mutator.io/docs/mutation-testing-elements/supported-mutators/

The repo's enabled subset (§2 above) is intentionally conservative —
operators with known high false-positive rates (regex, docstring) are
excluded so the ratchet signal stays high-fidelity.

## 5. Integration

### Files (designed, NOT created this sprint)

| File | Purpose |
|---|---|
| `mutation_survival_ratchet` | Fitness function — per-package baseline comparison, touched-file scope, same shape as `coverage_ratchet.py` |
| `.architecture/baseline/mutation-survival-rates.json` | Per-package baseline — `{<package>: {survived: N, killed: N, rate: P, timestamp: T, commit: SHA}}` |
| `.architecture/baseline/mutation-survival-rates-meta.yaml` | Provenance — captured-at date, source commit, mutation tool version, operator set |
| `mutmut.ini` | Repo-root Python mutmut config |
| `stryker.conf.json` (per TS pkg) | Per-package TS stryker config |
| `.github/workflows/5-mutation-testing.yml` | Nightly cron + `workflow_dispatch` trigger |

### Trigger model

| Trigger | Scope | Frequency |
|---|---|---|
| Nightly cron (`5-mutation-testing.yml`) | All packages above the rollout floor | 02:00 UTC daily; emits the updated baseline as a workflow artifact |
| `make mutation` | Configurable scope (default: files touched since `origin/main`) | Developer-initiated, pre-push |
| `make check` | **NOT WIRED** by default. Wired only after pilot proves stability (see §8). | Gate runs against baseline file in CI per PR |

### Per-package overrides

The baseline JSON carries per-package opt-outs:

```json
{
  "tools/scorecard": {
    "excluded": true,
    "reason": "Checked by scorecard contract suite + tier-3 BDD walker; mutation testing is redundant signal here",
    "expires": "2026-09-30"
  }
}
```

Exclusions MUST carry an `expires` date (<=90 days) so they re-surface
for review. The override grammar follows §2 of `quality-ratchet.md`.

### Ratchet semantics (per-PR)

The `mutation_survival_ratchet.py` gate:

1. Reads `.architecture/baseline/mutation-survival-rates.json`.
2. For each touched file in the PR, resolves the file's owning package.
3. If the package is excluded → skip silently.
4. If the package has no baseline entry → skip silently (package is pre-rollout).
5. Compares the post-PR per-file survival rate against the per-file
   baseline. **A file's rate may not increase.**
6. Aggregates per-package: if any touched file in a package regressed,
   the package FAILs.

Same override grammar as Sonar ratchet:

```
mutation-ratchet-acknowledged: <path> — <specific reason>
```

The reason must be specific per §2 of `quality-ratchet.md`. Vague reasons
(`wip`, `minor`, `out of scope`) fail the override-quality check.

## 6. Actor-model anchor

Per the actor-model + test-pyramid architecture (§1), every quality
surface must trace to at least one actor's stake. Mutation testing serves
three:

| Actor | Concern | What the gate gives them |
|---|---|---|
| **Platform operator** | "Does the test suite actually catch real bugs, or do green CI runs lie?" | A surviving-mutant report names specific defect classes the suite misses. PASS means: "for this baseline of operators, no regression in catch-rate". |
| **CFO / cost owner** | "Mutation testing is expensive — minutes per file per run. Is the cost bounded?" | Cost discipline (§9): nightly-only by default, per-PR opt-in via `make mutation`, hard 15-minute budget per package, scope to touched files. No full-suite runs in CI without explicit opt-in. |
| **Agent (self)** | "When I'm asked to add a test, did my test actually catch the mutation or just hit the line?" | Mutation report on the agent's PR shows which mutants the new test killed. An agent that writes mock-driven tests sees them survive mutants and self-corrects. |

The Agent (self) anchor is the key shift. Coverage % rewards mocking
because mocked tests execute the code. Mutation survival punishes mocking
because mocked tests don't observe the change a mutant introduced.

## 7. Sequencing

```
This sprint (E2)         → design doc lands (this file)
Pilot sprint (Q1 + 1)    → wire mutmut on tools/scorecard ONLY
                            - baseline captured
                            - nightly run for 2 weeks
                            - tune operator set if signal is noisy
                            - LANDING DEFINITION: rate stable +/- 2pp across 14 nightly runs
Expand sprint (Q1 + 2)   → add 1 package per sprint, in this order:
                            1. tools/scorecard (Python — pilot)
                            2. scripts/checks (Python — highest fitness-function leverage)
                            3. agentic/tools/mcp/kairix-export (Python — high-value mid-size MCP)
                            4. agentic/tools/plugins/voice-style-guard (TS — first TS pilot)
                            5. agentic/tools/mcp/relationship-crm (TS — high-value mid-size MCP)
Global enable (Q2)       → after 5 packages stable, wire into `make check`
                            with off-by-default `MUTATION_RATCHET_REQUIRED=1`
                            for CI only. Local make check still skips it
                            unless explicitly invoked.
```

Per-package addition is gated on:

- Nightly run completes within the 15-minute per-package budget.
- Survival rate is below the current quarterly ceiling OR has a documented exemption.
- At least one surviving-mutant class has been examined and either fixed (preferred) or annotated.

## 8. Risks

### Cost — mutation testing is expensive

Per-file mutation runs are minutes-scale (mutmut: ~30s-2min for a 100-line
file; stryker: similar). A full repo run would be hours.

**Mitigation:**
- Nightly cron only for full-package runs.
- Per-PR CI gate scopes to touched files (`--mutate src/touched/file.ts`).
- Hard per-package budget: 15 minutes. Over-budget = package excluded with auto-tracked issue.
- Parallelisation via `mutmut run --paths-to-mutate <pkg> --processes N` and `stryker run --concurrency N`.

### False-positive mutations — operators that don't represent real bugs

`stryker`'s regex operator and `mutmut`'s docstring mutation generate
mutants no production-side change would ever introduce. Tests that don't
catch them are not actually weaker.

**Mitigation:**
- Explicit exclude list in §2.
- Per-package config can extend the exclude list with rationale.
- The pilot sprint includes a tuning pass — if an operator generates
  >50% surviving-but-not-actionable mutants, drop it.

### Slow on JS/TS — full TS package mutation runs are slow

stryker runs each mutant in a fresh worker by default; cold-start cost
dominates.

**Mitigation:**
- `--mutate src/specific/file.ts` for per-PR runs.
- `stryker.conf.json` per package keeps the worker pool warm.
- `incrementalFile` (stryker's built-in cache) reused across PRs in the
  same package.

### Gaming the gate by writing tests that pad mutation kills

Per issue #296: **do not optimise for survival-rate % — optimise for
known-uncaught-defect classes.** If a mutation survives because the
production code is over-flexible, the right response is production-side
narrowing, not test-side assertion. The override grammar (`mutation-ratchet-acknowledged:`)
exists for this case.

### Audit policy

Same chronic-overrider signal as `quality-ratchet.md` §2:

- Same author overrides >=3 times in 30 days
- Same file overridden >=3 times in 30 days
- >=40% of an author's PRs include an override

Signals surface in the weekly retro.

## 9. Definition of Done — this sprint (E2)

- [x] This doc lands as the mutation-testing survival-ratchet standard.
- [x] The canonical-patterns index "Standards needed but not yet written" updated:
      the mutation-testing survival-ratchet row added with **LANDED (design)** status.
- [ ] Issue #296 stays open — design is one stage, implementation lands in follow-up PRs per §7.

## 10. What this doc does NOT do

- Does not implement `mutation_survival_ratchet`.
- Does not populate `.architecture/baseline/mutation-survival-rates.json`.
- Does not add `mutmut.ini` or any `stryker.conf.json`.
- Does not wire `.github/workflows/5-mutation-testing.yml`.
- Does not modify `Makefile` to add a `mutation` target.
- Does not change `make check`.
- Does not select the pilot package's first surviving-mutant fix targets — that's a Q1+1 sprint task.

Each of these is a follow-up PR. The contract above is what they must satisfy.

## 11. The `mutation_survival_ratchet` interface (designed, not implemented)

### Synopsis

```
mutation_survival_ratchet.py [--base REF] [--head REF]
                             [--touched-files PATH [PATH ...]]
                             [--package NAME]
                             [--baseline]
                             [--json]
                             [--verbose]
```

### Inputs

| Flag | Default | Meaning |
|---|---|---|
| `--base REF` | `origin/main` | Comparison base via `git merge-base $REF HEAD`. |
| `--head REF` | `HEAD` | PR head ref. |
| `--touched-files PATH ...` | (none) | Explicit override. Skips `git diff`. |
| `--package NAME` | (auto) | Restrict to one package (used by pilot rollout). |
| `--baseline` | off | Emit per-package baseline JSON to stdout. |
| `--json` | off | Structured output per `agent-actionable-feedback.md`. |
| `--verbose` | off | Per-mutant detail. |

### Outputs

**PASS:**

```text
PASS mutation_survival_ratchet (N touched files; P packages evaluated; 0 regressions; K overrides applied)
```

**FAIL:**

```text
FAIL mutation_survival_ratchet
  - tools/scorecard/check.py: survival rate regressed (38.0% -> 47.0%); fix: add a test that catches the surviving conditional-boundary mutant on line 88 OR add `mutation-ratchet-acknowledged: tools/scorecard/check.py — <reason>` to the PR body; next: make mutation SCOPE=tools/scorecard/check.py
```

**Exit codes:**

| Code | Meaning |
|---|---|
| 0 | PASS |
| 1 | FAIL — at least one touched file regressed without override |
| 2 | `unavailable` — mutmut/stryker missing, or baseline file missing |
| 64 | Usage error |

### Behaviour contracts (must)

- Respect per-package exclusions in the baseline JSON.
- Parse PR body for `mutation-ratchet-acknowledged:` lines.
- Honour rename detection (`git diff --name-status -M`).
- Emit messages conforming to `agent-actionable-feedback.md` (`fix:` + `next:`).
- Be deterministic — same inputs produce identical output.
- Surface `unavailable` (exit 2) NOT as a pass when the tooling is missing.

### Behaviour contracts (must not)

- Run a full-repo mutation pass. Touched-file scope only.
- Modify the baseline file from inside the gate (baseline updates are a separate, explicit script).
- Cache results across CI runs without commit-hash validation.

## References

- The quality-ratchet ADR — quality-ratchet architectural decision.
- The quality-ratchet standard — operational playbook the override grammar inherits.
- The testing-strategy standard — five-layer pyramid that mutation testing lives alongside (not inside).
- The agent-actionable-feedback standard — `fix:`/`next:`/`run:` message shape.
- The actor-model + test-pyramid architecture — actor model the §6 anchor uses.
- The coverage-theatre lesson (PR #290 closure) — the lesson this gate operationalises.
