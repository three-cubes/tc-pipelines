"""The hosted gate prepares one candidate before any evaluator observes it.

The preparation producer may emit an identity-bound patch for the existing
post-CI workflow to write back.  That original candidate must not receive the
required green context, and the post-CI workflow must never arm auto-merge in
the same run that writes a new head.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github" / "workflows"
SKELETONS = ROOT / "governance" / "skeletons" / "workflows"
GATE = WORKFLOWS / "python-quality-gate.yml"
EVALUATOR_JOBS = ("quality", "quality-shard", "quality-non-shard", "coverage-combine")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _needs(job: dict) -> list[str]:
    value = job.get("needs") or []
    return [value] if isinstance(value, str) else list(value)


def _steps(job: dict) -> list[dict]:
    return [step for step in job.get("steps", []) if isinstance(step, dict)]


def _workflow_outputs(document: dict) -> dict:
    trigger = document.get(True) or document.get("on") or {}
    return ((trigger.get("workflow_call") or {}).get("outputs")) or {}


def test_reusable_exposes_whether_exact_candidate_evaluation_ran() -> None:
    gate = _load(GATE)
    output = _workflow_outputs(gate)["evaluated"]
    assert output["value"] == "${{ jobs.gate.outputs.evaluated }}"
    assert gate["jobs"]["gate"]["outputs"]["evaluated"] == ("${{ steps.aggregate.outputs.evaluated }}")


def test_one_preparation_job_dominates_every_evaluator() -> None:
    jobs = _load(GATE)["jobs"]
    preparation = jobs["preparation"]
    assert "evaluated" in preparation["outputs"]
    assert "receipt-created" in preparation["outputs"]

    for name in EVALUATOR_JOBS:
        job = jobs[name]
        assert "preparation" in _needs(job), f"{name} can run before preparation"
        condition = str(job.get("if", ""))
        assert "needs.preparation.outputs.evaluated == 'true'" in condition, (
            f"{name} can evaluate a candidate that preparation changed"
        )

    detect = jobs["detect-changes"]
    assert "preparation" in _needs(detect)
    assert "needs.preparation.outputs.evaluated == 'true'" in str(detect.get("if", ""))


def test_quality_lanes_do_not_repeat_the_trusted_preparation_policy() -> None:
    gate = _load(GATE)
    body_calls = [
        step
        for name in ("quality", "quality-shard", "quality-non-shard")
        for step in _steps(gate["jobs"][name])
        if "python-gate-body" in str(step.get("uses", ""))
    ]
    assert len(body_calls) == 3
    assert all("candidate-head-sha" in step["with"] for step in body_calls)

    combine_names = {step.get("name") for step in _steps(gate["jobs"]["coverage-combine"])}
    assert "Prepare candidate" not in combine_names
    preparation = gate["jobs"]["preparation"]
    prepare = next(step for step in _steps(preparation) if step["name"] == "Prepare candidate")
    assert prepare["uses"].startswith("three-cubes/tc-pipelines/actions/python-preparation@")
    assert prepare["with"] == {
        "uv-version": "${{ inputs.uv-version }}",
        "preparation-command": "${{ inputs.preparation-command }}",
    }


@pytest.mark.parametrize(
    "path",
    [SKELETONS / "ci.yml.tmpl"],
)
def test_required_context_is_explicitly_red_when_preparation_changed_the_pr(
    path: Path,
) -> None:
    jobs = _load(path)["jobs"]
    check = jobs["check"]
    assert "gate" in _needs(check)
    assert str(check.get("if", "")) == "always()"
    step = next(step for step in _steps(check) if step.get("name") == "Gate on the reusable result")
    assert step["env"]["EVALUATED"] == "${{ needs.gate.outputs.evaluated }}"
    assert '[[ "$EVALUATED" == "true" ]]' in step["run"]
    assert "exit 1" in step["run"]


@pytest.mark.parametrize(
    "path",
    [WORKFLOWS / "auto-merge.yml", SKELETONS / "auto-merge.yml.tmpl"],
)
def test_existing_post_ci_run_writes_preparation_before_considering_merge(
    path: Path,
) -> None:
    jobs = _load(path)["jobs"]
    writeback = jobs["preparation-writeback"]
    assert "preparation-writeback.yml" in str(writeback.get("uses", ""))

    merge = jobs["merge"]
    assert "preparation-writeback" in _needs(merge)
    condition = str(merge.get("if", ""))
    assert "needs.preparation-writeback.result == 'success'" in condition
    assert "needs.preparation-writeback.outputs.result == 'no-artifact'" in condition


def test_writeback_result_protocol_is_explicit() -> None:
    workflow = _load(WORKFLOWS / "preparation-writeback.yml")
    result = _workflow_outputs(workflow)["result"]
    assert result["value"] == "${{ jobs.write-preparation.outputs.result }}"
    assert {"changed", "no-artifact", "ineligible"}.issubset(
        {
            value
            for line in (WORKFLOWS / "preparation-writeback.yml").read_text(encoding="utf-8").splitlines()
            if (value := line.strip().removeprefix("result=")) != line.strip()
        }
    )


def test_private_fetch_receives_the_ephemeral_read_token_in_its_own_step() -> None:
    workflow = _load(WORKFLOWS / "preparation-writeback.yml")
    steps = _steps(workflow["jobs"]["write-preparation"])
    fetch = next(step for step in steps if step.get("name") == "Validate and apply without executing PR code")
    assert "preparation_writeback.py fetch" in fetch["run"]
    assert fetch["env"]["GITHUB_READ_TOKEN"] == "${{ github.token }}"
