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

If you are an agent or directing one, also read the repo's `CLAUDE.md`. It carries the agent-specific operating contract: primary-agent review gate before each cherry-pick / PR approval, worktree-isolation hygiene for parallel subagents, human gate on PR *creation* (not just merge), and the actionable-feedback principle for any new pipeline-blocking message. The human-readable workflow document below stays canonical for humans; `CLAUDE.md` is its agent-shaped sibling.

### Track substantial work as a Linear item

Track substantial or delegated work as a Linear work item — do not let it live only in chat. Use the delivery-management verbs: **specify** the work, **decompose** it, **delegate** to a cluster, **update** as it progresses, **harvest** the decisions, and **close** when done. Harvest before you close — once the conversation decays, the work item is the durable record. Route intent ("track this", "add to Linear") through the repo's delivery-management ToolPack. Canon: the delivery-management operating model + operating-model standard.

### Commit and ship under a per-agent GitHub App

Commit, open PRs and merge under your **per-agent GitHub App** identity (one `tc-agent-<name>` App per agent) with short-lived installation tokens — not a shared human PAT. The App tiers are least-privilege: agents cannot self-approve, bypass CODEOWNERS, or override branch protection. A human approves every PR and owns the merge gate. Canon: the agent SDLC access + HITL standard.

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
| **Execute → Review** | Open PR, all automated checks pass, complete manual verification checklist. |
| **Review → Merge** | Merge commit to `main`, ~daily cadence per feature branch. Branch deletes after merge. |
| **Merge → Deploy → Verify** | Deploy is operator-triggered, not automatic on merge: run the `deploy-on-merge` workflow (`workflow_dispatch`), select scope, then verify the post-deploy health check and smoke test. Fix forward if deploy fails. |

