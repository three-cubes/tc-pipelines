# ADR-LOOP-STATE-MACHINE — the autonomous delivery loop state machine + guardrails

- **Status:** Accepted (validation-spike gate; SP-C-1)
- **Date:** 2026-07-02
- **Deciders:** Autonomous Delivery Platform program (owner: Dan McMahon)
- **Scope:** the failure-driven auto-dispatch loop (initiative pillar **SP-C — Failure-Driven
  Loop**). CORE repos (`tc-pipelines`, `tc-fitness`) — changes here need **n+1 human review** (D3).
- **Work item:** **PLA-309** (SP-C-1). **Related:** Increment 3 — *Shape-as-orchestrator + enforcing
  hooks* (`d4b8c682-a2cf-40e6-be44-86960d1505cd`); loop governor **PLA-312** (SP-C-4); downstream
  loop steps **PLA-310/311/313/314/315**; delegation model **SGO-123**; agent-hardening **PLA-241**
  (rate-limit backoff · idempotency · delegate-not-assignee); binding + harvest-decay **PLA-242**;
  ADR-042 (Shape-as-orchestrator / hooks-as-invariants), ADR-043 (native interaction model /
  `actor=app` / delegate-not-assignee), ADR-038 (harvest-then-decay).
- **Canonical spec (this decision's living detail):**
  [`governance/autonomous-loop.md`](../autonomous-loop.md) — the state-machine + 5-guardrail spec
  table. **Harness (this ADR's gate):** [`governance/loop/`](../loop/) — `loop_state_machine.py` +
  `tests/test_loop_guardrails.py`. Spec, ADR, and harness are one unit and may not drift.

---

## Context

The initiative's locked decisions (`governance/AUTONOMOUS-DELIVERY-STANDARD.md`) say agents own the
**inner loop** end-to-end against the Linear roadmap, and Increment 3 runs
`specify → decompose → delegate → update → harvest → close` recursively with **no per-turn human
approval gate**. Two hard-won lessons bound this:

1. **Per-turn "approve?" fails** — measured ~93% blind approval + approval fatigue. So the loop must
   be able to run without a human in each turn.
2. **"Green" ≠ correct** — frontier agents reward-hack visible tests, and *more iteration amplifies
   it*. A naive "retry until the suite is green, then merge" loop is exactly the failure mode: it
   rewards flakiness-masking and reward-hacking.

The program is explicit that **SP-C is gated behind a validation spike — its best practice is not
yet externally verified; nothing goes lights-out on faith.** The loop mechanics below are therefore
treated as **research-UNVERIFIED** until the guardrail harness proves each stop-condition fires.

This ADR pins the explicit state machine, separates the **deterministic glue** (safe to automate,
and machine-validated by the harness) from the **judgment** transitions (an instantiated agent, not
deterministic, and outside what the harness can guarantee), and enumerates the **hard
stop-conditions** that must fire before any auto-dispatch flag flips.

---

## Decision

### 1. The states

| State | Meaning | Terminal? |
|---|---|---|
| `ready` | A Linear work item exists (D4: no work without a work item), has acceptance criteria, is decomposed to one atomic dispatchable unit, and budget is available. | no (entry) |
| `dispatched` | An agent has been delegated the item (`delegate`, **not** `assignee` — ADR-043 / PLA-241) and is executing on its branch. | no |
| `in_review` | The agent opened a PR; the CI gate is running. | no |
| `verifying` | The deterministic gate finished **and** an independent fresh-context verifier is assessing the diff against the item's acceptance criteria. | no |
| `done` | Verified correct and merged. | **yes** |
| `needs_fix` | Verification found a defect, or the gate is red. Loops back to `dispatched` iff under the retry ceiling **and** budget; otherwise escalates. | no |
| `escalated` | Handed to a human. The loop performs **no further auto-dispatch** for this item. | **yes (to the loop)** |

### 2. The events / transitions

```
ready       --dispatch-------> dispatched      (glue, gated by can_dispatch guardrails)
dispatched  --pr_opened------> in_review       (glue: PR/webhook event)
in_review   --gate_complete--> verifying       (glue: CI gate finished)
verifying   --verified_pass--> done            (JUDGMENT: verification assessment)
verifying   --verified_fail--> needs_fix       (JUDGMENT: verification assessment)
needs_fix   --retry----------> dispatched      (glue, gated by retry ceiling + budget)
<any non-terminal> --escalate-> escalated       (glue: a stop-condition tripped)
```

Any event not in this table is an **illegal transition** and is rejected (fail-closed) — the harness
asserts this.

### 3. Deterministic glue vs judgment (the load-bearing split)

**Deterministic glue** — pure mechanics / event-driven, no model in the loop. These are what the
guardrail harness validates and what may run lights-out:

- `ready → dispatched` (create branch, set Linear `delegate`, idempotency key per PLA-241) — the
  *mechanics* once readiness is asserted.
- `dispatched → in_review` (PR-opened event).
- `in_review → verifying` (CI-gate-complete event).
- `needs_fix → dispatched` (the retry — counter increment, gated by the stop-conditions).
- `* → escalated` (a stop-condition firing on a **measured** value).

**Judgment** — requires an instantiated agent; **not deterministic**; explicitly **outside** the
guarantees this harness can give (this is the research-unverified surface, so it is fenced by the
stop-conditions, never trusted on faith):

- **Readiness / decomposition assessment** — *is the item atomic, with real acceptance criteria, and
  actually ready to dispatch?* Gates entry to `ready`.
- **Spec-conformance review** — *does the diff satisfy the work item's acceptance criteria?* The
  independent fresh-context verifier at `in_review → verifying`.
- **Verification assessment** — *is "green" actually correct (not reward-hacked), and is the verdict
  unambiguous?* Emits `verified_pass` / `verified_fail`, or **`ambiguous` ⇒ escalate**.

In the harness the judgment seam is an **injected callable** (a verdict oracle), so the deterministic
glue and guardrails are fully tested while judgment stays a pluggable, un-guaranteed input — mirroring
production, where that seam is an agent.

### 4. Hard STOP-CONDITIONS (each must be proven by the harness)

1. **N-retry ceiling.** After `retry_ceiling` fix cycles on one item, the loop **halts and
   escalates** — it never loops forever. (Default `N = 3`.)
2. **Per-issue budget cap.** Cumulative cost (tokens/$/wall-time) per work item ≤ cap. Projected
   overshoot **stops dispatch and escalates that item** (it is too expensive for the loop).
3. **Global budget cap (circuit breaker).** Sum across all in-flight items ≤ global cap. Overshoot
   **halts all new dispatch fleet-wide** — a runaway recursive fan-out cannot burn the budget.
4. **Determinism.** Verification in the loop must be deterministic: **no test `--reruns`** (retry-
   until-green masks flakiness and launders reward-hacking), pinned seeds, no network. A verification
   run that used `--reruns` (or network, or an unpinned seed) is **inadmissible**: it can *never*
   advance `verifying → done`; it escalates instead. This is the concrete "green means correct"
   guard.
5. **Ambiguous verification ⇒ escalate.** If the verifier cannot render a confident pass/fail
   (under-specified acceptance criteria, verifier disagreement), the loop **does not guess** — it
   escalates to a human.
6. **Repeated failure ⇒ escalate.** Recurring failure on the same item escalates (subsumed by the
   retry ceiling; called out so it is not "fixed" by raising N).
7. **Dispatch rate-limit ⇒ back off (not fail).** A sliding-window limiter caps dispatches per actor
   so a recursive fan-out degrades gracefully *before* it trips Linear's shared quota (5,000 req/hr +
   3M complexity-pts/hr per actor — PLA-241). Unlike 1–6 this is **transient backpressure**: the item
   is *not* escalated, the caller backs off and retries.

These map onto the canonical spec's **5 guardrails** (`governance/autonomous-loop.md`): (1)
max-iterations, (2) cost/budget cap incl. the global circuit-breaker, (3) determinism / no-`--reruns`,
(4) consecutive-failure + ambiguous ⇒ escalate, (5) dispatch rate-limit.

Escalation is **fail-closed**: on any of guardrails 1–6 the item moves to `escalated` (or, for the
global breaker, the fleet halts) and the loop stops auto-dispatching it.

### Enforcement placement (OpenClaw observer-only-hooks constraint)

Under **OpenClaw 2026.5.2 gateway hooks are observer-only — return values are discarded** — so a hook
cannot *block*. Therefore **all hard enforcement (guardrails 1–4) is placed at the CI / gate /
merge-queue level**, deterministic and un-bypassable, never in an observer hook. The one exception is
`subagent_spawning`, which uses the **decision-capable** hook and so can fail-closed at the delegation
boundary (SP-C-5); the "no work without a linked work item" invariant is *also* enforced by a
`tc-fitness` check at the merge boundary because observer hooks cannot block a merge.

---

## The lights-out gate (non-negotiable)

> **No auto-dispatch flag may flip to enabled until the guardrail harness in
> [`governance/loop/`](../loop/) is green.** The harness *is* the gate: it simulates the loop and
> asserts every stop-condition above actually fires. `arm_auto_dispatch()` refuses to arm unless it
> is handed proof the guardrails validated (`guardrails_validated=True`), which is only true when
> `python3 -m unittest discover -s governance/loop/tests` passes.

Run it:

```sh
python3 -m unittest discover -s governance/loop/tests -v
```

**Research-caveat closed.** SP-C is gated behind this validation spike. Each downstream SP-C issue
(SP-C-2…SP-C-7 / PLA-310…PLA-315) MUST cite, in its own description, the specific guardrail this
harness validated **before** its lights-out flag is enabled — nothing flips on faith.

This is a CORE repo, so per **D3** every change here (this ADR, the canonical spec, and the harness)
also takes **n+1 human review** before it can merge — the structural human boundary on the control
plane. Arming the loop for any repo additionally requires that repo's gate to meet the
[Gate-Hardening Standard](../gate-hardening.md) (green *and deterministic*) first.

---

## Consequences

- **Positive.** The loop can run lights-out on the inner cycle without per-turn approval, while every
  runaway mode (infinite retry, budget burn, flaky/reward-hacked "green", ambiguous verdicts) is
  bounded by a **deterministic** guardrail that is proven to fire before the flag can flip. The
  glue/judgment split makes explicit which parts are trustworthy mechanics and which are the
  un-guaranteed agent judgment fenced by the stop-conditions.
- **Negative / cost.** Judgment transitions remain unverified research: the guardrails *bound* their
  blast radius, they do not make the judgment correct. Escalation-to-human is load-bearing and must
  be staffed. Budget/ceiling defaults need tuning per repo and per cost model.
- **Follow-ups.** Wire the harness into CI as a required check for any repo that flips auto-dispatch;
  emit the loop's escalations/costs into SP-F (Ops Instrumentation / DORA-for-agents); bind the
  `delegate` + idempotency mechanics to the delivery-management server (PLA-241) and the
  harvest-then-decay record on `close` (PLA-242 / ADR-038).

## References

- `governance/AUTONOMOUS-DELIVERY-STANDARD.md` — locked decisions D1–D8, the "green means correct"
  gate, the SP-A…SP-F sequence (SP-C gated behind this validation spike).
- Increment 3 project `d4b8c682-a2cf-40e6-be44-86960d1505cd`; delegation SGO-123; PLA-241; PLA-242.
- ADR-042 (Shape-as-orchestrator / hooks-as-invariants), ADR-043 (`actor=app` / delegate-not-
  assignee), ADR-038 (harvest-then-decay).
