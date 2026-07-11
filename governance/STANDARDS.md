# Three Cubes — Build, Release & Governance Standard (CANONICAL)

> **🛑 Agents & humans: READ THIS before touching CI, the quality gate, fitness functions,
> coverage, mutation, or merge governance in ANY repo. These standards already exist and are
> detailed. Do NOT re-derive them. Converge *up* to them; promote improvements *into* the
> canonical homes below — never fork a parallel standard.**

This is the single referenceable index of the org's build/release/governance intent. It points to
the authoritative sources; it does not restate them.

## 1. Quality + fast-feedback requirements (the OKRs)

**[Build & Release Health initiative](https://linear.app/three-cubes/initiative/build-and-release-health-afb5e313b215)** (Linear) — the requirements, from a 6-agent root-cause diagnosis (2026-06-21):

- **O1 — Trustworthy local loop:** `make check` runs the *literal* CI command; a **<60s smoke tier** exists. (Fast feedback is a first-class requirement, not a nice-to-have.)
- **O2 — Honest, enforcing coverage:** whole-product scope, re-captured baseline, **required monotonic ratchet**, no skip-pass.
- **O3 — Fitness that bites:** ≥1 architecture/layering gate, mutation pilot, de-theatre placement-only rules.
- **O4 — Self-draining supply chain:** dependency auto-merge, zero high-severity alerts > 7 days.

KPIs and the **Wave 0/1/2** execution plan live in the initiative.

## 2. The fitness-function spec (the detailed design)

**[kairix#499 — "fitness-function system v2"](https://github.com/three-cubes/kairix/issues/499)** — the defect-grounded spec:

- the **F-series** fitness functions (~70 ADR/incident-traced rules), a single catalogue, never-renumber discipline;
- the **tiered, time-budgeted execution model** — pre-commit / safe-commit / CI Stage-0 (**<3s**); diff-scoped mutation (**~2–3 min**); nightly soak (non-blocking). *This is how "harder gate" and "fast feedback" coexist — rigour is diff-scoped and tiered, never brute-forced on the inner loop.*
- **Phase 4 = org-shared CI** (`uses:` reusables) — the convergence every repo follows.

**kairix is the reference implementation.** Best-of-breed patterns are promoted *into* the canonical
engine + reusables, then every repo converges up — nobody is down-levelled.

## 3. Canonical homes (where the standard lives — improve it HERE)

- **[`tc-fitness`](https://github.com/three-cubes/tc-fitness)** — the runnable gate engine (`uv run tc-fitness run`) + the check catalogue. New checks land here.
- **[`tc-pipelines`](https://github.com/three-cubes/tc-pipelines)** (this repo) — the reusable `workflow_call` workflows + composite actions + `governance/` templates (rulesets, CODEOWNERS, gate-hardening, dependabot, pre-commit). CI + governance shape land here.
- **[`governance/gate-hardening.md`](gate-hardening.md)** — the bar a repo's gate must clear before it runs autonomously (a pointer to the §2 spec, not a parallel definition).
- **[`governance/standards/improving-fitness-gates.md`](standards/improving-fitness-gates.md)** — the mechanics of changing a gate or a reusable and shipping it (converge-up, tag-release, consumer-repin); the complement to `gate-hardening.md` (the bar).

## 4. Merge governance (the model)

Agents author PRs as a **dedicated GitHub App** — the canonical `three-cubes-agent`, or a **per-agent App** (`tc-agent-builder`/`shape`/`consultant`/`growth`) so the audit log shows *which* agent acted — never a human identity, so review is possible and attribution is clean. The capability-vs-enforcement model, the per-agent App set, and the token-mint surfaces are the [**Agent SDLC-access + HITL standard**](agent-sdlc-access-and-hitl.md) + [`agent-app-manifests/`](agent-app-manifests/). The merge model:

- **Autonomous on green** for ordinary work — a green gate auto-merges, no human, no admin bypass.
- **HITL only on the control plane** — the gate's own definition (CI, `[tool.tc_fitness]`, schemas, validators, dep pins, governance) needs a human (`@three-cubes/maintainers`) via **CODEOWNERS**, so an agent can never weaken the gate that gates it.
- **De-churned** — no forced up-to-date rebase, no stale-dismiss (see [`governance/rulesets/main.json`](rulesets/main.json) + [`governance/CODEOWNERS`](CODEOWNERS)).
- **Clean authorship is CI-enforced, not convention** (decision D1) — the reusable gates ship a toggleable `no-attribution` leg (`meta-quality-gate.yml`, symmetric in `python-quality-gate.yml`; `run-no-attribution` input, default on) that rejects AI/LLM self-attribution residue in **every PR commit message and the PR title + body**, read-only (CI never rewrites history), via the single shared tc-fitness `no_llm_attribution` detector the local commit-msg strip hook and the fitness gate also use. It publishes the stable required-status-check context **`no-attribution`**; [`governance/rulesets/main.json`](rulesets/main.json) gates `main` on it. Renaming the leg's job means updating that context in lockstep.

This model is **safe only because the gate is hard + fast** (§1–§2). Harden + verify a repo's gate before flipping it to autonomous.

The **failure-driven auto-dispatch loop** that rides this model — its explicit state machine, the deterministic-glue vs judgment split, and the 5 hard guardrails that must be *proven to fire* before any lights-out flag flips — is specified in [`governance/autonomous-loop.md`](autonomous-loop.md) (decision record: [`governance/decisions/ADR-LOOP-STATE-MACHINE.md`](decisions/ADR-LOOP-STATE-MACHINE.md); validation harness: [`governance/loop/`](loop/)). **No auto-dispatch flag flips until that harness is green** (SP-C-1 / PLA-309).

## 5. The inner-loop contract — replay the gate before you push

The merge model (§4) is safe **only if green-locally implies green-in-CI.** Every `main`-break this
org has had traces to a violation of one of these four rules:

1. **Replay the *exact* CI gate locally before every push.** With the full dev env installed
   (`uv sync --all-extras --all-groups`), run what CI runs — `uv run pre-commit run --all-files`
   **and** `uv run tc-fitness run` — and get it green. A bare `python3` / `ruff` / single-file run is
   **not** a replay: it silently skips import-dependent fitness rules (they need the engine installed)
   and only checks the files you name, while CI runs `--all-files`. Repo-specific hooks that import
   repo code, `tc-fitness`, or tool dependencies must enter the locked uv environment and use a
   sandbox-safe cache outside `$HOME` (`UV_CACHE_DIR=/tmp/<repo>-uv-cache`, plus
   `UV_LINK_MODE=copy` when symlinked caches are not portable). Bare `python3` is allowed only for
   stdlib-only hooks. If it is green locally but red in CI, that is an **O1 parity bug in the local
   loop** (§1, O1) — fix the loop; never paper over it.

2. **Regenerate-and-stage generated artifacts.** When you touch an *input* to a generated file,
   regenerate it and stage it in the **same** commit. A stale generated artifact reds `main` even when
   your hand-edit was correct. Known input→artifact pairs: `.github/CODEOWNERS` →
   `public-interface-inventory.yaml`; catalogue inputs → the catalogue-currency check. The `pre-push`
   hook (`governance/git-hooks/pre-push`, wired via `pre-commit install --hook-type pre-push`) now
   enforces this by replaying the full `tc-fitness run` before every push — a stale artifact fails the
   gate locally. `git push --no-verify` skips it, for a genuine emergency only.

3. **Reconcile before push — locally, never in the UI.** When your branch is behind trunk, run
   `git fetch && git merge origin/main` **locally**, replay the gate (rule 1), then push once. Clicking
   *Update branch* in the GitHub UI merges trunk and launches a fresh ~16-minute CI run you have not
   replayed — the merge result can red even when your branch was green. Reconcile-and-replay locally so
   the push you make is the exact state CI signs off.

4. **Never merge over a red gate.** No admin bypass, no "I'll fix it after." A red gate means the
   change is not done. The autonomous rulesets enforce this (zero bypass actors); **humans must hold
   the same line** — admin-merging red work is what breaks `main` and forces self-heal churn.

## 6. For agents (the anti-reinvention rule)

Before you design a quality gate, a fitness function, a coverage/mutation policy, a CI workflow, or a
governance rule: **it already exists above.** Read it. If it's missing or weak, **propose the change
into the canonical home** (§3) — open a PR to `tc-fitness`/`tc-pipelines` — do not re-create it in a
single repo. The mechanics of that change (CORE check → tag-release → consumer-repin; reusable →
SHA-pin → tag) are in [`standards/improving-fitness-gates.md`](standards/improving-fitness-gates.md).
Every repo's `AGENTS.md` / `CLAUDE.md` / `.github/copilot-instructions.md` links here for exactly
this reason.

## 7. Engineering standards library (`standards/`)

The canonical body of each engineering standard lives once, here, in
[`standards/`](standards/). A repo's own docs **reference** these — they do not re-copy them. When a
pattern is weak, improve it here; every repo converges up. (The SDLC-access + HITL, gate-hardening,
security-scan, and Autonomous-Delivery standards keep their existing homes at the `governance/` top
level — see §3–§4 — and are not duplicated below.)

| Concern | Standard | What it governs |
|---|---|---|
| SDLC & workflow | [`development-workflow.md`](standards/development-workflow.md) | Branch, commit, PR, quality-gate, local-first loop conventions. |
| SDLC & workflow | [`testing-strategy.md`](standards/testing-strategy.md) | The test pyramid (contract/integration/E2E) + quality gates. |
| SDLC & workflow | [`validation-and-backpressure.md`](standards/validation-and-backpressure.md) | The syntax→unit→contract→integration→BDD ladder + stop conditions. |
| SDLC & workflow | [`sdlc-release-workflow.md`](standards/sdlc-release-workflow.md) | Trunk-based release: tag from `main`, CHANGELOG-driven notes. |
| SDLC & workflow | [`contract-test-patterns.md`](standards/contract-test-patterns.md) | Copy-paste contract-test skeletons (TS + Python) + baseline-shrink. |
| SDLC & workflow | [`process-shared-repo-pr-review-and-merge.md`](standards/process-shared-repo-pr-review-and-merge.md) | Review + merge process for shared repos the author can't self-approve. |
| SDLC & workflow | [`agent-process-controls.md`](standards/agent-process-controls.md) | The control hierarchy for agent-behaviour risks — push high-value risks from guidance up to structural gates. |
| Quality & fitness | [`quality-ratchet.md`](standards/quality-ratchet.md) | Touched-file coverage ratchet — lift without papering. |
| Quality & fitness | [`mutation-testing-survival-ratchet.md`](standards/mutation-testing-survival-ratchet.md) | Diff-scoped mutation + survivors ratchet. |
| Quality & fitness | [`agent-actionable-feedback.md`](standards/agent-actionable-feedback.md) | Every error carries `fix:`/`next:`/`run:`. |
| Quality & fitness | [`sonarqube-usage.md`](standards/sonarqube-usage.md) | New-code gate conditions, Security-Rating≥A, don't-ignore policy, FP mechanics. |
| Quality & fitness | [`improving-fitness-gates.md`](standards/improving-fitness-gates.md) | Add/improve a CORE check or a reusable and ship it: converge-up, tag-release, consumer-repin. |
| Architecture & decisions | [`architecture-decision-method.md`](standards/architecture-decision-method.md) | How a decision is researched + justified (method, not ADR mechanics). |
| Architecture & decisions | [`engineering-nfr-standard.md`](standards/engineering-nfr-standard.md) | The six-dimension NFR checklist every design must clear. |
| Language & deps | [`python-dependency-locking.md`](standards/python-dependency-locking.md) | uv workspace + frozen `uv.lock`. |
| Language & deps | [`js-ts-tooling-baseline.md`](standards/js-ts-tooling-baseline.md) | pnpm workspace + flat-config eslint. |
| IA, naming & docs | [`repo-ia-and-naming.md`](standards/repo-ia-and-naming.md) | Repo layout + file/dir naming syntax. |
| IA, naming & docs | [`naming-for-agent-affordance.md`](standards/naming-for-agent-affordance.md) | Name the WORK not the implementation — semantics of skill/tool/MCP names. |
| IA, naming & docs | [`no-real-names.md`](standards/no-real-names.md) | Synthetic names in fixtures/examples. |
| IA, naming & docs | [`documentation-standard.md`](standards/documentation-standard.md) | Doc structure + describe-the-target-not-the-journey. |
| Security & config | [`security-framework.md`](standards/security-framework.md) | Secrets, privileged ops, network + destructive-op gating. |
| Security & config | [`repo-governance-secret-wiring.md`](standards/repo-governance-secret-wiring.md) | Wiring a repo's governance secrets safely. |
| Security & config | [`environment-and-config-management.md`](standards/environment-and-config-management.md) | One committed registry for every deploy-target identifier; secrets referenced by name. |
| Bootstrap & adoption | [`new-repo-bootstrap.md`](standards/new-repo-bootstrap.md) | Standing up a repo with the standards baked in. |
| Bootstrap & adoption | [`common-standards-adoption-playbook.md`](standards/common-standards-adoption-playbook.md) | Converging an existing repo up to the common standards. |
| Bootstrap & adoption | [`roadmap-management-linear-github.md`](standards/roadmap-management-linear-github.md) | Linear-as-control-surface + GitHub linkage. |
| Deploy & ops | [`snapshot-before-apply.md`](standards/snapshot-before-apply.md) | Recovery point before any destructive apply (concrete: VM OS-disk snapshot). |
| Deploy & ops | [`deployment-verification.md`](standards/deployment-verification.md) | Recovery-point-before + verification-probe-after, generalised beyond one cloud. |
| Agent orchestration | [`subagent-orchestration.md`](standards/subagent-orchestration.md) | Single owner, no parallel git ops, no live ops, bounded output. |
| Agent orchestration | [`sub-agent-orchestration-lessons-2026-05-17.md`](standards/sub-agent-orchestration-lessons-2026-05-17.md) | Field lessons that extend the orchestration standard. |
| Agent orchestration | [`parallel-agent-discipline.md`](standards/parallel-agent-discipline.md) | Dispatching parallel streams without collision. |
| MCP tooling | [`mcp-engineering-standard.md`](standards/mcp-engineering-standard.md) | Tool-design contract: structured I/O, validate companions, drop-and-warn. |
| MCP tooling | [`mcp-tooling-canonical-pattern.md`](standards/mcp-tooling-canonical-pattern.md) | MCP server language/layout/helpers/contract-tests. |
| MCP tooling | [`mcp-performance-and-affordance-measurement.md`](standards/mcp-performance-and-affordance-measurement.md) | Perf SLO bands + affordance scoring for a capability. |
