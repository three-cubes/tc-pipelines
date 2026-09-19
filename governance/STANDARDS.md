# Three Cubes AI SDLC Standard

> **🛑 Agents & humans: READ THIS before touching CI, the quality gate, fitness functions,
> coverage, mutation, or merge governance in ANY repo. These standards already exist and are
> detailed. Do NOT re-derive them. Converge *up* to them; promote improvements *into* the
> canonical homes below — never fork a parallel standard.**

This is the canonical index for the shared development environment, fitness,
CI, release, deployment and governance product. The product architecture is
[`standards/ai-sdlc-product-architecture.md`](standards/ai-sdlc-product-architecture.md).

## 1. Quality + fast-feedback requirements (the OKRs)

**[Build & Release Health initiative](https://linear.app/three-cubes/initiative/build-and-release-health-afb5e313b215)** (Linear) — the requirements, from a 6-agent root-cause diagnosis (2026-06-21):

- **O1 — Trustworthy local loop:** local and CI resolve the same released environment, lock and task definitions; a **<60s warm affected tier** exists.
- **O2 — Honest, enforcing coverage:** whole-product scope, re-captured baseline, **required monotonic ratchet**, no skip-pass.
- **O3 — Fitness that bites:** ≥1 architecture/layering gate, mutation pilot, de-theatre placement-only rules.
- **O4 — Self-draining supply chain:** dependency auto-merge, zero high-severity alerts > 7 days.

KPIs and the **Wave 0/1/2** execution plan live in the initiative.

## 2. The fitness-function spec (the detailed design)

**[kairix#499 — "fitness-function system v2"](https://github.com/three-cubes/kairix/issues/499)** — the defect-grounded spec:

- the **F-series** fitness functions (~70 ADR/incident-traced rules), a single catalogue, never-renumber discipline;
- the **tiered, time-budgeted execution model** — pre-commit / safe-commit / CI Stage-0 (**<3s**); diff-scoped mutation (**~2–3 min**); nightly soak (non-blocking). *This is how "harder gate" and "fast feedback" coexist — rigour is diff-scoped and tiered, never brute-forced on the inner loop.*
- **Phase 4 = org-shared execution** — the released environment, task graph,
  fitness profiles and hosted workflow entrypoints consumed by every repo.

`tc-agent-zone` is the first complete environment-to-production vertical.
Kairix remains a reference consumer for fitness behaviour. Proven shared
patterns move into `tc-pipelines` or `tc-fitness`, then consumers upgrade through
one coordinated SDLC release.

## 3. Canonical homes (where the standard lives — improve it HERE)

- **[`tc-pipelines`](https://github.com/three-cubes/tc-pipelines)** (this repo) — the released SDLC environment, task graph, reusable workflows, evidence and deployment protocols, governance library and adoption tooling.
- **[`tc-fitness`](https://github.com/three-cubes/tc-fitness)** — the runnable fitness engine and shared check catalogue. `tc-pipelines` executes compatible fitness profiles as graph tasks.
- **Consumer repository** — product source, tests, generated artefacts, qualification journeys, runtime configuration and deployment values.
- **[`governance/gate-hardening.md`](gate-hardening.md)** — the bar a repo's gate must clear before it runs autonomously (a pointer to the §2 spec, not a parallel definition).
- **[`governance/standards/improving-fitness-gates.md`](standards/improving-fitness-gates.md)** — change a shared capability, qualify a coordinated SDLC release and upgrade consumers; the complement to `gate-hardening.md` (the bar).

## 4. Merge governance (the model)

Agents create commits locally with canonical `three-cubes-agent[bot]` metadata and no credential. A trusted host broker performs off-CI remote writes with a repository-scoped, short-lived token for the selected **per-agent App** (`tc-agent-builder`/`shape`/`consultant`/`growth`); Actions uses the WIF-backed composite. Agent harnesses do not receive Key Vault access or tokens, and Actions repository secrets are not a local plaintext retrieval path. The full credential boundary, capability-vs-enforcement model, and App set are the [**Agent SDLC-access + HITL standard**](agent-sdlc-access-and-hitl.md) + [`agent-app-manifests/`](agent-app-manifests/). The merge model:

- **Autonomous on green** for ordinary work — a green gate auto-merges, no human, no admin bypass.
- **HITL only on the control plane** — the gate's own definition (CI, `[tool.tc_fitness]`, schemas, validators, dep pins, governance) needs a human (`@three-cubes/maintainers`) via **CODEOWNERS**, so an agent can never weaken the gate that gates it.
- **De-churned** — no forced up-to-date rebase, no stale-dismiss (see the org rulesets [`governance/rulesets/main-product.json`](rulesets/main-product.json) + [`governance/rulesets/main-core.json`](rulesets/main-core.json) + [`governance/CODEOWNERS`](CODEOWNERS)).
- **Clean authorship is CI-enforced, not convention** (decision D1) — the reusable gates ship a toggleable `no-attribution` leg (`meta-quality-gate.yml`, symmetric in `python-quality-gate.yml`; `run-no-attribution` input, default on) that rejects AI/LLM self-attribution residue in **every PR commit message and the PR title + body**, read-only (CI never rewrites history), via the single shared tc-fitness `no_llm_attribution` detector the local commit-msg strip hook and the fitness gate also use. It publishes the stable required-status-check context **`no-attribution`**; the org rulesets [`governance/rulesets/main-product.json`](rulesets/main-product.json) + [`governance/rulesets/main-core.json`](rulesets/main-core.json) gate `main` on it — the two required contexts are **`Quality gate`** + **`no-attribution`**. Renaming the leg's job means updating that context in lockstep.

This model is **safe only because the gate is hard + fast** (§1–§2). Harden + verify a repo's gate before flipping it to autonomous.

The **failure-driven auto-dispatch loop** that rides this model — its explicit state machine, the deterministic-glue vs judgment split, and the 5 hard guardrails that must be *proven to fire* before any lights-out flag flips — is specified in [`governance/autonomous-loop.md`](autonomous-loop.md) (decision record: [`governance/decisions/ADR-LOOP-STATE-MACHINE.md`](decisions/ADR-LOOP-STATE-MACHINE.md); validation harness: [`governance/loop/`](loop/)). **No auto-dispatch flag flips until that harness is green** (SP-C-1 / PLA-309).

## 5. The inner-loop contract

The stable consumer commands are defined by the AI SDLC product architecture:

1. `make bootstrap` materialises the released environment and lock.
2. `make prepare` completes deterministic generators, formatting, lock and
   manifest maintenance.
3. `make check` executes the affected graph and selected `tc-fitness` profile.
4. `make check-all` executes the complete graph before release admission.

Local and hosted execution record the same SDLC lock, task definitions and input
identities. The canonical Linux image provides release evidence. Native execution
provides the supported platform feedback path.

Reconcile the feature branch with `origin/main`, rerun preparation and the
required graph, then push the tested commit. Required checks admit only a green
result. Generated changes produced by preparation land in the same feature
change as their inputs.

Repositories still on the compatibility path run their documented `make check`
entrypoint. Their migration work is tracked through
[`../docs/MIGRATION.md`](../docs/MIGRATION.md); individual uv, pre-commit and
workflow commands are implementation details of that entrypoint.

## 6. For agents (the anti-reinvention rule)

Before you design a quality gate, a fitness function, a coverage/mutation policy, a CI workflow, or a
governance rule: **it already exists above.** Read it. If it's missing or weak, **propose the change
into the canonical home** (§3) — open a PR to `tc-fitness`/`tc-pipelines` — do not re-create it in a
single repo. The qualification and coordinated release process is in
[`standards/improving-fitness-gates.md`](standards/improving-fitness-gates.md).
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
| SDLC & workflow | [`ai-sdlc-product-architecture.md`](standards/ai-sdlc-product-architecture.md) | Shared environment, task graph, fitness integration, evidence and deployment product. |
| SDLC & workflow | [`development-workflow.md`](standards/development-workflow.md) | Branch, commit, PR and local-first loop conventions. |
| SDLC & workflow | [`testing-strategy.md`](standards/testing-strategy.md) | The test pyramid (contract/integration/E2E) + quality gates. |
| SDLC & workflow | [`validation-and-backpressure.md`](standards/validation-and-backpressure.md) | The syntax→unit→contract→integration→BDD ladder + stop conditions. |
| SDLC & workflow | [`sdlc-release-workflow.md`](standards/sdlc-release-workflow.md) | Trunk-based release: tag from `main`, CHANGELOG-driven notes. |
| SDLC & workflow | [`ci-release-deployment-architecture.md`](standards/ci-release-deployment-architecture.md) | Local evidence, exact-merge validation, toolchain parity, attested candidates, protected publish, deployment handoff and PVT. |
| SDLC & workflow | [`contract-test-patterns.md`](standards/contract-test-patterns.md) | Copy-paste contract-test skeletons (TS + Python) + baseline-shrink. |
| SDLC & workflow | [`process-shared-repo-pr-review-and-merge.md`](standards/process-shared-repo-pr-review-and-merge.md) | Review + merge process for shared repos the author can't self-approve. |
| SDLC & workflow | [`agent-process-controls.md`](standards/agent-process-controls.md) | The control hierarchy for agent-behaviour risks — push high-value risks from guidance up to structural gates. |
| Quality & fitness | [`quality-ratchet.md`](standards/quality-ratchet.md) | Touched-file coverage ratchet — lift without papering. |
| Quality & fitness | [`mutation-testing-survival-ratchet.md`](standards/mutation-testing-survival-ratchet.md) | Diff-scoped mutation + survivors ratchet. |
| Quality & fitness | [`agent-actionable-feedback.md`](standards/agent-actionable-feedback.md) | Every error carries `fix:`/`next:`/`run:`. |
| Quality & fitness | [`improving-fitness-gates.md`](standards/improving-fitness-gates.md) | Qualify shared capability through a coordinated SDLC release. |
| Quality & fitness | [`supply-chain-pinning.md`](standards/supply-chain-pinning.md) | Release catalogue, generated locks, literal GitHub SHAs and coordinated consumer upgrades. |
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
| Deploy & ops | [`infrastructure-deployment-fitness.md`](standards/infrastructure-deployment-fitness.md) | Structured runtime filesystem, access, transaction and evidence contracts. |
| Agent orchestration | [`subagent-orchestration.md`](standards/subagent-orchestration.md) | Single owner, no parallel git ops, no live ops, bounded output. |
| Agent orchestration | [`sub-agent-orchestration-lessons-2026-05-17.md`](standards/sub-agent-orchestration-lessons-2026-05-17.md) | Field lessons that extend the orchestration standard. |
| Agent orchestration | [`parallel-agent-discipline.md`](standards/parallel-agent-discipline.md) | Dispatching parallel streams without collision. |
| MCP tooling | [`mcp-engineering-standard.md`](standards/mcp-engineering-standard.md) | Tool-design contract: structured I/O, validate companions, drop-and-warn. |
| MCP tooling | [`mcp-tooling-canonical-pattern.md`](standards/mcp-tooling-canonical-pattern.md) | MCP server language/layout/helpers/contract-tests. |
| MCP tooling | [`mcp-performance-and-affordance-measurement.md`](standards/mcp-performance-and-affordance-measurement.md) | Perf SLO bands + affordance scoring for a capability. |
