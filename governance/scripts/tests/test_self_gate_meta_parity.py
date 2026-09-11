"""The local tc-pipelines gate must cover every blocking CI meta leg.

The self-check fan-in combines the reusable meta-quality-gate with the contract
suite.  Running only pytest locally lets an invalid workflow, YAML document,
license, or branch name pass a developer gate then fail in CI.
"""

from __future__ import annotations

import os
import re
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
ACTIONLINT_VERSION = "1.7.12"
YAMLLINT_VERSION = "1.38.0"
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


def _workflow(path: Path) -> dict:
    """Load a workflow while handling PyYAML's YAML 1.1 ``on`` key."""
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _workflow_call_inputs(workflow: dict) -> dict[str, dict]:
    workflow_on = workflow.get("on", workflow.get(True, {})) or {}
    return (workflow_on.get("workflow_call", {}) or {}).get("inputs", {}) or {}


def _meta_and_caller() -> tuple[dict, dict, dict]:
    meta = _workflow(META_WORKFLOW)
    ci_meta = (_workflow(CI_WORKFLOW).get("jobs") or {}).get("meta") or {}
    return meta, ci_meta, _workflow_call_inputs(meta)


def _effective_meta_inputs(inputs: dict[str, dict], caller: dict) -> dict[str, object]:
    values = {name: definition.get("default") for name, definition in inputs.items()}
    values.update(caller.get("with") or {})
    return values


def _run_body(job: dict) -> str:
    run_steps = [step["run"] for step in job.get("steps", []) if "run" in step]
    assert len(run_steps) == 1, f"expected exactly one shell body, found {run_steps!r}"
    return run_steps[0]


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
    """The self caller must enable exactly the meta legs the local gate runs."""
    meta, ci_meta, inputs = _meta_and_caller()
    meta_jobs = meta.get("jobs") or {}
    expected_jobs = {*LOCAL_META_STEPS, "no-attribution"}
    assert set(meta_jobs) == expected_jobs, (
        f"{META_WORKFLOW.name}: expected exactly {sorted(expected_jobs)}, found "
        f"{sorted(meta_jobs)}. update the local gate and this parity contract together."
    )
    assert ci_meta.get("uses") == "./.github/workflows/meta-quality-gate.yml", (
        f"{CI_WORKFLOW.name}: self-CI no longer calls the local meta gate, so the "
        "local/CI parity mapping has no CI surface to protect."
    )
    effective_inputs = _effective_meta_inputs(inputs, ci_meta)
    enabled_jobs = set()
    for job_id, job in meta_jobs.items():
        condition = str(job.get("if", ""))
        match = re.fullmatch(r"(?:\$\{\{\s*)?inputs\.([a-z0-9-]+)(?:\s*\}\})?", condition)
        assert match, f"{META_WORKFLOW.name}: {job_id} must use a direct input toggle, got {condition!r}"
        if effective_inputs[match.group(1)] is True:
            enabled_jobs.add(job_id)
    assert enabled_jobs == set(LOCAL_META_STEPS), (
        f"{CI_WORKFLOW.name}: enabled meta jobs are {sorted(enabled_jobs)}, not the "
        f"exact local equivalents {sorted(LOCAL_META_STEPS)}."
    )
    _assert_local_meta_steps()


def test_ci_meta_tools_are_pinned_to_the_local_tool_versions() -> None:
    """CI must not silently drift while the local fitness dependencies are locked."""
    meta, ci_meta, inputs = _meta_and_caller()
    caller_inputs = ci_meta.get("with") or {}

    assert inputs["actionlint-version"].get("default") == ACTIONLINT_VERSION
    assert inputs["yamllint-version"].get("default") == YAMLLINT_VERSION
    assert caller_inputs.get("actionlint-version") == ACTIONLINT_VERSION
    assert caller_inputs.get("yamllint-version") == YAMLLINT_VERSION
    assert caller_inputs.get("yamllint-config") == YAMLLINT_CONFIG
    assert caller_inputs.get("yamllint-paths") == ".github/workflows actions .github/actions"

    actionlint_job = meta["jobs"]["actionlint"]
    actionlint_body = _run_body(actionlint_job)
    assert (actionlint_job.get("steps") or [])[-1].get("env", {}).get("ACTIONLINT_VERSION") == "${{ inputs.actionlint-version }}"
    assert "raw.githubusercontent.com/rhysd/actionlint/v${ACTIONLINT_VERSION}/" in actionlint_body
    assert '"$ACTIONLINT_VERSION" .' in actionlint_body
    assert "/main/" not in actionlint_body

    yamllint_job = meta["jobs"]["yamllint"]
    yamllint_body = _run_body(yamllint_job)
    assert (yamllint_job.get("steps") or [])[-1].get("env", {}).get("YAMLLINT_VERSION") == "${{ inputs.yamllint-version }}"
    assert 'pipx install "yamllint==${YAMLLINT_VERSION}"' in yamllint_body

    dev_dependencies = _project_config()["dependency-groups"]["dev"]
    assert "actionlint-py==1.7.12.24" in dev_dependencies
    assert "yamllint==1.38.0" in dev_dependencies


