"""Autonomous-delivery loop state machine + guardrail engine (SP-C-1).

This module is the machine-checkable half of ``governance/decisions/ADR-LOOP-STATE-MACHINE.md``.
It encodes:

* the explicit state machine ``ready -> dispatched -> in_review -> verifying ->
  done | needs_fix -> escalated`` as a **deterministic** transition table (illegal
  transitions fail closed);
* the **deterministic glue** transitions (event-driven mechanics — safe to run
  lights-out and validated by the harness); the **judgment** transitions
  (``verified_pass`` / ``verified_fail`` / ``ambiguous``) are an *injected* verdict
  oracle so the glue and guardrails are testable while the un-guaranteed agent
  judgment stays a pluggable seam;
* the 5 hard **guardrails** (``governance/autonomous-loop.md``): (1) N-retry /
  max-iterations ceiling → escalate; (2) cumulative per-issue + global cost cap
  (the global cap is a fleet-wide circuit-breaker); (3) determinism — ban
  ``--reruns`` / network / unpinned seed in verification; (4) consecutive-failure
  and ambiguous-verification → escalate; (5) dispatch rate-limit (graceful
  backoff, per PLA-241) → transient backpressure, not a terminal failure.

Stdlib only, no network — the same discipline the loop enforces. Run the harness:

    python3 -m unittest discover -s governance/loop/tests -v

The harness passing is the **lights-out gate**: ``arm_auto_dispatch`` refuses to
arm unless it is handed proof the guardrails validated (which is only true when
those tests pass). See the ADR's "The lights-out gate" section.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


# --------------------------------------------------------------------------- #
# States, events, verdicts
# --------------------------------------------------------------------------- #
class State(str, Enum):
    """The loop states (ADR §1)."""

    READY = "ready"
    DISPATCHED = "dispatched"
    IN_REVIEW = "in_review"
    VERIFYING = "verifying"
    DONE = "done"
    NEEDS_FIX = "needs_fix"
    ESCALATED = "escalated"


class Event(str, Enum):
    """The transition events (ADR §2)."""

    DISPATCH = "dispatch"
    PR_OPENED = "pr_opened"
    GATE_COMPLETE = "gate_complete"
    VERIFIED_PASS = "verified_pass"
    VERIFIED_FAIL = "verified_fail"
    RETRY = "retry"
    ESCALATE = "escalate"


class Verdict(str, Enum):
    """A verifier's judgment (the injected, un-guaranteed seam)."""

    PASS = "pass"
    FAIL = "fail"
    AMBIGUOUS = "ambiguous"


#: Terminal states — no further auto-dispatch happens from here.
TERMINAL: frozenset[State] = frozenset({State.DONE, State.ESCALATED})

#: The deterministic transition table (glue). ``escalate`` is legal from any
#: non-terminal state and is handled separately (a stop-condition firing).
TRANSITIONS: dict[tuple[State, Event], State] = {
    (State.READY, Event.DISPATCH): State.DISPATCHED,
    (State.DISPATCHED, Event.PR_OPENED): State.IN_REVIEW,
    (State.IN_REVIEW, Event.GATE_COMPLETE): State.VERIFYING,
    (State.VERIFYING, Event.VERIFIED_PASS): State.DONE,
    (State.VERIFYING, Event.VERIFIED_FAIL): State.NEEDS_FIX,
    (State.NEEDS_FIX, Event.RETRY): State.DISPATCHED,
}

#: Events that require JUDGMENT (an instantiated agent), not deterministic glue.
#: Documented here so callers/readers can see the split at a glance (ADR §3).
JUDGMENT_EVENTS: frozenset[Event] = frozenset(
    {Event.VERIFIED_PASS, Event.VERIFIED_FAIL}
)


# --------------------------------------------------------------------------- #
# Errors — every guardrail trip is a distinct, catchable type
# --------------------------------------------------------------------------- #
class LoopError(Exception):
    """Base for all loop errors."""


class IllegalTransition(LoopError):
    """An event not permitted from the current state (fail-closed)."""


class GuardrailTripped(LoopError):
    """Base for the hard stop-conditions (ADR §4)."""

    #: Coarse category, e.g. "retry" / "budget" / "determinism" / "ambiguous".
    scope: str = "guardrail"

    def __init__(self, message: str, scope: Optional[str] = None) -> None:
        super().__init__(message)
        if scope is not None:
            self.scope = scope


class RetryCeilingExceeded(GuardrailTripped):
    """More than ``retry_ceiling`` fix cycles on one item (STOP-CONDITION 1)."""

    scope = "retry"


