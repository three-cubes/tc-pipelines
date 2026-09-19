"""Contract controls for trusted preparation topology."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.contract


def _steps(path: Path, job: str) -> list[dict]:
    return yaml.safe_load(path.read_text())["jobs"][job]["steps"]


def test_quality_checkout_is_bound_to_the_pr_head_not_the_merge_candidate() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/python-quality-gate.yml").read_text()
    )
    assert "candidate-head-sha" not in workflow[True]["workflow_call"]["inputs"]
    preparation = workflow["jobs"]["preparation"]
    assert preparation["outputs"]["candidate-head-sha"] == (
        "${{ steps.candidate.outputs.sha }}"
    )
    candidate = next(
        step for step in preparation["steps"] if step.get("id") == "candidate"
    )
    assert "github.event.pull_request.head.sha" in candidate["env"]["EVENT_HEAD"]
    assert "REQUESTED_HEAD" not in candidate["env"]
    action = yaml.safe_load((ROOT / "actions/python-gate-body/action.yml").read_text())
    assert action["inputs"]["candidate-head-sha"]["required"] is True
    checkout = next(
        step for step in action["runs"]["steps"] if step["name"] == "Checkout"
    )
    assert checkout["with"]["ref"] == "${{ inputs.candidate-head-sha }}"
    for name in ("quality", "quality-shard", "quality-non-shard"):
        step = next(
            step
            for step in workflow["jobs"][name]["steps"]
            if "python-gate-body" in step.get("uses", "")
        )
        assert step["with"]["candidate-head-sha"] == (
            "${{ needs.preparation.outputs.candidate-head-sha }}"
        )


def test_preparation_uses_only_the_closed_trusted_ruff_policy() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/python-quality-gate.yml").read_text()
    )
    assert "pre-evaluation-normalize" not in str(workflow)
    prepare = next(
        step
        for step in workflow["jobs"]["preparation"]["steps"]
        if step["name"] == "Prepare candidate"
    )
    assert "ruff check --force-exclude --select E,F,I,UP,B,S,RUF" in prepare["run"]
    assert "--ignore E501,RUF022 --fix --no-unsafe-fixes --exit-zero" in prepare["run"]
    assert (
        "ruff format --force-exclude --line-length 110 --target-version py312"
        in prepare["run"]
    )
    assert prepare["run"].count("uvx --from ruff==0.16.8 ruff") == 2
    names = [step.get("name") for step in workflow["jobs"]["preparation"]["steps"]]
    assert "Install trusted uv for formatter preparation" in names
    assert "Locked uv install" not in names
    assert "pnpm install" not in names


def test_writer_bootstraps_private_tools_and_uses_only_the_fixed_policy() -> None:
    path = ROOT / ".github/workflows/preparation-writeback.yml"
    steps = _steps(path, "write-preparation")
    bootstrap = next(step for step in steps if step.get("id") == "bootstrap")
    assert "github-app-token@" in bootstrap["uses"]
    checkout = next(
        step for step in steps if step["name"] == "Checkout trusted receipt validator"
    )
    assert checkout["with"]["token"] == "${{ steps.bootstrap.outputs.token }}"
    assert checkout["with"]["ref"] == "${{ inputs.trusted-validator-ref }}"
    apply = next(step for step in steps if step.get("id") == "apply")
    assert '--expected-policy "python-ruff-v1"' in apply["run"]


def test_tc_pipelines_uses_its_local_writer_but_consumer_template_keeps_a_pin() -> None:
    local = yaml.safe_load((ROOT / ".github/workflows/auto-merge.yml").read_text())
    template = yaml.safe_load(
        (ROOT / "governance/skeletons/workflows/auto-merge.yml.tmpl").read_text()
    )
    assert local["jobs"]["preparation-writeback"]["uses"] == (
        "./.github/workflows/preparation-writeback.yml"
    )
    assert (
        local["jobs"]["preparation-writeback"]["with"]["trusted-validator-ref"]
        == "${{ github.sha }}"
    )
    assert "@{{PIPELINES_SHA}}" in template["jobs"]["preparation-writeback"]["uses"]
    assert (
        template["jobs"]["preparation-writeback"]["with"]["trusted-validator-ref"]
        == "{{PIPELINES_SHA}}"
    )
