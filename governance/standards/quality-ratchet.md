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
  - sonar-project.properties
  - the Sonar status helper
purpose: >
  Operational playbook for the touch-based SonarCloud quality ratchet. Defines
  the developer workflow when the gate fires, the exact PR-body override
  shape and its audit policy, the FP-marking workflow in the Sonar UI, the
  process for refreshing the exemption table, the CI/local parity model, and
  the designed-but-not-yet-implemented interface of
  sonar_quality_ratchet.
---

# Quality Ratchet Operational Standard

> When a PR's `git diff` touches a file, that file's outstanding SonarCloud
> finding count after the PR must be less than or equal to its count before.
> This standard tells you what to do when the gate fires.
>
> The architectural decision lives in the repo's quality-ratchet ADR.
> This document is the **operational** surface — workflows, exact text shapes,
> and the designed CLI interface.

## Where this fits

| Layer | Surface | Where |
|-------|---------|-------|
| Architectural decision | the quality-ratchet ADR | the repo's decisions tree |
| Operational playbook | this standard | governance standards |
| Gate implementation | the `sonar_quality_ratchet` fitness check | tc-fitness |
| Exemption table | `pyproject.toml [tool.sonar.ratchet]` | each repo |
| Override declaration | PR body | per-PR |
| Audit trail | the scorecard result JSON (`quality_ratchet_overrides`) | weekly retro |

## 1. Authoring a fix — the workflow when the gate fires

When `make check` or CI reports:

```text
sonar_quality_ratchet: <path>: <type> count regressed (<before> -> <after>); fix: address the <type> finding(s) introduced or restore main's baseline; next: sonar_quality_ratchet --base origin/main
```

…you have four valid responses. Choose the one that fits your situation.

### Response A — Fix the regression

Default. Identify the new finding(s) on `<path>` and resolve them.

1. Run `scripts/sonar/status.sh --branch <your-branch> --top 20` to enumerate current open findings on the branch.
2. Pull the file-scoped issue list:
   ```bash
   curl -sS -u "$SONAR_TOKEN:" \
     "https://sonarcloud.io/api/issues/search?organization=three-cubes&componentKeys=three-cubes_<repo>:<path>&resolved=false&branch=<your-branch>" \
     | jq '.issues[] | {rule, severity, line, message}'
   ```
3. Fix each finding in your working tree. Refactor for real — inline `# noqa`/`NOSONAR` is **forbidden** by ADR-010 D7.
4. Push the fix. Wait for SonarCloud's branch scan to complete. Re-run the gate.

This is the **expected** path for the BLOCKERs already on `main`. The ratchet's purpose is to convert the legacy backlog into a touch-driven work queue.

### Response B — Restore main's baseline

If you didn't intend to add findings (e.g. you pulled in a transitive change that adds a smell), restore `main`'s version of the affected lines and apply your intended change separately.

This is the "I accidentally regressed" path. Often the cleanest fix is `git checkout origin/main -- <path>` followed by re-applying your intended diff.

### Response C — Declare an override (D4)

Use this **only** when the touch is legitimately decoupled from the findings. See §2 below for the exact shape and audit policy.

### Response D — Revert the touch

If you don't strictly need to touch `<path>` for your PR's goal, drop the change. Untouched files don't trip the ratchet.

This is the right choice for "I edited it just to bump a comment" — the ratchet's signal is that comment-only touches on a file with debt are not free.

## 2. Using the override

The override is a single PR-body line:

```
quality-ratchet-acknowledged: <relative/path/to/file> — <specific reason>
```

Examples that **pass** the override-reason quality check:

- `quality-ratchet-acknowledged: agentic/skills/legacy/foo.py — pure rename, no logic change; rewrite scheduled in #221 for sprint W14`
- `quality-ratchet-acknowledged: infra/scripts/bootstrap.sh — vendored upstream pin bump, no edits in-flight; upstream cleanup tracked at https://upstream/issues/42`
- `quality-ratchet-acknowledged: agentic/tools/mcp/foo/server.py — BLOCKER on line 88 is tracked in #218 with a fix landing this week; PR's edit is unrelated config wiring`

Examples that **fail** the quality check (and the human-UX judge surface will flag):