class BudgetExceeded(GuardrailTripped):
    """Per-issue cap or global circuit-breaker tripped (STOP-CONDITIONS 2 & 3).

    ``scope`` is ``"per_issue"`` (this item escalates) or ``"global"`` (the whole
    fleet halts).
    """

    scope = "budget"


class DeterminismViolation(GuardrailTripped):
    """A non-deterministic verification run (``--reruns`` / network / unpinned
    seed) tried to advance the loop (STOP-CONDITION 4)."""

    scope = "determinism"


class AmbiguousVerification(GuardrailTripped):
    """The verifier could not render a confident verdict (STOP-CONDITION 5)."""

    scope = "ambiguous"


class DispatchRateLimited(GuardrailTripped):
    """The dispatch rate-limit fired — transient backpressure, NOT a terminal
    failure (GUARDRAIL 5 / PLA-241). The item stays dispatchable; the caller
    backs off and retries, degrading gracefully instead of tripping Linear's
    shared per-actor quota."""

    scope = "rate_limit"


# --------------------------------------------------------------------------- #
# Config + value objects
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GuardrailConfig:
    """Tunable ceilings for the loop. Defaults are conservative starting points;
    tune per repo + cost model (ADR §4)."""

    retry_ceiling: int = 3
    per_issue_budget: float = 5.0
    global_budget: float = 100.0
    #: Determinism policy — all three must hold for a verification run to be
    #: admissible in the loop. They are *bans*, not knobs to relax lightly.
    require_pinned_seed: bool = True
    allow_reruns: bool = False
    allow_network_in_verify: bool = False
    #: Dispatch rate-limit (GUARDRAIL 5 / PLA-241) — at most ``dispatch_rate_max``
    #: dispatches per ``dispatch_rate_window`` seconds, shared across the fleet
    #: (Linear's quota is per-actor). ``None`` disables the limiter.
    dispatch_rate_max: Optional[int] = None
    dispatch_rate_window: float = 3600.0


@dataclass
class RateLimiter:
    """A sliding-window dispatch limiter (GUARDRAIL 5). Deterministic: time is
    injected, never read from the wall clock inside the loop."""

    max_dispatches: int
    window: float
    _events: list[float] = field(default_factory=list)

    def allow(self, now: float) -> bool:
        """True iff a dispatch at ``now`` stays within the window budget."""
        cutoff = now - self.window
        self._events = [t for t in self._events if t > cutoff]
        return len(self._events) < self.max_dispatches

    def record(self, now: float) -> None:
        self._events.append(now)


@dataclass(frozen=True)
class VerificationRun:
    """One verification attempt: its determinism properties + the verifier's
    (judgment) verdict. The determinism fields are checked deterministically;
    ``verdict`` is the injected, un-guaranteed seam."""

    verdict: Verdict
    used_reruns: bool = False
    network_accessed: bool = False
    seed_pinned: bool = True


@dataclass
class WorkItem:
    """A single Linear work item flowing through the loop (D4: no work without a
    work item). Mutable — the engine advances it."""

    id: str
    state: State = State.READY
    retries: int = 0
    cost_spent: float = 0.0
    history: list[tuple[State, Event, State]] = field(default_factory=list)

    def _apply(self, event: Event) -> State:
        """Deterministic transition via the table. Raises on an illegal move."""
        key = (self.state, event)
        if key not in TRANSITIONS:
            raise IllegalTransition(
                f"{self.id}: event {event.value!r} illegal from state "
                f"{self.state.value!r}"
            )
        new_state = TRANSITIONS[key]
        self.history.append((self.state, event, new_state))
        self.state = new_state
        return new_state

    def _escalate(self, event: Event = Event.ESCALATE) -> None:
        """Fail-closed move to ``escalated`` from any non-terminal state."""
        self.history.append((self.state, event, State.ESCALATED))
        self.state = State.ESCALATED


