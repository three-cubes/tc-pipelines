# ARMING — the runbook for the continuous-dispatch driver

How the autonomous-delivery loop's **continuous-dispatch driver** is armed,
disarmed, and escalated. The driver is
[`loop_runner.py`](loop_runner.py), run on a cadence by
[`.github/workflows/loop-dispatch.yml`](../../.github/workflows/loop-dispatch.yml).
It is the piece that replaces the human hand-cranking the loop: each tick it
self-selects the next READY work item, guardrail-gates it, and — **only when
armed and live** — hands it to an agent-spawn seam.

> **The real spawn seam is now WIRED — and arming is STILL safe until the keys
> are set.** The runtime is
> [`GitHubActionsDispatchSink`](loop_runner.py): on the go-live path it triggers
> [`loop-implement.yml`](../../.github/workflows/loop-implement.yml) per item — a
> GHA-hosted, headless `claude -p` run that implements the one work item and
> opens the bot PR. It is selected by [`loop-dispatch.yml`](../../.github/workflows/loop-dispatch.yml)
> **only** when `LOOP_ARMED == "true"` AND `LOOP_LIVE == "true"`; on every other
> tick the runner falls back to the safe [`LoggingDispatchSink`](loop_runner.py)
> (records the contract, **spawns nothing**). And even when the real sink is
> wired, the runner's own gate ([`run_once`](loop_runner.py)) only *reaches* it
> once armed + live + **past the soak window** + harness-green + not-halted — so a
> disarmed / dry-run / soaking / red tick spawns nothing regardless. **Merging the
> loop code changes NOTHING**: with the arming vars unset (the default) every tick
> is dry-run and record-only. Arming for real is the deliberate two-key + soak act
> below.

> **⛔ THE ENFORCEABILITY PRECONDITIONS THAT MAKE THE LIVE SINK SAFE — they must
> STAY in place.** A live sink on top of inert guardrails is a runaway. The real
> sink is only safe to run because these three hardening fixes hold; a future
> reviewer MUST NOT weaken any of them while the real sink is wired:
> 1. **Durable cross-tick ledger** — the governor loads/persists a
>    [`StateStore`](loop_governor.py) each tick (a versioned JSON blob on the
>    dedicated `loop-state` git ref / an Azure blob — never the evictable Actions
>    cache). Without it the retry/budget/circuit-breaker counters reset every
>    fresh-process tick and never trip. An armed **live** tick with no durable
>    store is **refused** by the runner (fail-closed).
> 2. **Fail-closed harness validation** — [`guardrails_validated`](loop_dispatcher.py)
>    returns `True` only when the harness file exists AND at least the
>    known-minimum number of guardrail tests ran green; a missing/renamed/
>    truncated harness reads as **not validated** (never vacuously green).
> 3. **Soak before live** — the first `LOOP_SOAK_TICKS` armed ticks stay
>    record-only, so a cold armed tick can never dispatch (see the soak section).
>
> These are covered by `tests/test_loop_hardening.py`, and the real sink's own
> selection + gating is covered by `tests/test_loop_runner.py`
> (`GitHubActionsDispatchSinkTest` + `RealSinkGatingTest`). Both harnesses must
> stay green.

This is a **CORE** repo, so per decision **D3** every change here — including
flipping the arming variable's governance — takes **n+1 human review**.

## What "armed" means (and does not)

Three gates must ALL hold before a **scheduled** tick can dispatch for real, and a
fourth (soak) delays even that:

