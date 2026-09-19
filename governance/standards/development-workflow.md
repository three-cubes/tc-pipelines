# Development Workflow

*Strategic development process, quality gates, and continuous improvement framework.*

## Development Philosophy

Our development approach prioritises **systematic quality**, **evidence-based decisions**, and **continuous learning** through:

- **Test-first development** — Always write failing tests before implementation
- **Security by design** — Integrate security considerations from the start
- **Minimal viable changes** — Smallest change that solves the problem
- **Evidence-based debugging** — Root cause analysis over assumptions
- **Backward compatibility** — Preserve existing user workflows unless there is compelling reason to break them

---

## Agent-specific contract

If you are an agent or directing one, also read the repo's `CLAUDE.md`. It carries the agent-specific operating contract: primary-agent review gate before each cherry-pick, worktree-isolation hygiene for parallel subagents, the CODEOWNERS control-plane review carve-out (the human-in-the-loop sits on the gate's own definition, not on every PR), and the actionable-feedback principle for any new pipeline-blocking message. The human-readable workflow document below stays canonical for humans; `CLAUDE.md` is its agent-shaped sibling.

### Track substantial work as a Linear item

Track substantial or delegated work as a Linear work item — do not let it live only in chat. Use the delivery-management verbs: **specify** the work, **decompose** it, **delegate** to a cluster, **update** as it progresses, **harvest** the decisions, and **close** when done. Harvest before you close — once the conversation decays, the work item is the durable record. Route intent ("track this", "add to Linear") through the repo's delivery-management ToolPack. Canon: the delivery-management operating model + operating-model standard.

### Commit locally; ship through a GitHub App broker

Create local commits with the canonical `three-cubes-agent[bot]` author and committer metadata; this needs no credential. Send every off-CI `git`, `gh`, or API write through the trusted host broker, which mints a repository-scoped, short-lived installation token for the selected App and confines it to one operation. The agent harness never receives Key Vault access or token material, and never falls back to a shared human PAT. In Actions, the WIF-backed composite provides the equivalent job-scoped token path; Actions repository secrets are not a local plaintext retrieval mechanism. The App tiers remain least-privilege: an agent cannot self-approve, bypass CODEOWNERS, or override branch protection.

Commit *author* and *committer* always resolve to `three-cubes-agent[bot]` / `295831460+three-cubes-agent[bot]@users.noreply.github.com`, independent of which per-agent App performs the remote write. Carry no AI/LLM self-attribution: no `Co-Authored-By: <model>` trailer, no "Generated with" credit, no robot emoji. The `no_llm_attribution` + `canonical_commit_identity` fitness checks and the commit-msg strip hook enforce this on every commit and the PR title + body. Because a PR author cannot approve their own PR, App-authorship is exactly what lets a human maintainer review the control-plane changes that need one.

Ordinary work then **merges itself on a green gate** — no human runs the merge; a human review is required only on the control-plane paths CODEOWNERS pins (see the Merge gate below). Canon: the [Agent SDLC-access + HITL standard](../agent-sdlc-access-and-hitl.md) + [`STANDARDS.md §4`](../STANDARDS.md).

## Work Lifecycle

Every piece of work follows the same lifecycle regardless of size:

```
Idea → Issue → Plan → Execute → Review → Merge → Deploy → Verify
```

| Phase | Key Activities |
|-------|---------------|
| **Idea → Issue** | All work starts as a tracked issue. Assign priority and milestone. |
| **Issue → Plan** | List files that change, define verification criteria, identify dependencies and risks. |
| **Plan → Execute** | Branch from `main`, follow commit conventions, run verification after every logical change. |
| **Execute → Review** | Open PR as the App, all automated checks pass, complete manual verification checklist. |
| **Review → Merge** | On a green gate, `auto-merge-on-green.yml` arms `gh pr merge --auto` as the App and GitHub merges the moment every required check passes — no human runs the merge. Branch deletes after merge. |
| **Merge → Release or Deploy → Verify** | Exact integration allocates the release, builds one immutable candidate, publishes it through the protected environment and deploys that digest. Product PVT promotes or rolls back the candidate. See `sdlc-release-workflow.md` and `ci-release-deployment-architecture.md`. |

