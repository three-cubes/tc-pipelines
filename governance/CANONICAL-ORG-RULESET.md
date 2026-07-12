# Canonical org-level rulesets

Four organization rulesets govern branch protection across every three-cubes repo.
tc-pipelines (reusable workflows + composite actions) and tc-fitness (the gate engine
+ CORE checks) are the **paved path**: every rule below is enforced by a named component
of one of them, or by a native GitHub ruleset rule — nothing is aspirational.

They replace the per-repo divergence: taz's two rulesets (`org-baseline-main` +
`main`), kairix `main`, kata `kata-main-quality-gate`, and the earlier divergent
snapshots here. No repo carries its own `main`-branch ruleset any more — the org
rulesets cover everything centrally.

## Four profiles of the one standard

Applied as **organization** rulesets whose `conditions.repository_name` selects the
repo set. Three target `main`; the fourth targets every non-`main` branch. Snapshots
(importable): [`rulesets/main-product.json`](rulesets/main-product.json),
[`rulesets/main-core.json`](rulesets/main-core.json),
[`rulesets/main-baseline.json`](rulesets/main-baseline.json), and
[`rulesets/branch-naming.json`](rulesets/branch-naming.json).

| | **Product** (tc-agent-zone, kairix, kata) | **Paved-path core** (tc-pipelines, tc-fitness) | **Baseline** (.github, design-system-avanade, tc-demo-viewer, token-usage-and-visualization) |
|---|---|---|---|
| Ruleset | `org-main-product` | `org-main-core` | `org-main-baseline` |
| Approving reviews | **0** — work merges lights-out on green | **1** — a framework regression is fleet-wide | **0** |
| Code-owner review | required (humans-only `@maintainers`) | required | required |
| Thread resolution | required | required | — |
| Strict (up-to-date branch) | no | no | — |
| Dismiss stale reviews on push | off — an approval persists | off | off |
| Merge method | squash / merge / rebase (each repo decides) | squash / merge / rebase | — |
| Required checks | `Quality gate`, `no-attribution` | `Quality gate`, `no-attribution` | none |
| Block deletion + non-fast-forward | yes | yes | yes |
| Bypass | none (`bypass_actors: []`); owner `--admin` is the sole logged break-glass | | |

A fourth ruleset — [`rulesets/branch-naming.json`](rulesets/branch-naming.json) →
**`org-branch-naming`** — applies to **all repos, every non-`main` branch**. Its native
`branch_name_pattern` requires a branch to be a Linear `gitBranchName`
(`<user>/<team>-<number>-<slug>`, e.g. `dan/sgo-305-slug`), a Conventional Branch
operational prefix (`feat|fix|docs|chore|ci|build|refactor|test|perf|style|hotfix|release|revert|experiment|deps|feature|bugfix`),
or a bot namespace (`dependabot|renovate`). This **natively enforces work-item
traceability** — the branch embeds the Linear id.

**Why 0 reviews on product** (Dan, 2026-07-12): WORK PRs merge on a trustworthy
green gate with no human. `require_code_owner_review: true` keeps the **control
plane** (the gate's own definition + deploy/apply surfaces) held for a human — see
[`CODEOWNERS`](CODEOWNERS), two-tier with **no `*` default** so only control-weakening
paths hold. `@three-cubes/maintainers` is humans-only so an agent can never approve
the gate that gates it.

## The rules and what enforces them

| Requirement | Enforced by | Component |
|---|---|---|
| Branch name — Linear `<user>/<team>-<number>-<slug>`, a Conventional Branch prefix, or a bot namespace | GitHub | native `branch_name_pattern` in `org-branch-naming` |
| Work-item traceability — the branch embeds the Linear id (operational/bot prefixes exempt) | GitHub | native `branch_name_pattern` in `org-branch-naming` (the runtime `require-work-item.yml` callers were retired) |
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

**Sonar** is **decommissioned** (Dan, 2026-07-12) — `SonarCloud scan` / `SonarCloud Code
Analysis` are no longer required anywhere. A free two-tier gate — deterministic OSS checks
plus a self-hosted Foundry LLM judge — together with the new-code-coverage floor carries the
merge gate. **Independent verifier** and **Mutation** are not required either, deferred until
tc-fitness wires those workflows.

## Phased rollout — you cannot flip the ruleset first

Requiring a context a repo doesn't yet emit deadlocks its PRs. Order:

1. **Converge the emitters.** Rename each repo's fan-in to `Quality gate` (kairix `CI gate`,
   kata `Quality gate / Python quality gate result` → `Quality gate`). Wire the `no-attribution`
   caller in every repo. Work-item traceability moves to the native `org-branch-naming` rule —
   the runtime `require-work-item.yml` callers are retired.
2. **Align the paved path.** Bump every repo to the org-canonical pins (engine `v0.14.1`,
   reusable `v1.15.0`); taz sets `enforce-new-code-coverage: true`. Ensure each repo's Azure WIF
   federated credential exists (auto-merge prerequisite). Branch naming needs no per-repo fitness
   binding — the native `org-branch-naming` rule covers all repos (the engine `branch_naming`
   check now also exempts Conventional Branch prefixes).
3. **Flip.** Import `org-main-product`, `org-main-core`, `org-main-baseline`, and
   `org-branch-naming` as organization rulesets; delete the per-repo rulesets. Verify a green
   work PR auto-merges and a control-plane PR holds.

## Open items for the owner (org-admin)

- Org rulesets aren't API-readable by the App, so the *current* live state was inferred from
  these snapshots + docs — reconcile against the live org rulesets when importing.
- Confirm the repo-name targeting (new repos default to the **product** profile; the
  `org-branch-naming` rule already covers every repo).
- The `org-branch-naming` rule exempts the `dependabot`/`renovate` bot namespaces natively, so
  a bot PR — which can't cite a Linear item — still satisfies the branch rule.
