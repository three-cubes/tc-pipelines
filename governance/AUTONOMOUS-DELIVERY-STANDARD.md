# Autonomous Delivery Standard (summary)

> **Canonical, living detail lives in Linear** — initiative **Autonomous Delivery Platform**
> (`https://linear.app/three-cubes/initiative/autonomous-delivery-platform-dae678e12c5d`)
> and its document *"Autonomous Delivery Platform — Target-State Architecture & Program Brief"*.
> This file is the in-repo summary of the paved road every Three Cubes repo rides. Adopted 2026-07-01.

## The one idea
Quality and autonomy improve **by construction**: agents own the inner loop end-to-end against the Linear
roadmap; humans stay as plan-level directors and a **structural approver on the control plane**; every gate
is deterministic and every commit is clean-identity by machine, not by convention.

Two hard-won lessons shape everything below:
1. **Humans move up-and-out, not away.** Per-turn "approve?" prompts fail (measured ~93% blind approval +
   approval fatigue). Agents own execution; humans own the plan + the merge boundary on the control plane.
2. **"Green" ≠ correct.** Agents reward-hack visible tests, so auto-merge-on-green is safe only when green
   means *more than the agent's own suite*: merge-queue re-test + mutation + independent-verifier + honest coverage.

## Locked decisions
- **D1 — no LLM/AI self-attribution** in commits/PRs/code. Enforced (not convention) at three layers: root
  convention → commit-msg strip hook / `safe-commit.sh` → CI reject leg + tc-fitness `no_llm_attribution`.
  All agent commits author as the canonical `three-cubes-agent` GitHub App (see `STANDARDS.md` STD-IDENTITY).
- **D2 — guard forward only.** No git history rewrite; identity remapped via `.mailmap`.
- **D3 — safe lights-out merge.** 0-review auto-merge on **product** repos *via a merge queue* gated on
  the required checks (**`Quality gate`** + **`no-attribution`**) + honest coverage; **n+1 human approval
  on the two CORE repos** (tc-pipelines, tc-fitness); progressive-delivery auto-revert on deploy. Mutation
  + independent-verifier are deferred (not yet required). (See `STANDARDS.md` STD-MERGE, `gate-hardening.md`,
  the org rulesets `rulesets/main-product.json` / `rulesets/main-core.json`, `CODEOWNERS`.)
- **D4 — Linear is the single control surface.** assignee = human (accountable), delegate = agent; no work
  without a work item — traceability is enforced natively by the `org-branch-naming` ruleset (the branch
  embeds the Linear id), not a required status check.
- **Defaults:** loop in committed GitHub-Actions event-dispatch + Stop-hooks (D5); free-first SAST —
  Semgrep OSS + gitleaks, revive CodeQL on public repos (D6); Sigstore/gitsign signing P2 (D7);
  engineering-hub extract-then-remove — its repo is already deleted (D8).

## The paved road (CORE)
- **tc-pipelines** — reusable workflows + composite actions + governance templates + org rulesets.
- **tc-fitness** — the single-binary gate engine (`uv run tc-fitness run` reading each repo's
  `[tool.tc_fitness]`), so `make check == CI` by construction.
- Consumers pin `@v1` / engine `@vX` + lockfile SHA. Org required-workflows + rulesets applied centrally.
  Renovate customManager constrains the engine version (no silent drift). `bootstrap-repo-governance.sh`
  onboards any repo. **Principle: promote prior-work up into CORE, never fork-and-inline.**

## The gate — "green means correct" (blocking on the merge path)
Two required contexts — **`Quality gate`** + **`no-attribution`** — cover: lint/format ·
strict-typing-on-changed · honest coverage (widened scope + carve-outs + monotonic ratchet) ·
architectural fitness that bites (import-linter: layering / banned-import / public-API / no-orphan) ·
secret scan (detect-secrets + gitleaks) · SAST (Semgrep OSS + CodeQL) · determinism (pinned seeds, no
network, **no `--reruns`**) · **identity/attribution gate** (`no_llm_attribution` +
`canonical_commit_identity`). **Mutation blocking-on-diff** and the **independent verifier** (a second
fresh-context agent checks the diff against the work-item's acceptance criteria) are **deferred** — not
required until tc-fitness wires those workflows.

## The eight pillars → the Linear roadmap
autonomy topology · green-means-correct · safe lights-out merge · failure-driven next-action ·
issue-tracker-as-control-surface · identity & provenance · anti-drift / paved-road · measurement.

Sequenced delivery: **SP-A** Identity & Attribution (P0, unblocks all) → **SP-B** Auto-Merge & Merge Queue
∥ **SP-D** Security & Supply-Chain → **SP-C** Failure-Driven Loop → **SP-E** Agent-Affordance + ADR
consolidation → **SP-F** Ops Instrumentation (DORA-for-agents). Two pillars (SP-C, SP-F) are gated behind
validation spikes — their best practice is not yet externally verified; nothing goes lights-out on faith.

## Where the detail lives
- **Work items + acceptance criteria + implementation notes** → the Linear projects under the initiative.
- **Architecture, cited research, ADR reconciliation, prior-work harvest** → the Linear document above.
- **Org ADR register (go-forward)** → `governance/decisions/` (formalizing the decisions embedded in
  `IMPLEMENTATION.md` / `STANDARDS.md` / `gate-hardening.md`); product ADRs stay in-repo with namespaced ids
  (`TAZ-ADR-###`, `KAI-ADR-###`, `KATA-ADR-###`).