- `quality-ratchet-acknowledged: foo.py — WIP`
- `quality-ratchet-acknowledged: foo.py — minor`
- `quality-ratchet-acknowledged: foo.py — later`
- `quality-ratchet-acknowledged: foo.py — out of scope`
- `quality-ratchet-acknowledged: foo.py — N/A`

### Rules

- One declaration line per overridden file. Multiple files = multiple lines.
- The reason must be specific (concrete, falsifiable, links a tracking issue when applicable).
- The override is logged to the scorecard audit log under `quality_ratchet_overrides[]` with `{pr, file, reason, author, date}`.
- The override does NOT silence the underlying finding — SonarCloud still reports it. The override only allows the merge.

### Audit policy

The override generates a **chronic-overrider signal** when any of the following is true in a trailing 30-day window:

- Same author overrides ≥3 times.
- Same file is overridden ≥3 times.
- ≥40% of an author's PRs include an override.

Signals surface in the weekly retro — they are **not** a gate. The platform owner reviews patterns and decides whether to:

- Tighten the reason-quality rubric.
- Split a chronically-overridden file (the file is the smell, not the override).
- Schedule a focused-cleanup PR to flush the backlog on that file.

## 3. Marking false positives in the Sonar UI

If a finding is a genuine false positive:

1. Open the finding in SonarCloud (link from `scripts/sonar/status.sh --top N` or the dashboard).
2. **Add a comment first** stating WHY this is a false positive. Concrete reasoning, not "not applicable".
3. Change status to **False Positive** or **Won't Fix**.

### Required comment shape

```
False positive because <concrete reason>.

Evidence: <file:line range OR linked PR OR linked ADR>.
Rationale: <one or two sentences explaining the analyser's incorrect inference>.
```

Examples:

- `False positive because this function is invoked by Azure Functions runtime via decorator binding (line 12). Evidence: tests/integration/test_function_routing.py. Rationale: analyser sees no in-tree call site but the runtime resolves it via the @app.function_name decorator.`
- `False positive because the cryptographic primitive is intentionally chosen for compatibility with the upstream protocol (RFC NNNN §5.2). Evidence: ADR-006 §D3. Rationale: analyser flags weak cipher but the protocol mandates it; key material is ephemeral and scope-limited.`

### What's audited

