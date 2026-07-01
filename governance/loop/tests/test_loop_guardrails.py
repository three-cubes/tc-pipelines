"""Guardrail-validation harness for the autonomous-delivery loop (SP-C-1).

This IS the lights-out gate for ADR-LOOP-STATE-MACHINE: it simulates the loop and
asserts every hard STOP-CONDITION actually FIRES. No auto-dispatch flag may flip
until this is green.

Run (stdlib only, no deps, no network — the transport/judgment seams are injected):

    python3 -m unittest discover -s governance/loop/tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import loop_state_machine as loop  # noqa: E402 — path shim above
from loop_state_machine import (  # noqa: E402
    AmbiguousVerification,
    BudgetExceeded,
    DeterminismViolation,
    DispatchRateLimited,
    Event,
    GuardrailConfig,
    GuardrailTripped,
    IllegalTransition,
    LoopEngine,
    RetryCeilingExceeded,
    State,
    Verdict,
    VerificationRun,
    WorkItem,
    run_item,
)


class FakeClock:
    """A deterministic, injectable monotonic clock for the rate-limit tests."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _clean_pass(**kw) -> VerificationRun:
    return VerificationRun(verdict=Verdict.PASS, **kw)


def _clean_fail(**kw) -> VerificationRun:
    return VerificationRun(verdict=Verdict.FAIL, **kw)


def _to_verifying(engine: LoopEngine, item: WorkItem, cost: float = 1.0) -> None:
    """Drive a dispatchable item through the deterministic glue to ``verifying``."""
    engine.dispatch(item, cost=cost)
    engine.open_pr(item)
    engine.gate_complete(item)


def _fail_cycle(engine: LoopEngine, item: WorkItem, cost: float = 1.0) -> None:
    """One full loop cycle ending in ``needs_fix`` (dispatch → PR → gate → FAIL)."""
    _to_verifying(engine, item, cost=cost)
    engine.record_verification(item, _clean_fail())


# --------------------------------------------------------------------------- #
# Deterministic glue: the happy path + illegal transitions fail closed
# --------------------------------------------------------------------------- #
class GlueTransitionTest(unittest.TestCase):
    def test_happy_path_reaches_done(self):
        engine = LoopEngine()
        item = WorkItem(id="PLA-999")
        _to_verifying(engine, item)
        self.assertEqual(item.state, State.VERIFYING)
        engine.record_verification(item, _clean_pass())
        self.assertEqual(item.state, State.DONE)

    def test_full_transition_sequence_recorded(self):
        engine = LoopEngine()
        item = WorkItem(id="PLA-1")
        _to_verifying(engine, item)
        engine.record_verification(item, _clean_pass())
        events = [ev for _, ev, _ in item.history]
        self.assertEqual(
            events,
            [Event.DISPATCH, Event.PR_OPENED, Event.GATE_COMPLETE, Event.VERIFIED_PASS],
        )

    def test_pr_opened_illegal_from_ready(self):
        engine = LoopEngine()
        item = WorkItem(id="PLA-2")
        with self.assertRaises(IllegalTransition):
            engine.open_pr(item)

    def test_cannot_dispatch_terminal_item(self):
        engine = LoopEngine()
        item = WorkItem(id="PLA-3")
        _to_verifying(engine, item)
        engine.record_verification(item, _clean_pass())  # -> DONE
        with self.assertRaises(IllegalTransition):
            engine.dispatch(item)

    def test_verification_only_from_verifying(self):
        engine = LoopEngine()
        item = WorkItem(id="PLA-4")  # still READY
        with self.assertRaises(IllegalTransition):
            engine.record_verification(item, _clean_pass())

    def test_judgment_events_are_the_verifier_verdicts(self):
        # The split the ADR draws: only the verdict transitions are judgment.
        self.assertEqual(
            loop.JUDGMENT_EVENTS, frozenset({Event.VERIFIED_PASS, Event.VERIFIED_FAIL})
        )
        self.assertEqual(loop.TERMINAL, frozenset({State.DONE, State.ESCALATED}))


