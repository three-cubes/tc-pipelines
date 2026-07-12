# Canonical org-level ruleset

One organization ruleset governs `main` across every three-cubes repo. tc-pipelines
(reusable workflows + composite actions) and tc-fitness (the gate engine + CORE
checks) are the **paved path**: every rule below is enforced by a named component
of one of them, or by a native GitHub ruleset rule — nothing is aspirational.

It replaces the per-repo divergence: taz's two rulesets (`org-baseline-main` +
`main`), kairix `main`, kata `kata-main-quality-gate`, and the earlier divergent
snapshots here.

## Two profiles of the one standard

Applied as **organization** rulesets whose `conditions.repository_name` selects the
repo set. Snapshots (importable): [`rulesets/main-product.json`](rulesets/main-product.json)
and [`rulesets/main-core.json`](rulesets/main-core.json).

| | **Product** (tc-agent-zone, kairix, kata) | **Paved-path core** (tc-pipelines, tc-fitness) |
|---|---|---|
| Approving reviews | **0** — work merges lights-out on green | **1** — a framework regression is fleet-wide |
| Code-owner review | required (humans-only `@maintainers`) | required |
| Thread resolution | required | required |
| Merge method | squash | squash |
| Required checks | `Quality gate`, `require-work-item`, `no-attribution` | + `Independent verifier`, `Mutation` |
| Bypass | none (`bypass_actors: []`); owner `--admin` is the sole logged break-glass |

**Why 0 reviews on product** (Dan, 2026-07-12): WORK PRs merge on a trustworthy
green gate with no human. `require_code_owner_review: true` keeps the **control
plane** (the gate's own definition + deploy/apply surfaces) held for a human — see
[`CODEOWNERS`](CODEOWNERS), two-tier with **no `*` default** so only control-weakening
paths hold. `@three-cubes/maintainers` is humans-only so an agent can never approve
the gate that gates it.

## The rules and what enforces them

| Requirement | Enforced by | Component |
|---|---|---|
| Linear branch name `<user>/<team>-<number>-<slug>` | tc-fitness | `core:branch_naming` (`DEFAULT_LINEAR_PATTERN`), inside `Quality gate` |
| No work without an **open** Linear item — **every PR** (bots exempt) | tc-pipelines | `require-work-item.yml` → required context `require-work-item` |
| No AI/LLM self-attribution | tc-fitness / tc-pipelines | `core:no_llm_attribution` → `no-attribution` leg |
| Canonical bot/human commit author | tc-fitness | `core:canonical_commit_identity` |
| 80% coverage floor on changed lines | tc-fitness | `core:new_code_coverage`, run as the `new-code-coverage` job inside `Quality gate` |
| One runnable gate, local == CI | tc-pipelines | `python-quality-gate.yml` (the shared reusable) |
| Shard-count-independent required context | tc-pipelines | the reusable fan-in check-run, required **by name** |
| Consumer can't drift off the paved path | tc-fitness | `core:engine_version_floor`, `core:ci_consumes_shared_gate`, fan-in-name parity |
| Deterministic gate (no flaky reruns) | tc-fitness | `core:deterministic_tests` |
| Lights-out auto-merge of work PRs | tc-pipelines | `auto-merge-on-green.yml` (App token via WIF) |
| Secret scanning | tc-fitness / GitHub | `detect-secrets` (zero-tolerance vs empty baseline) + GitHub push protection |
| Required review + code-owner + thread | GitHub | the `pull_request` ruleset rule (above) |

**Required by NAME, not a required-workflow:** a native required-workflow takes fixed
inputs org-wide, but callers legitimately diverge (taz is rich — bicep/js-ts/go/openclaw
lanes; kata is lean). We require the fan-in **context name** `Quality gate`; tc-fitness
`core:ci_consumes_shared_gate` + fan-in-name parity guarantee the emitting job is the
shared reusable and carries that exact name.

**Sonar** is intentionally **not** required (Dan, 2026-07-12) — it runs weekly off the
PR loop as an informational full-codebase diagnostic; the deterministic OSS tier + the
new-code-coverage floor carry the merge gate.

## Phased rollout — you cannot flip the ruleset first

Requiring a context a repo doesn't yet emit deadlocks its PRs. Order:

1. **Converge the emitters.** Rename each repo's fan-in to `Quality gate` (kairix `CI gate`,
   kata `Quality gate / Python quality gate result` → `Quality gate`). Wire the
   `require-work-item.yml` + `no-attribution` callers in every repo. Change
   `require-work-item.yml` from *agent-only* to **every PR, bots (dependabot/renovate) exempt**.
2. **Bind + align the paved path.** Bind `core:branch_naming` where it's unbound (kairix, kata);
   bump every repo to the org-canonical pins (engine `v0.14.1`, reusable `v1.15.0`); taz sets
   `enforce-new-code-coverage: true`. Ensure each repo's Azure WIF federated credential exists
   (auto-merge prerequisite).
3. **Flip.** Import `org-main-product` + `org-main-core` as organization rulesets; delete the
   per-repo rulesets. Verify a green work PR auto-merges and a control-plane PR holds.

## Open items for the owner (org-admin)

- Org rulesets aren't API-readable by the App, so the *current* live state was inferred from
  these snapshots + docs — reconcile against the live org rulesets when importing.
- Confirm the repo-name targeting (new repos default to the **product** profile).
- `require-work-item` on **every** PR (Dan's call) still needs a dependabot/renovate exemption
  in the reusable, since a bot PR can't cite a Linear item.