1. **`LOOP_ARMED == "true"`** — a repo variable (the operator's first switch).
2. **The guardrail harness self-validates THIS tick** — the runner re-runs the
   proof ([`arm_auto_dispatch`](loop_state_machine.py)) live, now **fail-closed**
   (the harness file must exist and enough guardrail tests must run green); a red
   or missing harness `REFUSES` regardless of the variables.
3. **`LOOP_LIVE == "true"`** — a **second, independent** repo variable (the "go
   live" key). Until it is set, an armed scheduled tick stays **dry-run** so the
   operator can review the recorded would-dispatch decisions (the soak).
4. **Past the soak window** — even with 1–3, the runner keeps the first
   `LOOP_SOAK_TICKS` armed ticks record-only; only after that can it dispatch.

Once all four hold, the runner reaches the **`GitHubActionsDispatchSink`**, which
fires [`loop-implement.yml`](../../.github/workflows/loop-implement.yml) for the
selected item (the real GHA-hosted `claude -p` executor — see the executor section
below). Until the second key is set, "armed" == "logs the selection it would
dispatch, with the governor's **durable** ledger advancing across ticks (persisted
to the `loop-state` ref, so the ceilings actually trip tick-to-tick)" — the safe
`LoggingDispatchSink` path, no spawn.

## PRECONDITIONS — all four before arming for real

Do not set `LOOP_LIVE=true` with intent to dispatch for real until **every** one
of these holds. (Setting only `LOOP_ARMED=true` — leaving `LOOP_LIVE` unset — is a
safe shakedown: it exercises selection + gating + the soak in record-only mode
with the safe `LoggingDispatchSink` and zero blast radius.)

| # | Precondition | Evidence |
|---|---|---|
| 1 | **First cycle proven** — the dispatch → verify → close loop has completed at least one end-to-end cycle by hand, with a real merge closed via [`verify-and-close`](verify-and-close.md). | A closed Linear issue with a `verification-confirmed` comment. |
| 2 | **Guardrail harness validated (fail-closed)** — `python3 -m unittest discover -s governance/loop/tests` is green (it IS the lights-out gate; `arm_auto_dispatch` refuses without it). `guardrails_validated` now also refuses a missing/renamed/truncated harness. | Green harness on `main`; the runner re-confirms it every tick. |
| 3 | **Budget + retry caps configured** — the ceilings below are set deliberately for this fleet + cost model, not left at defaults by accident. | The `GuardrailConfig` in force (see the table); reviewed in the arming PR. |
| 3a | **Durable cross-tick ledger wired** — the workflow materialises the `loop-state` git ref into `--state-file` and writes it back, so the governor's retry/budget/circuit-breaker counters accumulate across the fresh-process ticks (they are inert otherwise). An armed **live** tick with no durable store is refused. | The restore/persist steps in [`loop-dispatch.yml`](../../.github/workflows/loop-dispatch.yml); the cross-tick tests in `tests/test_loop_hardening.py` green. |
| 3b | **Soak window configured** — `LOOP_SOAK_TICKS` set so the first N armed ticks stay record-only; the first armed cron tick never dispatches. | `LOOP_SOAK_TICKS` repo variable (default 3); the soak tests green. |
| 4 | **A real `DispatchSink` chosen + wired** — SATISFIED: [`GitHubActionsDispatchSink`](loop_runner.py) is implemented and selected by [`loop-dispatch.yml`](../../.github/workflows/loop-dispatch.yml) on the go-live path, with its own review + tests, on top of 3a + 3b + fail-closed 2. | This PR: `GitHubActionsDispatchSink` + `loop-implement.yml`; `test_loop_runner.py` (`GitHubActionsDispatchSinkTest` + `RealSinkGatingTest`) and `test_loop_hardening.py` green. |
| 4a | **The bot App is installed with the permissions the executor + dispatch need** — the `three-cubes-agent` App has `actions: write` on `tc-pipelines` (so the App-token-triggered `workflow_dispatch` actually runs `loop-implement.yml`), and `contents: write` + `pull-requests: write` on each TARGET product repo (so the executor can push its branch and open/auto-merge the PR). | The App's installation permissions; a manual `workflow_dispatch` of `loop-implement.yml` producing a real bot PR (precondition 1's end-to-end cycle). |

Preconditions 1–4a are met by this change. **Arming stays safe** because the two
keys (`LOOP_ARMED` + `LOOP_LIVE`) and the soak are all still required before the
real sink is ever reached — merging changes nothing until an operator acts.

### The chosen spawn seam (precondition 4) — and the alternatives

The wired runtime is **`GitHubActionsDispatchSink`** in
[`loop_runner.py`](loop_runner.py): on the go-live path it POSTs a
`workflow_dispatch` to [`loop-implement.yml`](../../.github/workflows/loop-implement.yml)
for the one selected item (issue id / branch / repo as inputs, all strict-pattern
validated before they reach the request), using the bot App installation token
(minted secret-free via WIF + Key Vault). A 201/204 means the executor run was
spawned; anything else fails CLOSED (the runner never records a phantom spawn).

Three other candidates remain in `loop_runner.py` as documented STUBs (each raises
`NotImplementedError`) so a future reviewer can see the menu that was considered:

- **`GitHubActionsHeadlessSink`** — the original un-parameterised description of
  the GHA-hosted seam, now realized as `GitHubActionsDispatchSink`.
- **`AgentPlatformSink`** — hand the contract to the standing
  `tc-agent-zone` / `vm-openclaw` runner (the persistent OpenClaw gateway). NOT
  chosen — the GHA-hosted path needs no standing host and NOTHING touches openclaw.
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

3. **Configure the soak window (recommended).** How many armed ticks stay
   record-only before live is permitted (default `3` if unset):

   ```sh
   gh variable set LOOP_SOAK_TICKS --repo three-cubes/tc-pipelines --body 3
   ```