# --------------------------------------------------------------------------- #
# STOP-CONDITION 1 — N-retry ceiling halts + escalates
# --------------------------------------------------------------------------- #
class RetryCeilingTest(unittest.TestCase):
    def test_retry_ceiling_halts_after_n_and_escalates(self):
        engine = LoopEngine(GuardrailConfig(retry_ceiling=3, per_issue_budget=1e9))
        item = WorkItem(id="PLA-10")
        # An agent that never fixes the defect — the loop MUST NOT spin forever.
        final = run_item(engine, item, lambda _i: _clean_fail(), max_cycles=50)
        self.assertEqual(final, State.ESCALATED)
        self.assertEqual(item.retries, 3)
        dispatches = [ev for _, ev, _ in item.history if ev in (Event.DISPATCH, Event.RETRY)]
        # 1 initial dispatch + exactly N retries, then escalation.
        self.assertEqual(dispatches, [Event.DISPATCH, Event.RETRY, Event.RETRY, Event.RETRY])

    def test_ceiling_plus_one_retry_raises(self):
        engine = LoopEngine(GuardrailConfig(retry_ceiling=2, per_issue_budget=1e9))
        item = WorkItem(id="PLA-11")
        _fail_cycle(engine, item)  # initial dispatch, retries 0 -> NEEDS_FIX
        _fail_cycle(engine, item)  # retry #1, retries 1 -> NEEDS_FIX
        _fail_cycle(engine, item)  # retry #2, retries 2 -> NEEDS_FIX
        self.assertEqual(item.retries, 2)
        with self.assertRaises(RetryCeilingExceeded) as ctx:
            engine.dispatch(item)  # retries 2 >= ceiling 2 -> escalate
        self.assertEqual(ctx.exception.scope, "retry")
        self.assertEqual(item.state, State.ESCALATED)


# --------------------------------------------------------------------------- #
# STOP-CONDITION 2 & 3 — budget caps stop dispatch
# --------------------------------------------------------------------------- #
class BudgetCapTest(unittest.TestCase):
    def test_per_issue_budget_stops_dispatch_and_escalates(self):
        engine = LoopEngine(
            GuardrailConfig(per_issue_budget=2.0, retry_ceiling=99, global_budget=1e9)
        )
        item = WorkItem(id="PLA-20")
        final = run_item(engine, item, lambda _i: _clean_fail(), cost_per_cycle=1.0)
        self.assertEqual(final, State.ESCALATED)
        # Spend never exceeds the cap.
        self.assertLessEqual(item.cost_spent, 2.0)

    def test_per_issue_budget_scope_and_no_overspend(self):
        engine = LoopEngine(GuardrailConfig(per_issue_budget=2.0, global_budget=1e9))
        item = WorkItem(id="PLA-21")
        engine.dispatch(item, cost=2.0)  # exactly at the cap — allowed
        engine.open_pr(item)
        engine.gate_complete(item)
        engine.record_verification(item, _clean_fail())  # -> NEEDS_FIX
        with self.assertRaises(BudgetExceeded) as ctx:
            engine.dispatch(item, cost=0.01)  # any more overshoots
        self.assertEqual(ctx.exception.scope, "per_issue")
        self.assertEqual(item.state, State.ESCALATED)
        self.assertEqual(item.cost_spent, 2.0)

    def test_global_budget_circuit_breaker_halts_fleet(self):
        engine = LoopEngine(
            GuardrailConfig(global_budget=2.0, per_issue_budget=1e9, retry_ceiling=99)
        )
        a, b, c, d = (WorkItem(id=x) for x in ("A", "B", "C", "D"))
        engine.dispatch(a, cost=1.0)  # global_spent 1
        engine.dispatch(b, cost=1.0)  # global_spent 2 (at cap)
        with self.assertRaises(BudgetExceeded) as ctx:
            engine.dispatch(c, cost=1.0)  # would be 3 > 2
        self.assertEqual(ctx.exception.scope, "global")
        self.assertTrue(engine.halted)
        # The breaker halts the FLEET: even an untouched item is refused now.
        self.assertEqual(c.state, State.READY)  # global breaker does not escalate the item
        with self.assertRaises(BudgetExceeded):
            engine.dispatch(d, cost=0.1)
        ok, _reason = engine.can_dispatch(d, cost=0.1)
        self.assertFalse(ok)


# --------------------------------------------------------------------------- #
# STOP-CONDITION 4 — determinism (ban --reruns / network / unpinned seed)
# --------------------------------------------------------------------------- #
class DeterminismTest(unittest.TestCase):
    def test_reruns_run_is_inadmissible(self):
        engine = LoopEngine()
        with self.assertRaises(DeterminismViolation):
            engine.admit_verification(_clean_pass(used_reruns=True))

    def test_network_run_is_inadmissible(self):
        engine = LoopEngine()
        with self.assertRaises(DeterminismViolation):
            engine.admit_verification(_clean_pass(network_accessed=True))

    def test_unpinned_seed_is_inadmissible(self):
        engine = LoopEngine()
        with self.assertRaises(DeterminismViolation):
            engine.admit_verification(_clean_pass(seed_pinned=False))

    def test_reruns_pass_can_never_reach_done(self):
        # The core "green != correct" guard: a retry-until-green pass must NOT merge.
        engine = LoopEngine()
        item = WorkItem(id="PLA-30")
        _to_verifying(engine, item)
        with self.assertRaises(DeterminismViolation) as ctx:
            engine.record_verification(item, _clean_pass(used_reruns=True))
        self.assertEqual(ctx.exception.scope, "determinism")
        self.assertEqual(item.state, State.ESCALATED)
        self.assertNotEqual(item.state, State.DONE)

    def test_clean_deterministic_pass_is_admissible(self):
        engine = LoopEngine()
        engine.admit_verification(_clean_pass())  # no raise


