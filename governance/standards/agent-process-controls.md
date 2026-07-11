# Agent-process controls — the hierarchy for agent-behaviour risks

The Golden Path convergence made **code quality** structural: local==CI fitness gates
mean a defect fails a gate, not a reviewer's attention. This standard aims the same
discipline one layer up, at **agent-process quality** — the risks that come from *how*
an autonomous agent works, not from the code it emits.

## The premise

A shared-engine change (tc-fitness v0.13.0) altered a public method's behaviour, shipped
with the full suite green, and broke a consumer a release later — the regression escaped
because the behaviour that changed was never pinned as a test. The guidance to prevent it
(*write tests before the code, not as backfill*) **existed and was not applied.**

The lesson is not "the agent should try harder." It is: **a control you have to remember
to apply is the control that fails under context pressure.** Treat high-value
agent-behaviour risks by moving them *up* the control hierarchy, not by adding more
guidance at the bottom.

## The control hierarchy

| Layer | Control | Reliance on the agent |
|---|---|---|
| **1 · Eliminate** | The wrong thing is impossible (branch protection blocks a merge on red). | none |
| **2 · Detect** | A gate catches it (a fitness check, a consumer canary, mutation). | none |
| **3 · Procedure** | A runbook / Definition of Done the agent must follow. | must follow |
| **4 · Guidance** | SOUL / standards / memory the agent reads and *chooses* to apply. | must remember |

**Rule:** push each high-value agent-behaviour risk as far up this table as it can go.
Do not treat a layer-4 failure with another layer-4 control.

## Risk register + treatment

| Risk (observed behaviour) | Current layer | Structural treatment |
|---|---|---|
| A behaviour change to a **shared contract** with no test pinning it. | 4 (failed) | **tc-fitness**: a contract-change gate + mutation coverage on the shared base — a surviving mutant on the changed branch is a missing test. DoD: red-before-green evidence. |
| An **engine change reaches the fleet** before any consumer validates it. | none | **tc-pipelines**: a pre-release consumer canary — run a consumer's full gate against the *candidate ref* before tag + repin. Blocks the release if the consumer reds. |
| **"Done/green" claimed** without verifying the required checks. | 4 (failed once) | **DoD**: never claim green from "no visible fails"; require the pasted required-check output. Honesty risk — human review is the backstop; instrument the claim-then-corrected rate. |
| **Delegation reproduces the agent's own anti-patterns** (code-first sub-agent specs). | none | **subagent-orchestration**: a test-first spec template — "define the behaviour; write the failing tests; prove they fail on the old behaviour; then implement." |

## The honest limit

Pure judgment and honesty risks — *did I verify, did I claim truthfully, did I read the
guidance* — cannot be fully gated; they live at layer 4 by nature. For those the only real
controls are the tightest procedure (a DoD with pasted evidence), human review as the
backstop, and **measurement**: instrument how often a claim is corrected on review so the
pattern trends and improves, rather than being re-litigated each time. The measurement loop
is the same one that caught the regression (consumer CI → root cause → contract test); the
goal is to make more of it fire *before* release, structurally.

## How a control gets built in

Land each treatment in the canonical home that already owns that surface — never a parallel
mechanism:

- Contract-change + mutation coverage → **tc-fitness** CORE checks.
- Consumer canary → a **tc-pipelines** reusable, wired into
  [`improving-fitness-gates.md`](improving-fitness-gates.md) between "engine PR merged" and
  "tag + repin".
- Test-first + evidence DoD → [`development-workflow.md`](development-workflow.md).
- Test-first sub-agent spec template → the subagent-orchestration standard.

Build every control **test-first** — the treatment for a process failure must itself be
proven to catch that failure (red against the old behaviour) before it is trusted.