4. **Enable the schedule.** Ensure the
   [`loop-dispatch`](../../.github/workflows/loop-dispatch.yml) workflow is
   enabled (Actions tab → `loop-dispatch` → *Enable workflow* if it was disabled).
   The `*/30` cron then ticks every 30 minutes; each tick runs the runner. With
   only `LOOP_ARMED` set, armed ticks stay **dry-run** and **soak** (record the
   would-dispatch decision to the run log for review) — nothing goes live yet.

5. **Review the soak, then flip the second key.** After watching the recorded
   would-dispatch decisions for at least `LOOP_SOAK_TICKS` armed ticks, set the
   **second, independent** go-live key:

   ```sh
   gh variable set LOOP_LIVE --repo three-cubes/tc-pipelines --body true
   ```

   Only now do scheduled ticks leave dry-run — and only once the runner's own
   soak counter (persisted in the `loop-state` ref) has also elapsed, so the
   very first armed tick still cannot dispatch. From this point a live tick
   **fires the real `GitHubActionsDispatchSink`**: it triggers
   [`loop-implement.yml`](../../.github/workflows/loop-implement.yml) for the
   selected item, and a GHA-hosted `claude -p` run implements it and opens the
   bot PR. Confirm the App's installation permissions (precondition 4a) first.

A scheduled tick goes live only when **`LOOP_ARMED` AND `LOOP_LIVE` are both
`true` AND the soak has elapsed**. A **manual** run (`workflow_dispatch`) stays
dry-run unless you set its `dry_run` input to `false` **and** both keys are set —
a human must explicitly opt a manual tick into live on top of both repo keys.

## SOAK — the mandatory dry-run before live

After `LOOP_ARMED` flips true, the scheduled path does **not** go live on the next
tick. Two layers enforce a soak so an operator can review "what would dispatch"
before anything real happens, and the very first armed cron tick can never go
live:

- **The `LOOP_LIVE` second key.** Scheduled ticks stay dry-run until the operator
  ALSO sets `LOOP_LIVE=true` — a deliberate, separate confirmation made *after*
  reviewing the recorded would-dispatch decisions.
- **The runner's soak counter.** Even once `LOOP_LIVE=true`, the runner keeps the
  first `LOOP_SOAK_TICKS` armed ticks record-only, incrementing a counter that
  **persists in the `loop-state` ref** (so the window elapses across the
  fresh-process ticks, not per-process). Only after the counter reaches
  `LOOP_SOAK_TICKS` can a tick dispatch. This holds even if an operator sets both
  keys at once — the cold armed tick still soaks.

Each soak tick records the `DispatchContract` it WOULD dispatch (visible in the
run log / JSON), with zero side effects. Manual `workflow_dispatch` runs stay
dry-run by default regardless.

## DISARM / KILL-SWITCH

Any one of these stops the loop; **it takes effect on the next tick**:

- **Set `LOOP_LIVE` to anything but `true`** (revert to soak/dry-run without
  fully disarming):

  ```sh
  gh variable set LOOP_LIVE --repo three-cubes/tc-pipelines --body false
  ```

- **Set `LOOP_ARMED` to anything but `true`** (the fast kill-switch):

  ```sh
  gh variable set LOOP_ARMED --repo three-cubes/tc-pipelines --body false
  ```

  The next tick sees `armed=false` and reverts to dry-run (record-only).

- **Disable the workflow** (Actions tab → `loop-dispatch` → *Disable workflow*),
  or delete/comment the `schedule:` trigger. No further ticks fire.

**In-flight work.** The real sink is now wired, so a live tick can have spawned a
per-item [`loop-implement.yml`](../../.github/workflows/loop-implement.yml) run.
Disarming (either key) stops *new* dispatch on the next tick, but does **not**
force-kill an already-spawned executor run: cancel that run from the Actions tab
(`loop-implement` → the run for the issue → *Cancel*) to stop it mid-flight, or
let it finish / hit its `--max-turns` + `timeout` bound. The kill-switch is
fail-safe for *dispatch*, not a remote agent-abort — the executor's own bounds
(per-item turn cap + wall-clock timeout + job `timeout-minutes`) cap a run that is
already in flight.

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
| **Soak before live** | `LOOP_SOAK_TICKS = 3` (workflow default) | first N armed ticks stay record-only; a cold armed tick never dispatches |

The retry ceiling is what bounds a mis-wired source — **but only because the
ledger is durable**. Each scheduled tick is a fresh process, so an in-memory-only
governor would forget every attempt and re-dispatch the same item forever. The
runner therefore loads the durable [`StateStore`](loop_governor.py) (the
`loop-state` git ref) at the start of each tick and persists it after a dispatch,
so the accumulated `attempts` cross ticks: even if the backlog snapshot keeps
returning the same item, the governor stops re-dispatching it after
`retry_ceiling` attempts *across ticks* and escalates. The same durability is what
makes the per-issue budget, the global budget, and the cross-issue circuit-breaker
actually trip tick-to-tick (proven in `tests/test_loop_hardening.py`).