# --------------------------------------------------------------------------- #
# STOP-CONDITION 5 — ambiguous verification escalates
# --------------------------------------------------------------------------- #
class AmbiguousVerificationTest(unittest.TestCase):
    def test_ambiguous_verdict_escalates(self):
        engine = LoopEngine()
        item = WorkItem(id="PLA-40")
        _to_verifying(engine, item)
        with self.assertRaises(AmbiguousVerification) as ctx:
            engine.record_verification(item, VerificationRun(verdict=Verdict.AMBIGUOUS))
        self.assertEqual(ctx.exception.scope, "ambiguous")
        self.assertEqual(item.state, State.ESCALATED)


# --------------------------------------------------------------------------- #
# GUARDRAIL 5 — dispatch rate-limit (graceful backoff, not a terminal failure)
# --------------------------------------------------------------------------- #
class DispatchRateLimitTest(unittest.TestCase):
    def test_rate_limit_blocks_then_recovers_after_window(self):
        clock = FakeClock()
        engine = LoopEngine(
            GuardrailConfig(
                dispatch_rate_max=2, dispatch_rate_window=60.0, per_issue_budget=1e9
            ),
            clock=clock,
        )
        a, b, c = (WorkItem(id=x) for x in ("A", "B", "C"))
        engine.dispatch(a)  # 1st in window — ok
        engine.dispatch(b)  # 2nd in window — ok (at the limit)
        with self.assertRaises(DispatchRateLimited) as ctx:
            engine.dispatch(c)  # 3rd within 60s — rate-limited
        self.assertEqual(ctx.exception.scope, "rate_limit")
        # Backpressure, NOT terminal: the item is not escalated and did not spend.
        self.assertEqual(c.state, State.READY)
        self.assertEqual(c.cost_spent, 0.0)
        # After the window advances, dispatch succeeds again (graceful recovery).
        clock.advance(61.0)
        engine.dispatch(c)
        self.assertEqual(c.state, State.DISPATCHED)

    def test_rate_limit_disabled_by_default(self):
        engine = LoopEngine(GuardrailConfig(per_issue_budget=1e9))
        for x in "ABCDEFGH":  # far more than any window would allow
            engine.dispatch(WorkItem(id=x))  # no DispatchRateLimited raised

    def test_can_dispatch_reports_rate_limit(self):
        clock = FakeClock()
        engine = LoopEngine(
            GuardrailConfig(dispatch_rate_max=1, dispatch_rate_window=60.0), clock=clock
        )
        engine.dispatch(WorkItem(id="A"))
        ok, reason = engine.can_dispatch(WorkItem(id="B"), cost=1.0)
        self.assertFalse(ok)
        self.assertIn("rate-limit", reason)


# --------------------------------------------------------------------------- #
# The lights-out gate — cannot arm until the harness is green
# --------------------------------------------------------------------------- #
class LightsOutGateTest(unittest.TestCase):
    def test_arm_refused_without_validation(self):
        engine = LoopEngine()
        self.assertFalse(engine.auto_dispatch_armed)
        with self.assertRaises(GuardrailTripped) as ctx:
            engine.arm_auto_dispatch(guardrails_validated=False)
        self.assertEqual(ctx.exception.scope, "lights_out")
        self.assertFalse(engine.auto_dispatch_armed)

    def test_arm_allowed_with_validation(self):
        engine = LoopEngine()
        engine.arm_auto_dispatch(guardrails_validated=True)
        self.assertTrue(engine.auto_dispatch_armed)


# --------------------------------------------------------------------------- #
# can_dispatch mirrors dispatch (non-mutating pre-check)
# --------------------------------------------------------------------------- #
class CanDispatchPredicateTest(unittest.TestCase):
    def test_fresh_item_is_dispatchable(self):
        engine = LoopEngine()
        ok, reason = engine.can_dispatch(WorkItem(id="PLA-50"), cost=1.0)
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_predicate_does_not_mutate(self):
        engine = LoopEngine()
        item = WorkItem(id="PLA-51")
        engine.can_dispatch(item, cost=1.0)
        self.assertEqual(item.state, State.READY)
        self.assertEqual(item.cost_spent, 0.0)
        self.assertEqual(engine.global_spent, 0.0)

    def test_terminal_item_not_dispatchable(self):
        engine = LoopEngine()
        item = WorkItem(id="PLA-52", state=State.DONE)
        ok, _ = engine.can_dispatch(item, cost=1.0)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
