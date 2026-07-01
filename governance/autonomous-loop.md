# The autonomous delivery loop — canonical state-machine spec (SP-C-1)

> Canonical, living spec for the **failure-driven next-action loop** (initiative pillar **SP-C**).
> The **decision record** is [`decisions/ADR-LOOP-STATE-MACHINE.md`](decisions/ADR-LOOP-STATE-MACHINE.md);
> the **machine-checkable gate** is [`loop/`](loop/) (`loop_state_machine.py` + the harness). This
> spec, that ADR, and that harness are one unit — they may not drift. Adopted 2026-07-02 (PLA-309).
>
> **SP-C is gated behind this validation spike:** the loop's best practice is not yet externally
> verified, so **nothing goes lights-out on faith** — the guardrails below must be *proven to fire*
> by the harness before any auto-dispatch flag flips (see "The lights-out gate").

## The state machine

The loop is an explicit finite-state machine. Every transition names its trigger event, whether it is
**deterministic glue** (mechanics, safe to automate, validated by the harness) or **judgment** (an
instantiated agent — the research-unverified surface, fenced by the guardrails), and its guardrail /
terminal stop-condition.

| From | Event (trigger) | To | Kind | Guardrail / counter |
|---|---|---|---|---|
| `ready` | `dispatch` (issue selected → delegate set) | `dispatched` | glue | rate-limit + budget + retry gate (`can_dispatch`) |
| `dispatched` | `pr_opened` (agent opens PR) | `in_review` | glue | — |
| `in_review` | `gate_complete` (CI gate finished) | `verifying` | glue | — |
| `verifying` | `verified_pass` | `done` | **judgment** | only if the run is determinism-admissible |
| `verifying` | `verified_fail` | `needs_fix` | **judgment** | increments the consecutive-failure counter |
| `verifying` | `ambiguous` | `escalated` | **judgment** | GUARDRAIL 4 (do not guess) |
| `needs_fix` | `retry` (re-dispatch fixing agent) | `dispatched` | glue | GUARDRAIL 1 (max-iterations) + 2 (budget) + 5 (rate) |
| *any non-terminal* | `escalate` (a stop-condition tripped) | `escalated` | glue | fail-closed |

`done` and `escalated` are terminal (no further auto-dispatch). The task-level state names map to the
loop stages the initiative uses: `ready`=issue-selected, `dispatched`=agent-dispatched,
`needs_fix`=ci-red→fixing / review-comment→addressing, `verifying`=gate-green→queued,
`done`=merged→advance, `escalated`=escalated.

### Deterministic glue vs judgment (why the split matters)

The glue transitions are pure mechanics and are what may run lights-out. The **judgment** transitions
require an instantiated agent — **readiness/decomposition** (is the item atomic + has real acceptance
criteria, gating entry to `ready`), **spec-conformance** (does the diff meet the acceptance criteria),
and **verification assessment** (is "green" actually correct, or reward-hacked / ambiguous). These are
*not deterministic* and are **outside** what the harness can guarantee; the guardrails bound their
blast radius, they do not make the judgment correct. In the harness the judgment seam is an injected
verdict oracle, so the glue + guardrails are fully tested while judgment stays pluggable.

## The 5 guardrails (spec table)

Encoded as a `tc_fitness`-style table; each row is proven to fire by the harness.