def test_ci_meta_lint_bodies_execute_the_configured_local_argv() -> None:
    """Installation alone is not parity: the reusable must run both linters."""
    meta, ci_meta, _ = _meta_and_caller()
    caller_inputs = ci_meta.get("with") or {}

    actionlint_body = _run_body(meta["jobs"]["actionlint"])
    assert "./actionlint -color" in actionlint_body.splitlines(), (
        f"{META_WORKFLOW.name}: actionlint must execute `./actionlint -color`, not only install it."
    )

    yamllint_body = _run_body(meta["jobs"]["yamllint"])
    assert 'yamllint -d "$YAMLLINT_CONFIG" $YAMLLINT_PATHS' in yamllint_body.splitlines(), (
        f"{META_WORKFLOW.name}: yamllint must execute its env-bound config and path argv."
    )
    assert caller_inputs["yamllint-config"] == YAMLLINT_CONFIG
    assert caller_inputs["yamllint-paths"].split() == LOCAL_META_STEPS["yamllint"]["run"][3:]


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


@pytest.mark.parametrize(
    ("contents", "expected"),
    [
        ("SPDX-License-Identifier: Apache-2.0\n", 0),
        ("Apache License\nVersion 2.0\n", 0),
        ("SPDX-License-Identifier: MIT\n", 1),
        ("not a licence\n", 1),
        (None, 1),
    ],
)
def test_license_ci_body_matches_the_local_canonical_command(
    tmp_path: Path, contents: str | None, expected: int
) -> None:
    """Run the reusable's exact shell body against pass and fail licence inputs."""
    meta, _, _ = _meta_and_caller()
    license_file = tmp_path / "LICENSE"
    if contents is not None:
        license_file.write_text(contents, encoding="utf-8")
    env = os.environ | {"LICENSE_FILE": str(license_file), "SPDX_ID": "Apache-2.0"}
    ci_result = subprocess.run(
        ["bash", "-c", _run_body(meta["jobs"]["license"])],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    local_result = subprocess.run(
        LOCAL_META_STEPS["license"]["run"],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert ci_result.returncode == local_result.returncode == expected, (
        f"CI={ci_result.returncode}: {ci_result.stderr}\nlocal={local_result.returncode}: "
        f"{local_result.stderr}"
    )


@pytest.mark.parametrize(
    ("branch", "expected"),
    [
        ("dan/exe-90-gate-parity", 0),
        ("alice/feature", 0),
        ("main", 0),
        ("develop", 0),
        ("HEAD", 0),
        ("gh-pages", 0),
        ("worktree-agent-parity", 0),
        ("renovate/actions-checkout-6", 0),
        ("dependabot/pip/pytest-9", 0),
        ("", 0),
        ("not-a-permitted-branch", 1),
        ("Dan/not-lowercase", 1),
    ],
)
def test_branch_ci_body_matches_the_local_canonical_adapter(branch: str, expected: int) -> None:
    """Run the reusable's exact shell body against pass and fail branch inputs."""
    meta, _, inputs = _meta_and_caller()
    env = os.environ | {
        "BRANCH_NAME": branch,
        "BRANCH_PATTERN": str(inputs["branch-name-pattern"]["default"]),
    }
    ci_result = subprocess.run(
        ["bash", "-c", _run_body(meta["jobs"]["branch-naming"])],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    local_result = subprocess.run(
        [*LOCAL_META_STEPS["branch-naming"]["run"], "--branch", branch],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert ci_result.returncode == local_result.returncode == expected, (
        f"CI={ci_result.returncode}: {ci_result.stderr}\nlocal={local_result.returncode}: "
        f"{local_result.stderr}"
    )
