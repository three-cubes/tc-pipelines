"""The loop's remaining refusals, tolerant parsers and operator renders.

The other suites prove each guardrail fires on its main path. These cover the
branches they leave: the refusals a caller meets when it asks for an illegal
move, the Linear and ledger shapes the parsers accept, and the operator views'
empty, refused and skipped renders. Pure, in-process and deterministic.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import loop_dispatcher as disp
import loop_runner as runner_mod
import tree_reconciler as rec
from loop_governor import Governor, Outcome, RetryCeilingExceeded
from loop_state_machine import (
    BudgetExceeded,
    GuardrailConfig,
    GuardrailTripped,
    IllegalTransition,
    LoopEngine,
    LoopError,
    State,
    Verdict,
    VerificationRun,
    WorkItem,
    run_item,
)

pytestmark = pytest.mark.unit

PASS = VerificationRun(verdict=Verdict.PASS)


# --------------------------------------------------------------------------- #
# State machine
# --------------------------------------------------------------------------- #
def test_an_item_mid_flight_is_not_dispatchable() -> None:
    engine = LoopEngine(GuardrailConfig())
    item = WorkItem(id="PLA-1", state=State.IN_REVIEW)

    assert engine.can_dispatch(item, 1.0) == (False, "item not dispatchable from in_review")
    with pytest.raises(IllegalTransition, match="cannot dispatch from in_review"):
        engine.dispatch(item)


def test_a_fix_cycle_at_the_retry_ceiling_is_not_dispatchable() -> None:
    engine = LoopEngine(GuardrailConfig(retry_ceiling=2))
    item = WorkItem(id="PLA-2", state=State.NEEDS_FIX, retries=2)

    assert engine.can_dispatch(item, 1.0) == (False, "retry ceiling reached (2)")


def test_run_item_returns_a_terminal_item_unchanged() -> None:
    item = WorkItem(id="PLA-3", state=State.DONE)

    assert run_item(LoopEngine(GuardrailConfig()), item, lambda _: PASS) is State.DONE
    assert item.history == []


def test_run_item_refuses_to_spin_past_its_cycle_bound() -> None:
    with pytest.raises(LoopError, match="exceeded max_cycles=0"):
        run_item(LoopEngine(GuardrailConfig()), WorkItem(id="PLA-4"), lambda _: PASS, max_cycles=0)


# --------------------------------------------------------------------------- #
# Governor
# --------------------------------------------------------------------------- #
def armed(config: GuardrailConfig | None = None) -> Governor:
    governor = Governor(config, clock=lambda: 0.0)
    governor.arm(guardrails_validated=True)
    return governor


def test_require_continuable_passes_a_dispatchable_issue() -> None:
    assert armed().require_continuable("PLA-1") is None


def test_require_continuable_refuses_while_disarmed() -> None:
    with pytest.raises(GuardrailTripped, match="not armed") as exc:
        Governor(clock=lambda: 0.0).require_continuable("PLA-1")
    assert exc.value.scope == "lights_out"


def test_a_done_issue_is_terminal_to_every_entry_point() -> None:
    governor = armed()
    governor.record_success("PLA-1")

    assert governor.should_continue("PLA-1").reason == "issue already done (terminal)"
    with pytest.raises(IllegalTransition, match="already done"):
        governor.require_continuable("PLA-1")
    result = governor.run_cycle("PLA-1", dispatch=lambda _: None, verify=lambda _: PASS, close=lambda _: None)
    assert result.outcome is Outcome.DONE


def test_require_continuable_raises_the_retry_ceiling() -> None:
    governor = armed(GuardrailConfig(retry_ceiling=1))
    governor.record_attempt("PLA-1")

    with pytest.raises(RetryCeilingExceeded) as exc:
        governor.require_continuable("PLA-1")
    assert exc.value.scope == "retry"


def test_require_continuable_raises_the_global_budget_when_the_circuit_is_closed() -> None:
    governor = armed(GuardrailConfig(per_issue_budget=10.0, global_budget=1.0))

    with pytest.raises(BudgetExceeded) as exc:
        governor.require_continuable("PLA-1", cost=2.0)
    assert exc.value.scope == "global"
    assert not governor.circuit_open


def test_measured_spend_past_the_global_cap_halts_the_cycle_it_lands_in() -> None:
    governor = armed(GuardrailConfig(per_issue_budget=10.0, global_budget=2.0))

    def verify(issue_id: str) -> VerificationRun:
        # The token-logger reports spend beyond the cycle's projection.
        governor.record_cost(issue_id, 1.5)
        return PASS

    closed: list[str] = []
    result = governor.run_cycle("PLA-1", dispatch=lambda _: None, verify=verify, close=closed.append)

    assert result.outcome is Outcome.HALTED
    assert governor.halted and closed == []


def test_run_until_terminal_refuses_to_spin_past_its_cycle_bound() -> None:
    with pytest.raises(LoopError, match="exceeded max_cycles=0"):
        armed().run_until_terminal(
            "PLA-1", dispatch=lambda _: None, verify=lambda _: PASS, close=lambda _: None, max_cycles=0
        )


# --------------------------------------------------------------------------- #
# Dispatcher parsing and render
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("assignee", "expected"),
    [({"displayName": "Dan"}, "Dan"), ({"name": ""}, None), ("dan", "dan")],
)
def test_the_assignee_is_read_from_each_linear_shape(assignee: object, expected: str | None) -> None:
    assert disp.CandidateIssue.from_linear({"id": "PLA-1", "assignee": assignee}).assignee == expected


def test_blockers_are_read_from_ids_and_explicit_activity() -> None:
    issue = disp.CandidateIssue.from_linear(
        {"id": "PLA-1", "blockers": ["PLA-9", {"id": "PLA-8", "active": False}]}
    )

    assert [(b.id, b.active) for b in issue.blockers] == [("PLA-9", True), ("PLA-8", False)]
    assert issue.is_blocked


def test_a_long_title_slug_is_cut_without_a_trailing_dash() -> None:
    slug = disp.slugify("word " * 20, max_len=12)

    assert slug == "word-word-wo"
    assert disp.slugify("a b c d e f", max_len=4) == "a-b"


def test_an_unparseable_creation_time_sorts_last() -> None:
    dated = disp.CandidateIssue(id="PLA-1", created_at="2026-07-01T00:00:00+00:00", labels=("adp-wave-1",))
    garbage = disp.CandidateIssue(id="PLA-2", created_at="not-a-date", labels=("adp-wave-1",))

    assert [i.id for i in disp.ready_queue([garbage, dated])] == ["PLA-1", "PLA-2"]


def test_a_refused_empty_plan_renders_its_refusal_and_skips() -> None:
    plan = disp.DispatchPlan(
        initiative="init",
        ready_queue=(),
        contracts=(),
        skipped=(("PLA-7", "per-issue budget cap would be exceeded"),),
        armed=False,
        refusal="guardrail harness is red",
        per_issue_budget=5.0,
        global_budget=100.0,
        global_spent=0.0,
    )

    text = disp.render_plan(plan, dry_run=False)

    assert "    (none)" in text
    assert "auto-dispatch REFUSED" in text and "refusal: guardrail harness is red" in text
    assert "    (nothing)" in text
    assert "    - PLA-7: per-issue budget cap would be exceeded" in text
    assert "[dry-run]" not in text


# --------------------------------------------------------------------------- #
# Reconciler parsing
# --------------------------------------------------------------------------- #
def test_tree_issues_read_the_mcp_status_parent_and_pr_shapes() -> None:
    issue = rec.TreeIssue.from_linear(
        {
            "id": "PLA-2",
            "status": {"name": "In Review"},
            "parent": "PLA-1",
            "pr_urls": ["https://github.com/three-cubes/x/pull/1", ""],
        }
    )

    assert (issue.status_name, issue.parent_id) == ("In Review", "PLA-1")
    assert issue.pr_urls == ("https://github.com/three-cubes/x/pull/1",)


@pytest.mark.parametrize(
    ("raw", "live"),
    [({"live": False}, False), ({"status": "Killed"}, False), ({"state": "running"}, True)],
)
def test_a_delegation_is_live_unless_marked_otherwise(raw: dict, live: bool) -> None:
    assert rec.Delegation.from_dict({"id": "d1", **raw}).live is live


def test_an_unparseable_start_time_is_never_overdue() -> None:
    started = rec.TreeIssue(
        id="PLA-3", state_type="started", status_name="In Progress", started_at="yesterday-ish"
    )
    delegation = rec.Delegation(id="d3", issue_id="PLA-3", branch="dan/pla-3-x")

    report = rec.reconcile([started], [delegation], now=datetime(2026, 10, 7, tzinfo=UTC))

    assert report.by_kind(rec.FindingKind.OVERDUE) == ()


# --------------------------------------------------------------------------- #
# Runner sink validation, ledger access and render
# --------------------------------------------------------------------------- #
CONTRACT = disp.DispatchContract(
    issue_id="PLA-5",
    title="work",
    repo="kairix",
    branch="dan/pla-5-work",
    acceptance_criteria="linear:PLA-5",
    wave=1,
    priority=2,
    url="",
)


@pytest.mark.parametrize(
    ("config", "message"),
    [({"repo": "not a repo"}, "unsafe orchestrator repo"), ({"workflow": "../x.sh"}, "unsafe workflow")],
)
def test_the_real_sink_refuses_an_unsafe_target_before_any_request(config: dict, message: str) -> None:
    requests: list[str] = []
    sink = runner_mod.GitHubActionsDispatchSink(
        token="t",
        **{"repo": "three-cubes/agent-platform", **config},
        transport=lambda url, body, headers: requests.append(url) or (204, ""),
    )

    with pytest.raises(ValueError, match=message):
        sink.dispatch(CONTRACT)
    assert requests == []


def test_the_runner_exposes_the_ledger_store_it_persists_to() -> None:
    store = runner_mod.JsonFileStateStore(Path("loop-state.json"))
    dispatcher = disp.Dispatcher(disp.StaticIssueSource([]), guardrails_validator=lambda: True)

    runner = runner_mod.Runner(dispatcher, Governor(), state_store=store)

    assert runner.state_store is store


def test_a_tick_renders_its_dispatch_result_and_runtime_skips() -> None:
    result = runner_mod.RunResult(
        decision=runner_mod.RunDecision.DISPATCHED,
        reason="armed and live",
        armed=True,
        harness_validated=True,
        dry_run=False,
        dispatched=True,
        initiative="init",
        contract=CONTRACT,
        dispatch_result=runner_mod.DispatchResult(
            spawned=False, sink="logging", issue_id="PLA-5", detail="logged"
        ),
        ready=("PLA-5",),
        skipped=(("PLA-6", "per-issue budget"),),
    )

    text = runner_mod.render_result(result)

    assert "  sink=logging  spawned=False  logged" in text
    assert "  skipped (runtime guardrail):\n    - PLA-6: per-issue budget" in text


@pytest.mark.parametrize(("raw", "ticks"), [(" 7 ", 7), ("-2", 0), ("seven", 0)])
def test_the_soak_ticks_default_reads_a_non_negative_int_from_the_environment(
    raw: str, ticks: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOOP_SOAK_TICKS", raw)

    assert runner_mod.build_arg_parser().parse_args([]).soak_ticks == ticks
