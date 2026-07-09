# SonarCloud usage — how the fleet runs Sonar (clean-as-you-code)

> SonarCloud is a **required merge gate** on every paved-road repo, run as an artifact-handoff
> reusable (`sonar-scan.yml`, `sonar.qualitygate.wait=true`) — the `SONAR-HANDOFF` org decision.
> This standard is the usage contract: the new-code conditions, the security rule, the
> don't-ignore policy, and the false-positive mechanics. The bar itself is set in
> [gate-hardening](../gate-hardening.md) §Sonar new-code.

## The two required contexts

- **`SonarCloud scan`** — the CI job that runs the scanner and waits for the gate.
- **`SonarCloud Code Analysis`** — the SonarCloud app's own status check.

Both gate `main`. A red on either blocks the merge. Only these two (plus the Quality gate) are
required — a non-required Sonar decoration failing is not, on its own, grounds for a bypass.

## The new-code quality gate (clean-as-you-code)

Sonar gates the **agent's diff**, not the whole product. On new code, require:

- coverage on new code **≥ 80%**
- **0** new bugs, **0** new vulnerabilities, **0** unreviewed new security hotspots
- new-code maintainability rating **A**; **0** new blocker/critical smells
- duplicated lines on new code **< 3%**

Legacy debt ratchets down monotonically; it never blocks a change that did not create it.

## Security Rating ≥ A is never merged unseen

Before any owner override past a failing `SonarCloud Code Analysis`, READ the `sonarqubecloud[bot]`
PR decoration. A **Security Rating worse than A is never merged unseen** — fix it. A coverage /
duplication / smell-only failure may, by the interim policy, be an owner's logged `--admin`
exception; a security-rating regression may not.

## Don't ignore Sonar

Sonar is **signal that serves agent self-correction**, not a box to tick and not the objective.
The policy is "don't ignore Sonar": resolve a finding in code, or — for a genuine false positive —
mark it with a rationale. Never suppress blindly, never let a rating regress unexamined. Chasing a
coverage percentage while defect-catching power stays flat is theatre; the goal is code an agent
can safely change, and Sonar is one instrument reading that.

## New-code-only findings

Some rules are **0 on `main` but fire on changed lines** during a PR's leak period — commonly
`python:S6418` (hardcoded secret heuristics), `pythonsecurity:S8707` / `S2083` (path traversal),
and `githubactions:S8541`/`S8544` (workflow injection). Expect them on a PR that touches those
surfaces; resolve in code where real (e.g. route file paths through the canonical
`assert_within_roots` helper, never inline the check), or FP-mark where genuinely spurious.

## False-positive marking mechanics

Marking on `main` and marking on a **PR instance** are two different transitions — do both when the
finding is on an open PR:

1. **`main`** — register the finding in the repo's FP driver (an org convention is a
   `sonar_mark_false_positive.py`-style script) with a rationale; it targets `branch=main`.
2. **The PR instance** — the same issue on the PR needs a **direct** transition call:
   `POST api/issues/do_transition` with `transition=falsepositive` (or `wontfix`) for the PR issue
   key. After it lands, the gate recomputes green in ~1 minute.

Every FP MUST carry a rationale. An unexplained suppression is a debt, not a fix.

## API notes (when scripting Sonar)

- **Filter to open issues.** `api/issues/search` returns CLOSED issues by default — always pass
  `&statuses=OPEN,CONFIRMED,REOPENED`, or the counts mislead.
- **"ANALYSIS SUCCESSFUL" ≠ persisted.** A scan can report success yet be silently rejected at the
  org LoC tier. When coverage or issue counts look wrong, check `api/ce/activity` for the real
  processing verdict before trusting the decoration.
- Useful authenticated endpoints: `api/ce/activity` (processing state), `api/components/show`,
  `api/measures/component_tree`, `api/settings/values`.
- The auth token lives in the **`SONAR_TOKEN`** secret (CI) / env var (local scripting) — never in
  code, never in logs.

## How to apply

1. Adopt the `sonar-scan.yml` reusable; set the project key per repo; keep hotspot rationales in-repo.
2. Set the new-code conditions above; start any ratcheted threshold at current, only raise it.
3. On a red PR: read the decoration. Security-rating regression → fix in code. Real finding → fix.
   Genuine FP → mark on `main` **and** transition the PR issue, each with a rationale.
4. Never merge over a red required Sonar context; never bypass a security-rating regression.