> **Product release deploys the qualified digest.** The release graph hands the
> candidate receipt to the protected production environment. The target verifies
> recovery coverage, applies that digest and records product PVT, rollback and
> cleanup. See [`deployment-verification.md`](deployment-verification.md),
> [`snapshot-before-apply.md`](snapshot-before-apply.md), and
> [`agent-sdlc-access-and-hitl.md`](../agent-sdlc-access-and-hitl.md).

The current container-only path remains governed by
[`snapshot-before-apply.md`](snapshot-before-apply.md) until its typed transaction
replacement passes the same rollback journey.

---

## Workflow Decision Matrix

| Scenario | Workflow |
|----------|----------|
| Test is failing unexpectedly | **Debug** |
| Function returns wrong value | **Debug** |
| Security vulnerability found | **Security fast-track** |
| Adding validation to existing function | **Feature development** |
| Creating new feature | **Feature development** |
| Refactoring architecture | **Feature development** |

**Switch from Debug → Development if:** solution requires >50 lines of new code, new classes/modules, touches >3 files, affects public APIs, or needs new dependencies.

---

## Quality Gates

> **Improving the shared product?** Change the canonical `tc-fitness` or
> `tc-pipelines` home and qualify one coordinated SDLC release through
> [`improving-fitness-gates.md`](improving-fitness-gates.md). The fitness quality
> bar is [`gate-hardening.md`](../gate-hardening.md).

### Local-first feedback loop

The released SDLC environment provides the local feedback loop and the hosted
sign-off path. Use the stable repository commands:

| Run locally | Covers |
|---|---|
| `make bootstrap` | Released toolchain, dependencies and generated SDLC lock. |
| `make prepare` | Formatting, generators, manifests and other deterministic maintenance. |
| `make check` | Affected language, build, security and `tc-fitness` tasks. |
| `make check-all` | Complete graph required for release admission. |

Repositories on the migration path use their documented `make check` command
until `tc-sdlc` supplies these targets. Their adoption state is recorded in
[`../../docs/MIGRATION.md`](../../docs/MIGRATION.md).

Record local evidence in the PR or handoff: tested commit, exact commands,
terminal exit status, SDLC lock, task identities and generated receipt or
artifact identities. Passing evidence requires a complete terminal result and
the behavioural assertions required by that task. The ordered validation ladder
and stop conditions live in
[`validation-and-backpressure.md`](validation-and-backpressure.md).

The consumer's `sdlc.yaml` declares generator inputs and outputs. `make prepare`
refreshes them before evaluation. Repository-specific generator instructions
live beside the generator or in the consumer resolver.

### Pre-Code Gates (All Work)

- [ ] Strategy alignment confirmed
- [ ] Test approach planned
- [ ] Security implications assessed
- [ ] Backward compatibility considered

### Automated Gates (CI Enforced)

| Gate | Blocks merge? |
|------|--------------|
| Type checking (zero errors) | ✅ Yes |
| Unit + contract tests | ✅ Yes |
| Linting / code quality | ✅ Yes |
| Security scan | ✅ Yes |
| Build succeeds | ✅ Yes |

### Product acceptance gates

Each product declares the journeys required by its change surface. UI changes
include accessibility and supported viewport journeys. Runtime changes include
real dependency, state and recovery journeys. The graph selects the declared
journeys through project dependencies and affected inputs.

### Post-Deploy Gates

| Gate | What |
|------|------|
| Health check | Health endpoint returns 200 |
| Auth enforced | Authenticated endpoint returns 401 without token |
| Product verification test | Product journey proves the deployed candidate's intended outcome |
| No crash loops | Container/service logs show clean startup |

### Definition of Done

A change is DONE when its behaviour is proven and its required gate is verified. Two clauses make that concrete as procedure (layer-3 in [`agent-process-controls.md`](agent-process-controls.md)) rather than guidance a busy agent may skip:

- **Pin a shared-contract behaviour change with red-before-green evidence.** A change to a shared contract — a public method, or an engine surface a consumer depends on — is DONE only when the PR body carries the pinning test run against the **old** behaviour and shown **failing**, then green on the new code. The failing run proves the test binds the behaviour that changed; a test added after the change can pass without ever exercising it.
- **Claim "done" or "green" from a verified required check.** Cite the
  repository's actual required contexts and terminal results. A workflow still
  running or a partial log records progress.

---

## Branching and Commit Conventions

### One branch per feature, merged daily