| # | Guardrail | Enforcement | On breach | Harness proof |
|---|---|---|---|---|
| 1 | **Max-iterations / retry ceiling per issue** (`retry_ceiling`, default 3) | count `needs_fix → dispatched` retries | **escalate** to the human-accountable assignee | `RetryCeilingTest` — a synthetic loop that never greens halts at N and escalates |
| 2 | **Cumulative cost + token cap** (`per_issue_budget`; `global_budget` = fleet-wide **circuit-breaker**) | sum spend before each dispatch | per-issue → **escalate that item**; global → **halt all dispatch** | `BudgetCapTest` — per-issue overshoot escalates; global overshoot halts the fleet |
| 3 | **Determinism — no test `--reruns`** (also no network, pinned seed) | `admit_verification` rejects a tainted run | **inadmissible** — can never reach `done`; escalate | `DeterminismTest` — a `--reruns` "pass" can never reach `done` |
| 4 | **Consecutive-failure / ambiguous verification → escalate** | same issue red N times (=guardrail 1); ambiguous verdict | **escalate** (never re-dispatch blindly, never guess) | `RetryCeilingTest` + `AmbiguousVerificationTest` |
| 5 | **Dispatch rate-limit** (`dispatch_rate_max` / window; PLA-241) | sliding-window limiter, shared per actor | **back off + retry** — transient backpressure, *not* a terminal failure | `DispatchRateLimitTest` — blocks at the limit, recovers after the window |

Defaults are conservative starting points — tune per repo + cost model. Guardrails 1–4 are hard
stop-conditions (fail-closed → escalate); guardrail 5 is graceful degradation (Linear's quota is
5,000 req/hr + 3M complexity-pts/hr **shared per user/actor**, so a recursive fan-out must back off
*before* it trips, per PLA-241).

## Enforcement placement — the OpenClaw observer-only-hooks constraint

Under **OpenClaw 2026.5.2, gateway hooks are observer-only — their return values are discarded** — so
a hook cannot *block* an action. Therefore **all hard enforcement is placed at the CI / gate /
merge-queue level** (deterministic, un-bypassable), *not* in gateway hooks. The single exception is
`subagent_spawning`, which uses the **decision-capable** hook and so can fail-closed at the
delegation boundary (SP-C-5). Consequently:

- Guardrails 1–4 live in this loop engine + the CI gate + the merge queue (SP-B), never in an
  observer hook.
- The "no delegation / agent-PR without a linked work item" invariant (SP-C-5) is enforced both by
  the `subagent_spawning` decision hook *and* by a `tc-fitness` `pr_has_linked_work_item` check at
  the merge boundary, because observer hooks cannot block the merge.

## The lights-out gate

**No auto-dispatch flag may flip to enabled until the guardrail harness in [`loop/`](loop/) is
green.** The harness *is* the gate — it simulates the loop and asserts every guardrail above actually
fires. `arm_auto_dispatch()` refuses to arm unless handed proof the guardrails validated.

```sh
python3 -m unittest discover -s governance/loop/tests -v
```

**Research-caveat closed:** each downstream SP-C issue (SP-C-2…SP-C-7 / PLA-310…PLA-315) MUST cite,
in its own description, the specific guardrail row above that was validated by this harness **before**
its lights-out flag is enabled. No SP-C flag flips on faith.

Because `tc-pipelines` is a **CORE** repo, per decision **D3** every change to this spec, the ADR, and
the harness also takes **n+1 human review** before merge. Arming the loop for a given repo further
requires that repo's gate to meet the [Gate-Hardening Standard](gate-hardening.md) (green *and
deterministic*) first.

## Scope of the tc-pipelines deliverable

This repo (CORE) owns the **canonical spec** (this file), the **decision record** (the ADR), and the
**validation harness** (`loop/`). The companion `tc-agent-zone` half — ADR-043 (realising ADR-042)
and the `tests/agentops/` integration harness, plus the `subagent_spawning` decision-hook wiring —
ships in that repo, cross-linked from here.

## References

- [`decisions/ADR-LOOP-STATE-MACHINE.md`](decisions/ADR-LOOP-STATE-MACHINE.md) · [`loop/`](loop/) ·
  [`STANDARDS.md`](STANDARDS.md) §4 · [`AUTONOMOUS-DELIVERY-STANDARD.md`](AUTONOMOUS-DELIVERY-STANDARD.md).
- Linear: Increment 3 (`d4b8c682-a2cf-40e6-be44-86960d1505cd`); PLA-309 (this); PLA-310–315
  (downstream SP-C); PLA-312 (loop governor); PLA-241 (rate-limit backoff / idempotency); SGO-123
  (delegation); ADR-042 / ADR-043 / ADR-038.
