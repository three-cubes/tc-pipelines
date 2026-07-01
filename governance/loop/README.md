# governance/loop/ — the autonomous-delivery loop guardrail harness (SP-C-1)

The machine-checkable half of the canonical spec
[`../autonomous-loop.md`](../autonomous-loop.md) and its decision record
[`../decisions/ADR-LOOP-STATE-MACHINE.md`](../decisions/ADR-LOOP-STATE-MACHINE.md).

- [`loop_state_machine.py`](loop_state_machine.py) — the explicit loop state machine
  (`ready → dispatched → in_review → verifying → done | needs_fix → escalated`) as a
  **deterministic** transition table, plus the guardrail engine that enforces the hard
  stop-conditions. The **judgment** transitions (spec-conformance / verification assessment) are an
  *injected* verdict seam, so the deterministic glue + guardrails are fully testable while the
  un-guaranteed agent judgment stays pluggable.
- [`tests/test_loop_guardrails.py`](tests/test_loop_guardrails.py) — the harness. It **simulates the
  loop and asserts each of the 5 guardrails fires**: (1) the N-retry ceiling halts + escalates; (2)
  the per-issue budget cap and global circuit-breaker stop dispatch; (3) determinism is enforced (a
  `--reruns` / networked / unpinned-seed "pass" can never reach `done`); (4) ambiguous /
  consecutive-failure verification escalates; (5) the dispatch rate-limit backs off and recovers
  (transient backpressure, not a terminal failure).

## The lights-out gate

**No auto-dispatch flag may flip to enabled until this harness is green.** `arm_auto_dispatch`
refuses to arm unless handed proof the guardrails validated — see the ADR. This is a CORE repo, so
per decision **D3** these files also take **n+1 human review** before merge.

## Run

```sh
python3 -m unittest discover -s governance/loop/tests -v
```

Stdlib only — no dependencies, no network (the transport + judgment seams are injected fakes),
matching the determinism the loop itself enforces.