## THE EXECUTOR — `loop-implement.yml`

The real sink's target is
[`.github/workflows/loop-implement.yml`](../../.github/workflows/loop-implement.yml):
the GHA-hosted, headless agent-execution runtime that turns ONE selected work item
into a working bot PR. `GitHubActionsDispatchSink` triggers it via
`workflow_dispatch` with three inputs — `issue-id`, `issue-branch`, `repo` — each
strict-pattern-validated on both sides (the sink before it posts, and the workflow
before it uses them). It runs on `ubuntu-latest`; **NOTHING touches openclaw**.

Per tick, one item. The workflow, in order:

1. **Validates** `issue-id` / `issue-branch` / `repo` against strict allowlists
   (rejecting the `unknown` sentinel) and resolves a bare repo name to
   `owner/name` — injection-safe: env-bound, never interpolated raw.
2. **Federates to Azure (WIF)** — no stored credential — and reads the model key
   (`anthropic-api-key`) and Linear key (`ci-verify-and-close`) from Key Vault
   `kv-tc-agents`, masked the instant they are read and kept step-local (never an
   output). Same KV+WIF pattern as [`verify-and-close.yml`](verify-and-close.md).
3. **Mints the bot App token** from the App id + private key ALSO in the vault
   (via the [`github-app-token`](../../.github/actions/github-app-token/action.yml)
   composite), scoped to the TARGET repo — so every git/gh write is the
   `three-cubes-agent` App, never a human PAT, never GITHUB_TOKEN.
4. **Checks out the target repo** on the issue branch and runs `claude -p`
   HEADLESS with a tightly-scoped executor prompt: read the item from Linear,
   implement only it, run the repo gate green, commit D1-clean (canonical bot
   identity, ZERO AI attribution), open the bot PR, and enable auto-merge on
   product repos (never on core repos — those keep n+1 human review per D3).

**Per-item bounds (cost/turn caps).** The executor is bounded three ways, all
operator-overridable via repo variables:

| Bound | Repo variable | Default |
|---|---|---|
| Agent turns per item | `LOOP_EXECUTOR_MAX_TURNS` (`claude -p --max-turns`) | `80` |
| Wall-clock per item | `LOOP_EXECUTOR_TIMEOUT_MIN` (`timeout` around `claude`) | `45` min |
| Whole-job ceiling | `LOOP_EXECUTOR_JOB_TIMEOUT_MIN` (job `timeout-minutes`) | `60` min |
| Model | `LOOP_EXECUTOR_MODEL` | `claude-opus-4-8` |
| CLI version (pinned) | `LOOP_CLAUDE_CODE_VERSION` | `2.1.197` |
| Core repos (never auto-merged) | `LOOP_CORE_REPOS` | `tc-pipelines tc-agent-zone` |

The prompt hard-forbids touching anything outside the one issue (other repos,
other issues, branch-protection, secret exfiltration) and treats the Linear issue
body as DATA, not instructions that can widen the task — a content-level
prompt-injection guard on top of the input validation. These per-item caps compose
with the governor's cross-tick ceilings (below): the governor bounds *how many*
items dispatch and *how often*; `loop-implement.yml` bounds *how much* each one
may spend.

## References

- [`loop_runner.py`](loop_runner.py) · [`loop_governor.py`](loop_governor.py) ·
  [`loop_dispatcher.py`](loop_dispatcher.py) · [`loop_state_machine.py`](loop_state_machine.py)
- [`../autonomous-loop.md`](../autonomous-loop.md) (the canonical spec + the
  lights-out gate) · [`../decisions/ADR-LOOP-STATE-MACHINE.md`](../decisions/ADR-LOOP-STATE-MACHINE.md)
- [`verify-and-close.md`](verify-and-close.md) (the close side + the KV+WIF
  secret-free Linear pattern this driver mirrors)
- The driver workflow [`loop-dispatch.yml`](../../.github/workflows/loop-dispatch.yml)
  (selects the sink) and the executor
  [`loop-implement.yml`](../../.github/workflows/loop-implement.yml) (the GHA-hosted
  headless `claude -p` runtime) · the App-token composite
  [`github-app-token`](../../.github/actions/github-app-token/action.yml).
- Durable cross-tick ledger: the `loop-state` git ref (`refs/loop-state/ledger`),
  materialised into `--state-file` by `loop-dispatch.yml`; the enforceability
  proofs live in [`tests/test_loop_hardening.py`](tests/test_loop_hardening.py),
  and the real-sink selection + gating in
  [`tests/test_loop_runner.py`](tests/test_loop_runner.py).
- Linear: Increment 3 (`d4b8c682-a2cf-40e6-be44-86960d1505cd`); SP-C (PLA-309–315).