> **Deploy is not automatic on merge.** The `deploy-on-merge` workflow deliberately disables the push trigger — the manual `workflow_dispatch` is the human gate against unintended production changes. The job authenticates to the cloud via WIF/OIDC, snapshots the target host, applies the selected scope (e.g. `auto`/`config`/`infra`), and runs the smoke check. The deploy reusables live in [tc-pipelines](https://github.com/three-cubes/tc-pipelines) (`azure-vm-deploy.yml`).

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

### Local-first feedback loop

**The CI/CD pipeline is sign-off, never the primary feedback loop.** It is designed to be slow and thorough; using it to discover what's broken burns its purpose and everyone's time. Before **every** push:

| Run locally | Covers |
|---|---|
| `make check` | the fitness harness + ruff/bandit/secret-scan/bicep/TS gates — **but NOT the platform pytest**: it skips `tests/` with `No platform Python tests present in tests/; skipping pytest` |
| `uv run pytest tests/fitness <skill-test-dirs>` | the pytest run CI's **Quality gate AND SonarCloud scan** both execute. `make check` passing does NOT imply these pass — run pytest before every test/Python push |
| `uv run detect-secrets-hook --baseline .secrets.baseline $(git diff --name-only origin/main...HEAD)` | CI's changed-file secret scan, against the same base |
| `shellcheck` on touched shell scripts | CI shell linting |

A push whose CI failure was locally reproducible is a process violation. If CI fails anyway, reproduce the failure locally first, fix it there, and push once.

Sync dependencies with **`uv sync --all-packages`** — bare `uv sync` uninstalls workspace-member dependencies (pptx, openpyxl, …) and false-fails `script_help_smoke`. The agent Bash tool runs **zsh**: `for x in $var` does not word-split (use `${(f)…}` or a literal list), and `mapfile` / `timeout` are unavailable.

#### Generated-artefact regen map

Adding or changing a surface regenerates a tracked artefact that a freshness gate enforces. Regenerate it and commit it in the same change, or CI fails on a stale artefact:

| When you… | Regenerate | Commit as |
|---|---|---|
| add/change a public interface (MCP tool, CLI, Bicep, plugin) | the interface-inventory generator → `public-interface-inventory.yaml` | the repo's **generator identity**, in its own commit (per the `storage_policy_validate` gate) |
| add an argparse CLI | an F30 outcome test (subprocess the script with the **literal** path string in `args`; assert on stdout) + a paired test (`test_discipline`); ensure `--help` exits 0 (`script_help_smoke`) | normal |
| add/change a skill | `python3 scripts/build-skills-catalog.py` → `docs/architecture/skills-catalog.md` + `agent-bootstrap/capabilities/*.json` | normal |
| lift a skill's maturity level | `python3 scripts/checks/skill_maturity_ledger.py --write` (reports) then `--accept-ratchet` (pin the baseline) | normal |

A runtime-type classifier (e.g. `build-skills-catalog.py:_infer_skill_type`) MUST exclude `tests/`/`evals/` — a validation test must not reclassify a prompt-only skill as code. In `set -euo pipefail` scripts increment with `n=$((n + 1))`, never `((n++))`: `((n++))` returns the pre-increment value, whose arithmetic exit status is 1 when `n` is 0, so `set -e` aborts the script.

A detect-secrets false positive on a keyword-like name (`secret_resolution`, an `api_key` placeholder) clears with an inline `# pragma: allowlist secret`; commit the hook's auto-updated `.secrets.baseline` alongside it.

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

### Manual Gates (PR Checklist)

| Gate | When Required |
|------|--------------|
| Mobile/responsive test | Any visual change |
| Keyboard navigation test | Any interactive element change |
| Accessibility audit | Any new interactive element |
| UI copy review | Any user-facing text change |

### Post-Deploy Gates

| Gate | What |
|------|------|
| Health check | Health endpoint returns 200 |
| Auth enforced | Authenticated endpoint returns 401 without token |
| Smoke test | Post-deploy script confirms core flow works |
| No crash loops | Container/service logs show clean startup |

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

- **Merge commit** to `main` (`gh pr merge --merge --delete-branch`) — squash and rebase merging are disabled at the repo level so the feature branch's commit history is preserved.
- PR title: `type(scope): description (#issue)`
- Branch deletes after merge

### Merge gate — required contexts, review, and `--admin`

Three status contexts gate every merge: **Quality gate** (`make check`), **SonarCloud scan** (the GH Actions pytest+coverage job), and **SonarCloud Code Analysis** (the SonarCloud app's new-code quality gate). Beyond these, two active org **rulesets** (`org-baseline-main`, `main`) require **1 approving review + code-owner review + thread resolution** — this is invisible in classic branch protection, which reports `required_approving_review_count: 0`. A PR author cannot self-approve.

`gh pr merge --admin` is the **owner's logged exception** that clears the review gate. Agents request it; they never self-authorise (the durable rule is "agents have no override"). The admin-bypass also covers, under the interim coverage-gate policy, a **coverage / duplication / smell-only** SonarCloud Code Analysis failure.

It MUST NOT clear a **Security Rating worse than A**. Before any `--admin` past a failing SonarCloud Code Analysis, read the SonarCloud PR decoration (`gh api repos/<org>/<repo>/issues/<pr>/comments` → the `sonarqubecloud[bot]` body) and check the failed conditions. A security finding is fixed, not bypassed — repo policy sets **no Sonar issue-ignore overrides** (see `sonar-project.properties`): genuinely refactor the finding (e.g. validate + reconstruct a URL flowing to `urlopen` for S5144 SSRF), never suppress it.

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

## Per-repo reconciliation notes

Apply these repo-specific rules when adopting this baseline in a given repo:

- Branch from current `main` and use PRs for all repo changes.
- Do not edit live runtime config directly; change templates/scripts in the repo and apply only after explicit approval.
- Do not restart live services or deploy as part of documentation or standards work.
- One complete-feature PR with evidence (diff, validation command, rollback note) — never micro-PRs.
- Where a repo deploys to a host, treat the repo's checked-out tree as the canonical **deploy source** and engineering/edit surface — but **not a runtime path**. Operational code (gateway/MCP/plugins/hooks) should execute from an immutable, published tree; a deploy is `git pull` (source) → publish the immutable tree → render config + restart. See the repo's deploy runbook.
