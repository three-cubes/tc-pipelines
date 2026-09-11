"""The local tc-pipelines gate must cover every blocking CI meta leg.

The self-check fan-in combines the reusable meta-quality-gate with the contract
suite.  Running only pytest locally lets an invalid workflow, YAML document,
license, or branch name pass a developer gate then fail in CI.
"""

from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
PYPROJECT = REPO_ROOT / "pyproject.toml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
META_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "meta-quality-gate.yml"

YAMLLINT_CONFIG = "{extends: relaxed, rules: {line-length: disable, document-start: disable}}"
LOCAL_META_STEPS = {
    "actionlint": {"run": ["actionlint", "-color=false"]},
    "yamllint": {
        "run": [
            "yamllint",
            "-d",
            YAMLLINT_CONFIG,
            ".github/workflows",
            "actions",
            ".github/actions",
        ]
    },
    "license": {
        "run": ["bash", "actions/license-present/check-license.sh"],
        "env": {"LICENSE_FILE": "LICENSE", "SPDX_ID": "Apache-2.0"},
    },
    "branch-naming": {"run": ["python", "governance/scripts/check_branch_naming.py"]},
}


def _project_config() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _steps_by_id() -> dict[str, dict]:
    steps = _project_config().get("tool", {}).get("tc_fitness", {}).get("steps", [])
    return {step["id"]: step for step in steps}


def _assert_local_meta_steps() -> dict[str, dict]:
    steps = _steps_by_id()
    for step_id, expected in LOCAL_META_STEPS.items():
        assert steps.get(step_id) == {"id": step_id, "summary": steps.get(step_id, {}).get("summary"), **expected}, (
            f"{PYPROJECT.name}: local `{step_id}` is {steps.get(step_id)!r}, not the "
            f"configured equivalent of CI's `{step_id}` meta leg. fix: declare the "
            "exact local command and environment in [tool.tc_fitness]."
        )
    return steps


def test_each_ci_meta_leg_has_one_local_gate_equivalent() -> None:
    """Deleting a local hygiene step would otherwise leave its CI job unexercised."""
    meta_jobs = (yaml.safe_load(META_WORKFLOW.read_text(encoding="utf-8")) or {}).get("jobs") or {}
    assert set(LOCAL_META_STEPS) <= set(meta_jobs), (
        f"{META_WORKFLOW.name}: expected the four blocking hygiene jobs "
        f"{sorted(LOCAL_META_STEPS)}, found {sorted(meta_jobs)}. fix: update this "
        "parity contract when the reusable meta gate changes."
    )
    ci_meta = ((yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8")) or {}).get("jobs") or {}).get("meta") or {}
    assert ci_meta.get("uses") == "./.github/workflows/meta-quality-gate.yml", (
        f"{CI_WORKFLOW.name}: self-CI no longer calls the local meta gate, so the "
        "local/CI parity mapping has no CI surface to protect."
    )
    _assert_local_meta_steps()


@pytest.mark.parametrize("step_id", sorted(LOCAL_META_STEPS))
def test_each_local_meta_equivalent_rejects_a_bad_input(tmp_path: Path, step_id: str) -> None:
    """Each meta validator must reject the same class of broken input locally."""
    steps = _assert_local_meta_steps()
    step = steps[step_id]
    env = os.environ | {str(key): str(value) for key, value in (step.get("env") or {}).items()}

    if step_id == "actionlint":
        broken = tmp_path / "broken-workflow.yml"
        broken.write_text("name: broken\non: push\njobs: []\n", encoding="utf-8")
        command = [*step["run"], str(broken)]
    elif step_id == "yamllint":
        broken = tmp_path / "broken.yml"
        broken.write_text("broken: [\n", encoding="utf-8")
        command = [*step["run"][:3], str(broken)]
    elif step_id == "license":
        broken = tmp_path / "LICENSE"
        broken.write_text("not a licence\n", encoding="utf-8")
        env["LICENSE_FILE"] = str(broken)
        command = step["run"]
    else:
        command = [*step["run"], "--branch", "not-a-permitted-branch"]

    result = subprocess.run(command, cwd=REPO_ROOT, env=env, check=False, capture_output=True, text=True)
    assert result.returncode != 0, (
        f"local `{step_id}` accepted its sabotaged input. stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )
