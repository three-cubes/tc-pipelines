"""A lane that did not run must not be able to report green through the fan-in.

Actions treats "skipped" as non-blocking: a skipped required check satisfies
branch protection, and a lane a fan-in waits for but never inspects contributes
nothing to that fan-in's conclusion. The fan-in is the one context a consumer
pins in branch protection, so a lane it does not inspect can fail into a green
merge.

Waiting is not inspecting. `needs:` only orders the graph; the verdict comes
from whatever the fan-in's shell actually tests. A lane bound to an env var that
is then printed but never compared reads as covered to any file-shape check
while contributing nothing to the exit status, so this asserts the lane's result
reaches a line that decides, not merely a line that reports.

The same gap runs the other way: a job outside the fan-in's `needs` closure
cannot reach its conclusion at all.

Neither is visible to actionlint or yamllint, which judge each file alone, nor
to the script-level tests, which execute shell lifted out of the workflows
rather than the workflows themselves.

A job that must report separately is declared in CLOSURE_EXEMPT with its reason,
so intent stays distinguishable from drift.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

RESULT_REF = re.compile(r"needs\.([A-Za-z0-9_-]+)\.result")

# (workflow, job) -> why the job reports outside the fan-in's closure.
CLOSURE_EXEMPT = {
    ("ci.yml", "no-attribution"): (
        "Emitted as its own BARE required status context. The org-main-core "
        "ruleset gates on `no-attribution`, and a nested `meta / no-attribution` "
        "cannot satisfy that context."
    ),
}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _jobs(document: dict) -> dict[str, dict]:
    return {
        name: job
        for name, job in (document.get("jobs") or {}).items()
        if isinstance(job, dict)
    }


def _needs(job: dict) -> list[str]:
    declared = job.get("needs") or []
    return [declared] if isinstance(declared, str) else list(declared)


def _workflows() -> list[Path]:
    return sorted(WORKFLOW_DIR.glob("*.yml"))


def _steps(job: dict) -> list[dict]:
    return [step for step in (job.get("steps") or []) if isinstance(step, dict)]


def _fan_ins() -> list[tuple[str, str, dict]]:
    """Terminal aggregators: (workflow, job, job body).

    Terminal means no other job in the file `needs` it, so its conclusion is what
    a ruleset or a calling workflow reads. Aggregator means it reads at least one
    lane result — an `always()` cleanup or notify job decides nothing and is not
    a merge signal.
    """
    found = []
    for path in _workflows():
        jobs = _jobs(_load(path))
        for name, job in jobs.items():
            if "always()" not in str(job.get("if", "")):
                continue
            if any(name in _needs(other) for other in jobs.values()):
                continue
            if not RESULT_REF.search(json.dumps(job)):
                continue
            found.append((path.name, name, job))
    return found


def _carriers(job: dict, lane: str) -> tuple[str, list[str]]:
    """The literal reference for a lane, plus the env vars bound to it."""
    reference = f"needs.{lane}.result"
    bound = [
        str(name)
        for step in _steps(job)
        for name, value in (step.get("env") or {}).items()
        if reference in str(value)
    ]
    return reference, bound


def _deciding_lines(job: dict) -> list[str]:
    """Run lines that can change the job's exit status.

    A line whose command is `echo`/`printf`, or that only appends to the step
    summary, reports a value without testing it.
    """
    lines = []
    for step in _steps(job):
        body = step.get("run")
        if not isinstance(body, str):
            continue
        # A shell continuation splits one command across physical lines.
        for line in re.sub(r"\\\n\s*", " ", body).splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.match(r"^(?:echo|printf)\b", stripped):
                continue
            if "GITHUB_STEP_SUMMARY" in stripped:
                continue
            lines.append(stripped)
    return lines


def _consumes(job: dict, lane: str) -> bool:
    reference, bound = _carriers(job, lane)
    deciding = _deciding_lines(job)
    if any(reference in line for line in deciding):
        return True
    return any(
        re.search(rf"\$\{{?{re.escape(name)}\b", line)
        for name in bound
        for line in deciding
    )


def _closure(jobs: dict[str, dict], root: str) -> set[str]:
    seen, pending = {root}, [root]
    while pending:
        for parent in _needs(jobs.get(pending.pop(), {})):
            if parent not in seen:
                seen.add(parent)
                pending.append(parent)
    return seen


FAN_INS = _fan_ins()
LANES = [
    (workflow, name, lane)
    for workflow, name, job in FAN_INS
    for lane in _needs(job)
]


# ── the scan matched something ───────────────────────────────────────────────


def test_the_scan_found_fan_in_aggregators() -> None:
    """A scan that silently matches nothing would pass every assertion below."""
    assert len(FAN_INS) >= 2, (
        f"only {len(FAN_INS)} terminal always() aggregator(s) discovered — the "
        f"job `if:` shapes have drifted, so the fan-ins that carry the required "
        f"status contexts are no longer being checked."
    )


def test_the_scan_found_lanes_to_check() -> None:
    assert len(LANES) >= 6, (
        f"only {len(LANES)} fan-in lane(s) discovered — the `needs:` shapes have "
        f"drifted, so lane consumption is no longer being checked."
    )


def test_both_ways_of_carrying_a_lane_result_are_still_exercised() -> None:
    """The consumption scan resolves a lane through an env binding OR a direct
    expression. A scan that lost either path would pass vacuously on the half it
    can no longer see."""
    via_env, via_expression = [], []
    for workflow, name, job in FAN_INS:
        for lane in _needs(job):
            _, bound = _carriers(job, lane)
            target = via_env if bound else via_expression
            target.append(f"{workflow}:{name}:{lane}")
    assert via_env and via_expression, (
        f"lane results are no longer carried both ways (env-bound: {via_env}, "
        f"inline expression: {via_expression}), so one branch of _consumes() is "
        f"never exercised and could rot unnoticed. "
        f"fix: keep a fan-in of each shape, or drop the unused branch."
    )


# ── a lane the fan-in waits for must reach a line that decides ───────────────


@pytest.mark.parametrize(
    ("workflow", "job_name", "lane"),
    LANES,
    ids=[f"{w}:{j}:{lane}" for w, j, lane in LANES],
)
def test_fan_in_consumes_every_lane_it_waits_for(
    workflow: str, job_name: str, lane: str
) -> None:
    job = _jobs(_load(WORKFLOW_DIR / workflow))[job_name]
    assert _consumes(job, lane), (
        f"{workflow}: fan-in `{job_name}` waits for `{lane}` but no line that "
        f"can change its exit status reads `needs.{lane}.result`. `needs:` only "
        f"orders the graph — a lane the fan-in prints but never tests fails "
        f"while this job, the required status context a consumer pins, reports "
        f"success and the PR merges. "
        f"fix: bind the lane (R_<LANE>: ${{{{ needs.{lane}.result }}}}) and add "
        f"$R_<LANE> to the loop that rejects 'failure' and 'cancelled', or test "
        f"`needs.{lane}.result` directly. Printing it in an echo does not count."
    )


def test_the_quality_gate_fails_when_neither_quality_lane_ran() -> None:
    """`detect-changes` and `shards` are not in `gate`'s needs, so a failure of
    either surfaces only as both quality lanes being skipped — which the
    failure/cancelled loop passes."""
    jobs = _jobs(_load(WORKFLOW_DIR / "python-quality-gate.yml"))
    assert "gate" in jobs, (
        "python-quality-gate.yml no longer has a `gate` job, so the fan-in every "
        "consumer pins as its required status context is gone or renamed. "
        "fix: restore the job, or repoint this test at its replacement."
    )
    gate = jobs["gate"]
    lines = _deciding_lines(gate)
    _, unsharded = _carriers(gate, "quality")
    _, sharded = _carriers(gate, "quality-shard")
    assert unsharded and sharded, (
        "python-quality-gate.yml: `gate` no longer binds the two quality lane "
        "results to env vars, so the did-not-run backstop cannot be verified. "
        "fix: restore the bindings."
    )
    guard = [
        index
        for index, line in enumerate(lines)
        if unsharded[0] in line and sharded[0] in line and "skipped" in line
    ]
    assert guard, (
        f"python-quality-gate.yml: `gate` no longer rejects the case where both "
        f"${unsharded[0]} and ${sharded[0]} are 'skipped'. Exactly one quality "
        f"lane runs, so both being skipped means the gate never executed — and "
        f"a skipped lane clears the failure/cancelled loop, leaving the required "
        f"context green having verified nothing. "
        f"fix: restore the branch that errors and exits 1 when both are 'skipped'."
    )
    assert any("exit 1" in line for line in lines[guard[0] :]), (
        "python-quality-gate.yml: `gate` detects that both quality lanes were "
        "skipped but does not exit non-zero, so the gate reports green having "
        "run nothing. fix: `exit 1` inside that branch."
    )


# ── a job outside the closure cannot reach the fan-in at all ─────────────────


@pytest.mark.parametrize(
    ("workflow", "job_name"),
    [(w, j) for w, j, _ in FAN_INS],
    ids=[f"{w}:{j}" for w, j, _ in FAN_INS],
)
def test_every_job_reaches_the_fan_in(workflow: str, job_name: str) -> None:
    jobs = _jobs(_load(WORKFLOW_DIR / workflow))
    covered = _closure(jobs, job_name)
    orphans = sorted(
        name
        for name in jobs
        if name not in covered
        and name not in {fan for w, fan, _ in FAN_INS if w == workflow}
        and (workflow, name) not in CLOSURE_EXEMPT
    )
    assert not orphans, (
        f"{workflow}: job(s) {orphans} are outside the `needs` closure of the "
        f"fan-in `{job_name}`, so their conclusion never reaches it. The fan-in "
        f"is the context branch protection reads; a job it cannot see fails into "
        f"a green merge. "
        f"fix: add the job to the closure (directly, or through a lane the "
        f"fan-in already waits for), or add it to CLOSURE_EXEMPT with the reason "
        f"it must report separately."
    )


def test_every_closure_exemption_names_a_live_job() -> None:
    """A stale exemption would silently excuse a job that no longer exists."""
    stale = sorted(
        f"{workflow}:{job}"
        for workflow, job in CLOSURE_EXEMPT
        if job not in _jobs(_load(WORKFLOW_DIR / workflow))
    )
    assert not stale, (
        f"CLOSURE_EXEMPT names job(s) that no longer exist: {stale}. "
        f"fix: remove them, or the exemption outlives the job it explains."
    )