# --------------------------------------------------------------------------- #
# The engine
# --------------------------------------------------------------------------- #
class LoopEngine:
    """Drives work items through the loop while enforcing the stop-conditions.

    All auto-dispatch flows through :meth:`dispatch`, so the guardrails have a
    single chokepoint. Judgment enters only via :meth:`record_verification`,
    which takes a :class:`VerificationRun` (verdict from the injected oracle).
    """

    def __init__(
        self,
        config: GuardrailConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or GuardrailConfig()
        self._clock = clock
        self.global_spent: float = 0.0
        #: Set when the global circuit-breaker trips — no new dispatch fleet-wide.
        self.halted: bool = False
        self._auto_dispatch_armed: bool = False
        self._rate: Optional[RateLimiter] = (
            RateLimiter(self.config.dispatch_rate_max, self.config.dispatch_rate_window)
            if self.config.dispatch_rate_max is not None
            else None
        )

    # -- guardrail-gated dispatch (glue) ----------------------------------- #
    def can_dispatch(self, item: WorkItem, cost: float) -> tuple[bool, str]:
        """Non-mutating predicate: may ``item`` be (re)dispatched at ``cost``?

        Returns ``(ok, reason)``. Mirrors the guard order in :meth:`dispatch` so
        callers can pre-check without tripping/escalating.
        """
        if self.halted:
            return False, "global budget circuit-breaker is open (fleet halted)"
        if item.state in TERMINAL:
            return False, f"item is terminal ({item.state.value})"
        if item.state not in (State.READY, State.NEEDS_FIX):
            return False, f"item not dispatchable from {item.state.value}"
        if item.state == State.NEEDS_FIX and item.retries >= self.config.retry_ceiling:
            return False, f"retry ceiling reached ({self.config.retry_ceiling})"
        if item.cost_spent + cost > self.config.per_issue_budget:
            return False, "per-issue budget cap would be exceeded"
        if self.global_spent + cost > self.config.global_budget:
            return False, "global budget cap would be exceeded"
        if self._rate is not None and not self._rate.allow(self._clock()):
            return False, "dispatch rate-limit — back off and retry"
        return True, "ok"

    def dispatch(self, item: WorkItem, cost: float = 1.0) -> State:
        """``ready``/``needs_fix`` -> ``dispatched``, enforcing every guardrail.

        Fail-closed: a tripped stop-condition raises (and escalates the item, or
        halts the fleet for the global breaker) rather than dispatching.
        """
        if self.halted:
            raise BudgetExceeded(
                "global budget circuit-breaker is open — no new dispatch",
                scope="global",
            )
        if item.state in TERMINAL:
            raise IllegalTransition(
                f"{item.id}: cannot dispatch a terminal item ({item.state.value})"
            )
        if item.state not in (State.READY, State.NEEDS_FIX):
            raise IllegalTransition(
                f"{item.id}: cannot dispatch from {item.state.value}"
            )

        is_retry = item.state == State.NEEDS_FIX

        # STOP-CONDITION 1 — N-retry ceiling.
        if is_retry and item.retries >= self.config.retry_ceiling:
            item._escalate()
            raise RetryCeilingExceeded(
                f"{item.id}: retry ceiling {self.config.retry_ceiling} reached — "
                f"escalating instead of a {item.retries + 1}th fix cycle",
                scope="retry",
            )

        # STOP-CONDITION 2 — per-issue budget cap.
        if item.cost_spent + cost > self.config.per_issue_budget:
            item._escalate()
            raise BudgetExceeded(
                f"{item.id}: per-issue budget {self.config.per_issue_budget} "
                f"would be exceeded ({item.cost_spent} + {cost})",
                scope="per_issue",
            )

        # STOP-CONDITION 3 — global budget circuit-breaker (fleet-wide halt).
        if self.global_spent + cost > self.config.global_budget:
            self.halted = True
            raise BudgetExceeded(
                f"global budget {self.config.global_budget} would be exceeded "
                f"({self.global_spent} + {cost}) — halting all dispatch",
                scope="global",
            )

        # GUARDRAIL 5 — dispatch rate-limit (transient backpressure; do NOT
        # escalate or spend — the item stays dispatchable, the caller backs off).
        now = self._clock()
        if self._rate is not None and not self._rate.allow(now):
            raise DispatchRateLimited(
                f"{item.id}: dispatch rate-limit "
                f"({self.config.dispatch_rate_max}/{self.config.dispatch_rate_window}s) "
                "reached — back off and retry (graceful degradation, not a failure)",
                scope="rate_limit",
            )

        # Guards passed — spend + move (the retry counter is the fix-cycle count).
        if is_retry:
            item.retries += 1
            item._apply(Event.RETRY)
        else:
            item._apply(Event.DISPATCH)
        item.cost_spent += cost
        self.global_spent += cost
        if self._rate is not None:
            self._rate.record(now)
        return item.state

    # -- plain glue events -------------------------------------------------- #
    def open_pr(self, item: WorkItem) -> State:
        """``dispatched`` -> ``in_review`` (deterministic: PR-opened event)."""
        return item._apply(Event.PR_OPENED)

    def gate_complete(self, item: WorkItem) -> State:
        """``in_review`` -> ``verifying`` (deterministic: CI-gate-complete)."""
        return item._apply(Event.GATE_COMPLETE)

    # -- determinism guardrail --------------------------------------------- #
    def admit_verification(self, run: VerificationRun) -> None:
        """STOP-CONDITION 4. Raise :class:`DeterminismViolation` unless ``run`` is
        deterministic (no ``--reruns``, no network, pinned seed). Non-mutating."""
        if run.used_reruns and not self.config.allow_reruns:
            raise DeterminismViolation(
                "verification used test --reruns — retry-until-green masks "
                "flakiness and launders reward-hacking; inadmissible in the loop",
                scope="determinism",
            )
        if run.network_accessed and not self.config.allow_network_in_verify:
            raise DeterminismViolation(
                "verification accessed the network — non-deterministic; "
                "inadmissible in the loop",
                scope="determinism",
            )
        if self.config.require_pinned_seed and not run.seed_pinned:
            raise DeterminismViolation(
                "verification ran with an unpinned seed — non-deterministic; "
                "inadmissible in the loop",
                scope="determinism",
            )

    def record_verification(self, item: WorkItem, run: VerificationRun) -> State:
        """``verifying`` -> ``done`` | ``needs_fix`` | ``escalated``.

        The determinism guard (STOP-CONDITION 4) runs first, so a ``--reruns`` /
        networked / unpinned "pass" can **never** reach ``done`` — it escalates.
        Then the injected verdict (judgment) decides: PASS->done, FAIL->needs_fix,
        AMBIGUOUS->escalate (STOP-CONDITION 5).
        """
        if item.state != State.VERIFYING:
            raise IllegalTransition(
                f"{item.id}: verification only valid from 'verifying', not "
                f"{item.state.value!r}"
            )

        # Determinism first — a tainted run cannot advance to done; escalate.
        try:
            self.admit_verification(run)
        except DeterminismViolation:
            item._escalate()
            raise

        if run.verdict is Verdict.PASS:
            return item._apply(Event.VERIFIED_PASS)
        if run.verdict is Verdict.FAIL:
            return item._apply(Event.VERIFIED_FAIL)

        # AMBIGUOUS — do not guess; escalate to a human.
        item._escalate()
        raise AmbiguousVerification(
            f"{item.id}: verifier returned an ambiguous verdict — escalating "
            "rather than guessing",
            scope="ambiguous",
        )

    # -- lights-out arming -------------------------------------------------- #
    @property
    def auto_dispatch_armed(self) -> bool:
        return self._auto_dispatch_armed

    def arm_auto_dispatch(self, *, guardrails_validated: bool) -> None:
        """Flip the lights-out flag — refused unless the guardrail harness is
        green. ``guardrails_validated`` is the caller's proof (only true when
        ``governance/loop/tests`` pass). See the ADR's "lights-out gate"."""
        if not guardrails_validated:
            raise GuardrailTripped(
                "auto-dispatch may not be armed until the guardrail harness is "
                "green (run: python3 -m unittest discover -s governance/loop/tests)",
                scope="lights_out",
            )
        self._auto_dispatch_armed = True


# --------------------------------------------------------------------------- #
# A tiny loop driver — used by the harness and re-usable as a simulator
# --------------------------------------------------------------------------- #
def run_item(
    engine: LoopEngine,
    item: WorkItem,
    verifier: Callable[[WorkItem], VerificationRun],
    *,
    cost_per_cycle: float = 1.0,
    max_cycles: int = 100,
) -> State:
    """Drive ``item`` to a terminal state, calling ``verifier`` (the injected
    judgment seam) each cycle. Returns the terminal :class:`State`.

    Guardrail trips (:class:`GuardrailTripped`) are the *designed* exits — they
    are caught here so the driver returns the terminal state rather than
    propagating; the state itself records what happened (``escalated`` /
    ``done``). ``max_cycles`` is a belt-and-braces bound so a mis-wired verifier
    can never spin forever (the real bound is the retry ceiling).
    """
    for _ in range(max_cycles):
        if item.state in TERMINAL:
            return item.state
        try:
            if item.state in (State.READY, State.NEEDS_FIX):
                engine.dispatch(item, cost=cost_per_cycle)
            engine.open_pr(item)
            engine.gate_complete(item)
            engine.record_verification(item, verifier(item))
        except GuardrailTripped:
            # A stop-condition fired; the item is escalated (or the fleet
            # halted). Surface the terminal state, not the exception.
            return item.state
    raise LoopError(
        f"{item.id}: exceeded max_cycles={max_cycles} without terminating — "
        "a guardrail should have fired first"
    )
