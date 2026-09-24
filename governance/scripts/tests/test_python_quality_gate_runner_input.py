"""Contract tests for reusable Python quality-gate runner selection."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "python-quality-gate.yml"

pytestmark = pytest.mark.contract


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_runner_input_is_optional_and_defaults_to_ubuntu_latest() -> None:
    workflow = _workflow()
    trigger = workflow.get("on") or workflow[True]
    spec = trigger["workflow_call"]["inputs"]["runs-on"]

    assert spec["type"] == "string"
    assert spec["default"] == "ubuntu-latest"
    assert spec.get("required", False) is False


def test_every_job_uses_the_selected_runner() -> None:
    jobs = _workflow()["jobs"]

    assert jobs
    assert all(job["runs-on"] == "${{ inputs.runs-on }}" for job in jobs.values())
