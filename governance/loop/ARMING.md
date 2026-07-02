# ARMING — the runbook for the continuous-dispatch driver

How the autonomous-delivery loop's **continuous-dispatch driver** is armed,
disarmed, and escalated. The driver is
[`loop_runner.py`](loop_runner.py), run on a cadence by
[`.github/workflows/loop-dispatch.yml`](../../.github/workflows/loop-dispatch.yml).
It is the piece that replaces the human hand-cranking the loop: each tick it
self-selects the next READY work item, guardrail-gates it, and — **only when
armed and live** — hands it to an agent-spawn seam.

> **Arming is currently SAFE.** The spawn seam is a
> [`LoggingDispatchSink`](loop_runner.py) — it records the dispatch contract and
> **spawns nothing**. No real `DispatchSink` is wired, so even a fully armed,
> live tick only **logs** the selection. Arming today changes what gets logged,
> not what runs. A real spawn cannot happen until the org picks a runtime and
> wires one of the stub sinks (below). Until then, arming has no blast radius.

This is a **CORE** repo, so per decision **D3** every change here — including
flipping the arming variable's governance — takes **n+1 human review**.

## What "armed" means (and does not)

Two independent gates must BOTH hold before a tick can leave dry-run:

1. **`LOOP_ARMED == "true"`** — a repo variable (the operator's switch).
2. **The guardrail harness self-validates THIS tick** — the runner re-runs the
   proof ([`arm_auto_dispatch`](loop_state_machine.py)) live; a red harness
   `REFUSES` regardless of the variable.

Even with both, the runner reaches only the **`LoggingDispatchSink`**. So today
"armed + live" == "logs the selection it would dispatch, with the governor's
runtime ledger advancing across ticks". There is no path to a real spawn yet.

## PRECONDITIONS — all four before arming for real

Do not set `LOOP_ARMED=true` with intent to dispatch for real until **every** one
of these holds. (Arming while the sink is still `LoggingDispatchSink` is safe and
is a useful shakedown — it exercises selection + gating with zero blast radius.)

| # | Precondition | Evidence |
|---|---|---|
| 1 | **First cycle proven** — the dispatch → verify → close loop has completed at least one end-to-end cycle by hand, with a real merge closed via [`verify-and-close`](verify-and-close.md). | A closed Linear issue with a `verification-confirmed` comment. |
| 2 | **Guardrail harness validated** — `python3 -m unittest discover -s governance/loop/tests` is green (it IS the lights-out gate; `arm_auto_dispatch` refuses without it). | Green harness on `main`; the runner re-confirms it every tick. |
| 3 | **Budget + retry caps configured** — the ceilings below are set deliberately for this fleet + cost model, not left at defaults by accident. | The `GuardrailConfig` in force (see the table); reviewed in the arming PR. |
| 4 | **A real `DispatchSink` chosen + wired** — exactly one of the stub seams is implemented and swapped in for `LoggingDispatchSink`, with its own review + tests. | A merged PR implementing the chosen sink; the CLI/workflow updated to use it. |

Preconditions 1–3 are met today. **Precondition 4 is deliberately NOT met** —
that is why arming is currently safe.

### Choosing the real spawn seam (precondition 4)

Three documented STUB candidates ship in [`loop_runner.py`](loop_runner.py), each
raising `NotImplementedError` with a wiring note. The org picks exactly one:

- **`GitHubActionsHeadlessSink`** — a scheduled/`workflow_dispatch` worker runs
  `claude -p` headless per item; the API key comes from Key Vault (KV+WIF, no
  stored secret). No standing host; inherits Actions concurrency + audit.
- **`AgentPlatformSink`** — hand the contract to the standing
  `tc-agent-zone` / `vm-openclaw` runner (the persistent OpenClaw gateway that
  already enforces the subagent-spawning decision hook and feeds the spend path).
- **`LinearDelegationSink`** — set the Linear `delegate = agent` so Linear's
  native agent integration picks the item up; dispatch becomes one idempotent
  Linear mutation.

## ARM — the exact steps

1. **Validate the harness.** Confirm it is green on `main`:

   ```sh
   python3 -m unittest discover -s governance/loop/tests -v
   ```

2. **Set the arming variable.** Flip the repo variable to exactly `true`:

   ```sh
   gh variable set LOOP_ARMED --repo three-cubes/tc-pipelines --body true
   ```

   Optionally configure the secret-free Linear read (recommended) and the
   source initiative (the runner selects one READY item per tick):

   ```sh
   gh variable set LOOP_LINEAR_KEY_VAULT --repo three-cubes/tc-pipelines --body <kv-name>
   # LOOP_LINEAR_KEY_SECRET_NAME defaults to ci-verify-and-close
   # LOOP_INITIATIVE defaults to the ADP initiative id
   # AZURE_CLIENT_ID / AZURE_TENANT_ID / AZURE_SUBSCRIPTION_ID = the repo WIF identity
   ```

3. **Enable the schedule.** Ensure the
   [`loop-dispatch`](../../.github/workflows/loop-dispatch.yml) workflow is
   enabled (Actions tab → `loop-dispatch` → *Enable workflow* if it was disabled).
   The `*/30` cron then ticks every 30 minutes; each tick runs the runner. While
   the sink is still `LoggingDispatchSink`, armed ticks **log only**.

A scheduled tick goes live only when armed. A **manual** run
(`workflow_dispatch`) stays dry-run unless you also set its `dry_run` input to
`false` — a human must explicitly opt a manual tick into live.

## DISARM / KILL-SWITCH

Any one of these stops the loop; **it takes effect on the next tick**:

- **Set `LOOP_ARMED` to anything but `true`** (the fast kill-switch):

  ```sh
  gh variable set LOOP_ARMED --repo three-cubes/tc-pipelines --body false
  ```

  The next tick sees `armed=false` and reverts to dry-run (record-only).

- **Disable the workflow** (Actions tab → `loop-dispatch` → *Disable workflow*),
  or delete/comment the `schedule:` trigger. No further ticks fire.

**In-flight work.** Today there is nothing in flight to stop: the sink spawns
nothing. **Once a real `DispatchSink` is wired**, disarming stops *new* dispatch
on the next tick; already-spawned agents are not force-killed by the switch —
they either finish their current item or are stopped out-of-band (cancel the
worker run for `GitHubActionsHeadlessSink`; stop the agent on the platform for
`AgentPlatformSink`; un-delegate the Linear issue for `LinearDelegationSink`).
The kill-switch is fail-safe for *dispatch*, not a remote agent-abort — that is
the chosen runtime's responsibility, and the sink's wiring note must document it
before precondition 4 is signed off.

## ESCALATION path

The driver never guesses and never loops forever. A guardrail breach
short-circuits the tick and hands off to a human:

- **Per-item breach** (retry ceiling reached, or per-issue budget cap) — the
  runner **skips** the item this tick and does not dispatch it. The governor's
  [`escalate`](loop_governor.py) opens a **Linear escalation to the
  human-accountable assignee exactly once** (idempotent) via its
  `EscalationSink` (Linear + PushNotification in production) on the verify/close
  side of the loop.
- **Fleet-wide breach** (global budget cap, or the cross-issue circuit-breaker) —
  the runner returns `HALTED` and dispatches nothing fleet-wide; a single
  fleet-level escalation is opened to the human.
- **Ambiguous / non-deterministic verification** — handled on the close side
  ([`verify-and-close`](verify-and-close.md) + the governor's determinism
  admission): a `--reruns` / networked / unpinned-seed "pass" can never close; it
  escalates rather than advancing.

Escalation always terminates at a **human** (assignee), who decides whether to
re-scope, re-dispatch, or drop the item. There is no auto-retry past the ceiling.

## Ceilings in force

The runtime ceilings the governor enforces (the
[`GuardrailConfig`](loop_state_machine.py) defaults — tune per fleet + cost model
in the arming PR, per precondition 3):

| Ceiling | Default | Behaviour on breach |
|---|---|---|
| **Retry ceiling** (per issue) | `retry_ceiling = 3` | escalate the item to the human (no further fix cycle) |
| **Per-issue budget cap** | `per_issue_budget = 5.0` | escalate *that* item |
| **Global budget cap** (fleet circuit-breaker) | `global_budget = 100.0` | **halt all dispatch** fleet-wide |
| **Cross-issue circuit-breaker** | `circuit_breaker_threshold = 5` consecutive cross-issue failures | **halt all dispatch** fleet-wide (systemic red) |
| **Determinism** | `--reruns` / network / unpinned seed all banned | inadmissible — can never close; escalate |
| **Dispatch rate-limit** | `dispatch_rate_max = None` (off) / `window = 3600s` | back off + retry (transient backpressure, not a failure) |

The retry ceiling is what bounds a mis-wired source: even if the backlog snapshot
keeps returning the same item, the governor stops re-dispatching it after
`retry_ceiling` attempts and escalates.

## References

- [`loop_runner.py`](loop_runner.py) · [`loop_governor.py`](loop_governor.py) ·
  [`loop_dispatcher.py`](loop_dispatcher.py) · [`loop_state_machine.py`](loop_state_machine.py)
- [`../autonomous-loop.md`](../autonomous-loop.md) (the canonical spec + the
  lights-out gate) · [`../decisions/ADR-LOOP-STATE-MACHINE.md`](../decisions/ADR-LOOP-STATE-MACHINE.md)
- [`verify-and-close.md`](verify-and-close.md) (the close side + the KV+WIF
  secret-free Linear pattern this driver mirrors)
- Linear: Increment 3 (`d4b8c682-a2cf-40e6-be44-86960d1505cd`); SP-C (PLA-309–315).