The human-UX judge surface (issue #167) periodically samples FP comments and scores them on specificity. Comments that fail the rubric are flagged for re-review — the FP status may be reverted.

### Recovery: FP marked without a comment

Restore the audit trail by leaving a compliant FP comment OR by reverting to "Open" and fixing the finding properly. A bare FP marking is treated as an audit smell; the judge surface flags it. Resolver workflow:

1. Re-open the finding (status → "Open").
2. Apply the canonical resolution — either fix the finding properly OR re-mark FP with a comment that names the rule, evidence, and rationale.

## 4. Refreshing the per-file ignores / exemption table

Exemptions live in `pyproject.toml`:

```toml
[tool.sonar.ratchet]
exempt_patterns = [
  "tests/**",
  "**/tests/**",
  "agent-bootstrap/vault-knowledge/**",
]
exempt_types = []            # optional; default = none (all types ratcheted)
pinned_baselines = {}        # optional; per-file forced baselines, see below
```

### When to add an `exempt_pattern`

- A directory is genuinely not subject to per-file finding discipline (test code, extracted knowledge content).
- A new subsystem is added that is excluded from `sonar-project.properties` `sonar.sources` anyway — add the matching pattern for belt-and-braces.

### When NOT to add an `exempt_pattern`

- "This file has too many findings to fix in one PR." Use an override instead — that's what overrides are for.
- "This subsystem is owned by a team that hasn't adopted Sonar." Wrong shape — fix the ownership, not the rules.
- "Coverage is too low on this directory." Coverage is not in the ratchet (ADR-014 D7). Adjust coverage gates separately.

### How to add an exempt pattern

1. Open a PR editing `pyproject.toml [tool.sonar.ratchet] exempt_patterns`.
2. Commit message MUST explain why the pattern is exempt (which class of code, what discipline applies instead).
3. PR review checks the justification.

### Using `pinned_baselines` (escape hatch)

Rarely, the canonical SonarCloud count is unreliable (e.g. a file just moved and `main`'s count hasn't refreshed; the analyser is temporarily down). `pinned_baselines` lets you fix a per-file baseline for the gate:

```toml
[tool.sonar.ratchet.pinned_baselines."agentic/skills/legacy/foo.py"]
bugs = 0
vulnerabilities = 0
code_smells = 3
expires = "2026-06-30"
reason = "SonarCloud rescan pending on file rename; baseline from main pre-move"
```

Pins **must** carry an `expires` date (≤90 days). The gate refuses to use an expired pin and falls back to the canonical SonarCloud count with a warning.

## 5. CI / local parity

The gate must produce the same result in CI and on a developer's laptop. Two modes:

### Mode A — CI (authoritative)

```bash
SONAR_TOKEN=$SONAR_TOKEN \
  sonar_quality_ratchet \
    --base "origin/$GITHUB_BASE_REF" \
    --head "$GITHUB_HEAD_REF"
```

Order of operations in CI:

1. Sonar scan job completes on the PR branch (existing).
2. Ratchet job depends on (1) and runs the script.
3. FAIL exits 1 → the PR is blocked.

### Mode B — Local (pre-push parity)

```bash
# Pre-push: scan local working tree, compare to main's cached counts
make sonar-ratchet            # invokes sonar_quality_ratchet --local-scan
```

Mode B runs `sonar-scanner` locally against the working tree, captures per-file deltas, and compares against `main`'s API-fetched counts. It is **not** authoritative — Mode A in CI is the gate of record — but it lets a developer catch a regression before pushing.

### Local debugging recipe

```bash
# 1. See what's outstanding on the branch you're working from
scripts/sonar/status.sh --branch <my-branch> --top 20

# 2. See the per-file diff the ratchet will evaluate
git diff --name-only origin/main..HEAD

# 3. Run the ratchet
sonar_quality_ratchet --base origin/main --head HEAD

# 4. Inspect the per-file before/after JSON
sonar_quality_ratchet --base origin/main --head HEAD --baseline > /tmp/baseline.json
jq '.files["path/to/file"]' /tmp/baseline.json
```

## 6. The `sonar_quality_ratchet` interface (designed, not implemented)

The implementation lands in a follow-up PR. This section is the **contract** that implementation must satisfy.

### Synopsis

```
sonar_quality_ratchet.py [--base REF] [--head REF]
                         [--touched-files PATH [PATH ...]]
                         [--local-scan]
                         [--baseline]
                         [--json]
                         [--verbose]
```

### Inputs

| Flag | Default | Meaning |
|------|---------|---------|
| `--base REF` | `origin/main` | The ref to compare against. The gate uses `git merge-base $REF HEAD` as the comparison base. |
| `--head REF` | `HEAD` | The PR HEAD ref to evaluate. |
| `--touched-files PATH ...` | (none) | Explicit override of the touched-files list. When set, the gate skips `git diff` and uses this list. Useful for local debugging and for pre-commit hook integration. |
| `--local-scan` | off | Mode B — run `sonar-scanner` against the working tree instead of querying SonarCloud for the head ref's post-PR counts. |
| `--baseline` | off | Emit the JSON baseline used for the comparison (counts per file per type, before and after) to stdout. Useful for pre-commit caching and retro analysis. |
| `--json` | off | Structured output per `agent-actionable-feedback.md` §`--json`. |
| `--verbose` | off | Print rule-by-rule reasoning per file. |

### Token resolution

Same precedence as the Sonar status helper:

1. `$SONAR_TOKEN` (env).
2. `az keyvault secret show --vault-name <key-vault> --name sonarcloud-pat`.

If both are absent → `unavailable` exit with `fix: export SONAR_TOKEN OR install az + run az login; next: re-run the gate`.

### Output

**Default (PASS):**

```text
PASS sonar_quality_ratchet (N touched files; M tracked file/type pairs; 0 regressions; K overrides applied)
```

**Default (FAIL):**

One line per regressed `(file, type)` pair, each terminating in `fix:` and `next:` per the agent-actionable-feedback standard:

```text
FAIL sonar_quality_ratchet
  - agentic/skills/foo/run.py: code_smells count regressed (4 -> 6); fix: address the 2 new code-smell findings introduced by this PR OR add `quality-ratchet-acknowledged: agentic/skills/foo/run.py — <reason>` to the PR body; next: sonar_quality_ratchet --base origin/main --head HEAD
  - agentic/tools/mcp/bar/server.py: bugs count regressed (1 -> 2); fix: resolve the new BUG finding; next: sonar_quality_ratchet --base origin/main --head HEAD
```

**`--json`:**

```json
{
  "ok": false,
  "code": "failed_gate",
  "what": "2 file/type pairs regressed against origin/main baseline",
  "fix": "Resolve the new findings OR add a quality-ratchet-acknowledged line per file in the PR body.",
  "next": "sonar_quality_ratchet --base origin/main --head HEAD",
  "evidence": [
    {"file": "agentic/skills/foo/run.py", "type": "code_smells", "before": 4, "after": 6},
    {"file": "agentic/tools/mcp/bar/server.py", "type": "bugs", "before": 1, "after": 2}
  ],
  "overrides_applied": [],
  "retryable": true
}
```

**`--baseline`:**

```json
{
  "base_ref": "origin/main",
  "head_ref": "HEAD",
  "computed_at": "2026-05-17T14:32:08Z",
  "touched_files": ["agentic/skills/foo/run.py", "..."],
  "files": {
    "agentic/skills/foo/run.py": {
      "before": {"bugs": 0, "vulnerabilities": 0, "code_smells": 4},
      "after":  {"bugs": 0, "vulnerabilities": 0, "code_smells": 6},
      "regressed": ["code_smells"],
      "exempt": false,
      "override": null
    }
  }
}
```

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | PASS — no regressions, or all regressions accounted for by overrides. |
| `1` | FAIL — at least one (file, type) pair regressed without an override. `make check` chains correctly on this. |
| `2` | `unavailable` — Sonar API unreachable, missing token, or missing scan on the head ref. The gate did not run. |
| `64` | Usage error (bad flags). |

### Behaviour contracts

The implementation MUST:

- Respect `pyproject.toml [tool.sonar.ratchet] exempt_patterns` (D5) — exempt files are skipped silently.
- Parse the PR body for `quality-ratchet-acknowledged:` lines (D4) and apply matching overrides. PR body source: `$GITHUB_EVENT_PATH` `.pull_request.body` in CI; in local mode, accept a `--override <file>:<reason>` flag.
- Honour rename detection (D9) — `git diff --name-status -M` is the truth; pass renamed files through with the old path as the baseline source.
- Treat security_hotspots as out-of-scope (D12) — do not query, do not include.
- Never write the token to a file or log; never persist it beyond the HTTP call lifetime (D8).
- Emit messages conforming to `agent-actionable-feedback.md` — every FAIL line has `fix:` AND `next:` (or `run:`).
- Surface `unavailable` (exit 2) NOT as a pass when the head scan is missing — D3 explicit.
- Be deterministic: same inputs → same output. Idempotent re-runs return identical JSON.
- Log override applications to the scorecard audit log (`quality_ratchet_overrides[]`) (D4) when invoked via `make check`.

The implementation MUST NOT:

- Use `# noqa` / `NOSONAR` / equivalent inline suppressions in its own code (ADR-010 D7).
- Add `sonar.issue.ignore.*` to `sonar-project.properties` to satisfy itself.
- Pass overrides between PRs (each PR's overrides apply only to its own diff).
- Cache SonarCloud responses across CI runs without freshness checks (stale cache → wrong gate result → outage).

## Stay inside the ratchet contract

Cross-references to the controls already in ADR-014 §Anti-pattern guardrails — repeated here for the operator's convenience:

- Address the rule by refactor; suppression markers (`# noqa`, `NOSONAR`) violate ADR-010 D7 and the ratchet itself MUST be suppression-free.
- Accompany every Sonar FP marking with a comment naming rule + evidence + rationale (§3); audit re-opens bare FP markings.
- Reserve `# ratchet: override` for the rare exemption the audit allows (§2); routine use defeats the ratchet.
- Refactor instead of editing `sonar-project.properties` to add `sonar.issue.ignore.*` or `sonar.coverage.exclusions`.
- Treat CI Mode A as the gate of record (§5); use `--local-scan` only as a fast pre-push sanity check.
- Let pre-commit and CI re-run on the merged ref; both rerun on the merge commit so the gate stays in force.

## 7. Coverage ratchet (W20)

The coverage ratchet is the SonarCloud quality ratchet's twin on the coverage
axis. Same touch-based shape, same override grammar, different data source.
Implementation: the `coverage_ratchet` fitness check. Config:
`pyproject.toml [tool.coverage.ratchet]`.

### What it does

When a PR's `git diff` touches a `.py` file, that file's line coverage after
the PR must be `>=` its line coverage before the PR. The before-coverage is
read from a committed baseline at
`.architecture/baseline/coverage-baseline.xml`; the after-coverage from the
working tree's freshly-generated `coverage.xml`.

The Sonar global new-code coverage gate (`new_coverage >= 90%`) remains the
**absolute target**. The coverage ratchet is the **touch bar** — it stops
PRs from making existing files worse while the global new-code gate pushes
new code over 90%. Both can fire; both must pass.

### Data flow

```
pytest --cov=scripts --cov=tools --cov-report=xml
      |
      v
coverage.xml  ----compare----  .architecture/baseline/coverage-baseline.xml
      |                                  ^
      v                                  |
coverage_ratchet.py                committed by hand from a
      |                            green-state pytest run
      v
PASS / FAIL / SKIP / establish-baseline
```

### Operator workflow when the gate fires

```text
FAIL coverage_ratchet
  - scripts/checks/foo.py: coverage dropped 85.0% -> 70.0% (delta -15.0%); fix: add tests covering the removed lines OR add `coverage-ratchet-acknowledged: scripts/checks/foo.py — <specific reason>` to the commit message; next: pytest --cov=scripts --cov-report=term-missing scripts/checks/foo.py
```

Four valid responses (mirroring §1):

- **A — Add tests.** Default. Cover the lines flagged by `--cov-report=term-missing`.
- **B — Restore main's coverage.** If a refactor removed test seams,
  re-instate them.
- **C — Declare an override.** PR body or commit message:
  ```
  coverage-ratchet-acknowledged: <path> — <specific reason>
  ```
  Same vague-reason rules as the Sonar ratchet (§2): the reason must be ≥21
  chars and not match `wip|minor|todo|skip|later|n/a|out of scope`.
- **D — Revert the touch.** Untouched files don't trip the ratchet.

### Stay inside the ratchet contract

- Reserve `# pragma: no cover` for genuinely unreachable branches (e.g. `if TYPE_CHECKING:`); cover real lines with tests per ADR-010 D7.
- Write tests that assert observable behaviour; the judge surface samples for trivial `assert True` inflation and flags it.
- Treat `.architecture/baseline/coverage-baseline.xml` as monotonically increasing — raise it via passing tests; lower it only via an ADR.

### Modes

| Mode | Trigger | Behaviour |
|------|---------|-----------|
| **Enforce** (active) | `coverage.xml` exists AND baseline file exists | Compare per-file; FAIL on regression. |
| **Establish baseline** | `coverage.xml` exists, baseline absent | PASS, print per-file coverage; commit `coverage.xml` to `.architecture/baseline/coverage-baseline.xml` in a follow-up PR to start enforcing. |
| **Skip** | `coverage.xml` absent, `COVERAGE_RATCHET_REQUIRED` unset | PASS with `SKIP` line; matches `sonar_quality_ratchet`'s soft-pass. |
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
superseding ADR-014 — this is intentional friction. The audit policy in §2
applies to baseline refreshes too.

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

## References

- The quality-ratchet ADR — architectural decision and rationale.
- The ToolPack + capability ADR §D7 — no-suppressions principle.
- The agent-constitution-conformance ADR — two-tier + fitness-function gate pattern.
- The agent-actionable-feedback standard — `fix:`/`next:`/`run:` requirements.
- The repo's Sonar status helper — token resolution + API endpoint patterns (the gate inherits these).
- The prior-art baseline-ratchet artefact — the pattern this gate generalises.