- **One feature = one branch = one PR.** Every commit for the feature — implementation, sub-agent output, docs, gate fixes, review remediations — lands on that single branch. Never fan a feature out into micro-PRs.
- **Merge the feature branch to `main` ~once a day** while the feature is in flight. A feature branch never lives past the day's merge without a deliberate reason.
- **Defects found after a merge are remediated in a single additional commit** on the feature branch (or its next-day successor) and merged — one remediation commit + one merge, not a cascade of follow-up PRs.
- Work that surfaces on `main` mid-feature (gate breaks, rename fallout) is repaired **on the open feature branch** as part of the day's merge, not in its own PR.

### Branch Naming

The `branch_naming` fitness gate enforces Linear's `gitBranchName` shape
`<user>/<team>-<number>-<slug>` — the branch carries its Linear issue
identifier, so the issue↔branch↔PR link is automatic (per
[`roadmap-management-linear-github.md`](roadmap-management-linear-github.md)).
Copy the exact name from the Linear issue ("Copy git branch name"):

```
dan/kno-45-pr-a-sync-compose_slide-dispatch-table-stage-columns
dan/kno-48-pr-d-mcp-powerpoint-doctor-cli-bindoctor
dan/exe-12-engagement-bundle-manifest
```

`main`/`develop` and automation branches (`worktree-agent-*`, `renovate/*`,
`dependabot/*`, `gh-pages`) are exempt. The commit-message type prefix
(`feat`/`fix`/`chore`/…) still names the concern — see Commit Messages below.

### Commit Messages

```
feat(scope): add voice capture hold-to-record (#42)
fix(auth): wire Bearer token into API client (#75)
chore(cleanup): remove legacy references (#54)
docs: update ways of working with agent workflow
```

**Scope examples:** `auth`, `ux`, `api`, `ci`, `build`, `a11y`, `backend`, `cleanup`

### Merge Strategy

- **Merge commit** to `main` — squash and rebase merging are disabled at the repo level, so the feature branch's commit history is preserved. The merge is **armed** by the App via `gh pr merge --auto --merge --delete-branch` and **executed by GitHub** the moment every required check is green; a human does not run it.
- PR title: `type(scope): description (#issue)`
- Branch deletes after merge.

### Merge gate — required contexts, review, and auto-merge

