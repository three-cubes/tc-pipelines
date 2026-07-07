"""Contract tests for Azure run-command message failure detection."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "governance" / "scripts" / "run_command_output_gate.py"
ACTION = REPO_ROOT / ".github" / "actions" / "apply-on-vm-via-runcommand" / "action.yml"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "azure-vm-deploy.yml"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_command_output_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _message(stdout: str = "", stderr: str = "") -> str:
    return f"""Enable succeeded:
[stdout]
{stdout}

[stderr]
{stderr}
"""


@pytest.mark.parametrize(
    "stderr",
    [
        "/bin/sh: 2: set: Illegal option -o pipefail",
        "bash: deploy/apply.sh: command not found",
        "fatal: not a git repository",
        "Traceback (most recent call last):",
        "Permission denied",
    ],
)
def test_fatal_stderr_markers_fail(stderr: str) -> None:
    module = _load_module()

    result = module.classify_run_command_message(_message(stdout="ok", stderr=stderr))

    assert result.failed is True
    assert result.matches


def test_failure_markers_in_stdout_fail() -> None:
    module = _load_module()

    result = module.classify_run_command_message(_message(stdout="ERROR: apply failed"))

    assert result.failed is True
    assert "ERROR:" in result.matches[0]


@pytest.mark.parametrize(
    "stderr",
    [
        "",
        "Already on 'main'",
        "Switched to branch 'main'",
    ],
)
def test_benign_azure_message_passes(stderr: str) -> None:
    module = _load_module()

    result = module.classify_run_command_message(_message(stdout="apply completed", stderr=stderr))

    assert result.failed is False
    assert result.matches == []


def test_composite_action_uses_shared_run_command_output_gate() -> None:
    text = ACTION.read_text(encoding="utf-8")

    assert "governance/scripts/run_command_output_gate.py" in text
    assert "value[0].message" in text
    assert "FAIL_ON_ERR" in text


def test_reusable_workflow_gates_apply_message_before_smoke() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    gate_definition = text.find("gate_run_command_output()")
    gate_call = text.find('gate_run_command_output "$VM" "$MSG_FILE"')
    smoke = text.find("=== Smoke ${VM}")

    assert gate_definition != -1
    assert gate_call != -1
    assert smoke != -1
    assert gate_definition < gate_call < smoke
    assert "Illegal option -o pipefail" in text
    assert "Traceback \\(most recent call last\\):" in text