Three status contexts gate every merge: **Quality gate** (`uv run tc-fitness run`), **SonarCloud scan** (the coverage + new-code analysis job), and **SonarCloud Code Analysis** (the SonarCloud app's new-code quality gate); a repo that has hardened its gate also requires **Mutation**. The `main` ruleset (`RULESET-D1`) blocks deletion + force-push, is **not strict** (no forced up-to-date rebase), does **not** stale-dismiss reviews, and requires **0 approvals on ordinary work**.

**Ordinary work auto-merges on green.** `auto-merge-on-green.yml` fires on the Quality-gate `workflow_run` completion; when the fan-in "CI gate" check-run is green it arms `gh pr merge --auto` as the App, and GitHub merges the instant every required context passes. No human runs the merge.

**Control-plane changes hold for a human.** A PR that touches a CODEOWNERS-owned path — the CI/merge machinery, the gate's own definition (`[tool.tc_fitness]`), governance canon, contracts/schemas, deploy/runtime-config — requires a `@three-cubes/maintainers` (humans-only) review and does **not** auto-merge. Everything else — skills, tools, tests, feature docs, content — merges unattended on green. This is what makes App-authorship load-bearing: because an author cannot approve their own PR, the required human review is a genuine second party. The two CORE paved-road repos (tc-pipelines, tc-fitness) hold *every* PR for an `n+1` human approval — see [`process-shared-repo-pr-review-and-merge.md`](process-shared-repo-pr-review-and-merge.md).

`gh pr merge --admin` is the **owner's logged exception**, requested by an agent and never self-authorised — a ruleset with no bypass actors blocks even admins, so the override is a deliberate human act. It clears the review gate and, under the interim coverage-gate policy, a **coverage / duplication / smell-only** SonarCloud Code Analysis failure — but never a required check red for another reason, and never a **Security Rating worse than A**. Before any `--admin` past a failing SonarCloud Code Analysis, read the SonarCloud PR decoration (`gh api repos/<org>/<repo>/issues/<pr>/comments` → the `sonarqubecloud[bot]` body) and check the failed conditions. A security finding is fixed, not bypassed — repo policy sets **no Sonar issue-ignore overrides** (see `sonar-project.properties`): genuinely refactor the finding (e.g. validate + reconstruct a URL flowing to `urlopen` for S5144 SSRF), never suppress it.

Canon: [`STANDARDS.md §4`](../STANDARDS.md) + [`agent-sdlc-access-and-hitl.md`](../agent-sdlc-access-and-hitl.md); `RULESET-D1` / `CODEOWNERS-D1` / `STD-MERGE` in [`ADR-POLICY.md`](../decisions/ADR-POLICY.md).

---

## Compliance and Monitoring

### 4-Layer Defence

| Layer | Trigger | Gate |
|-------|---------|------|
| **SAST** | Before every commit | No HIGH/MEDIUM security issues |
| **Dependency analysis** | Daily scans, before deploy | No known CVEs with patches |
| **Dynamic testing** | Test execution phase | All security tests pass |
| **Source control security** | Pre-commit hooks, audits | No secrets in history |

### Quality Thresholds

- **Security:** Zero HIGH findings; MEDIUM findings documented with risk assessment
- **Quality:** Meets language-specific linter threshold
- **Coverage:** Meets minimum coverage targets (see Testing Strategy)
- **Dependencies:** All known CVEs updated within 1 week

### Non-Compliance Response

| Severity | Action |
|----------|--------|
| HIGH security issues | Immediate build failure; blocks merge; escalate if unresolved >24h |
| Known CVEs with active exploits | Immediate dependency freeze; emergency patching |
| Quality regressions | Build warning; mandatory review; refactoring scheduled if trend continues |

### Override Process (Emergency Use Only)

1. Document justification with specific business reason
2. Detailed risk assessment and consequences analysis
3. Mitigation plan with steps to address post-deployment
4. Senior approval (architect or tech lead sign-off)
5. Maximum override duration specified; auto-expires

---

## Infrastructure-Gated Changes

When a change involves both infrastructure (DNS, cloud resources, auth configuration, certificates) and code references, follow this sequencing:

| Step | What | Example |
|------|------|---------|
| 1. Infrastructure deployed | Cloud resource, DNS record, certificate provisioned | Add custom domain to Container App, update DNS CNAME |
| 2. Infrastructure verified | Smoke test or health check confirms accessibility | `curl -f https://new-domain.example.com/health` |
| 3. Operational references updated | CI/CD workflows, smoke tests, deploy scripts | `SMOKE_TEST_BASE_URL`, `PLAYWRIGHT_BASE_URL` |
| 4. Code references updated | Application code, documentation, specs | Config files, CLAUDE.md, spec docs |

**Critical rule:** Deploy-critical references (CI/CD URLs, smoke tests, health check targets) must **never** be updated before the infrastructure they depend on is live and verified. Documentation-only references may be updated ahead of infrastructure.

**Anti-pattern:** Updating smoke test URLs to a new domain before DNS resolves → deploy pipeline breaks with network errors even though the application deployed successfully.

---

## Change Management

### Default: Preserve Compatibility

Always preserve existing user workflows unless there is compelling reason to break them:

- Command line arguments and options
- File formats and directory structures
- Environment variables and configuration
- API responses and error codes

### When Breaking Changes Are Justified

- **Security requirements** — Insecure defaults → secure defaults
- **Critical bug fixes** — Data corruption/loss → preservation
- **Major architecture** — Significant improvement with clear user benefit

### Breaking Change Strategies

| Strategy | Approach |
|----------|----------|
| **Deprecation path** (preferred) | Support old and new behaviour; warn about old usage |
| **Configuration flag** | Allow users to opt into new behaviour |
| **Auto-detection** | Detect old vs new format and handle appropriately |
| **Version-based** | Different behaviour based on configuration version |

---

## Continuous Improvement

### Retrospective Triggers

- After security-critical work
- After resolving major bugs or issues
- After implementing complex features (>5 files changed)
- After any process violation

### Improvement Loop

```
DO WORK → REFLECT → LEARN → IMPROVE → APPLY → repeat
```

**Immediate actions:** Fix remaining issues, update documentation, add missing tests.
**Process updates:** Update standards and practices documents, add checklist items.
**Strategic changes:** Tool adoption, skill development, architecture improvements.

---

*For tactical implementation procedures and checklists, use the repo standards index. Retrospective process details are pending migration from the vault.*


---

## Consumer-specific instructions

The consumer resolver routes product files, runtime adapters and runbooks. The
shared product supplies environment, orchestration and evidence. Product
deployment applies immutable published artefacts and records the deployed digest.
