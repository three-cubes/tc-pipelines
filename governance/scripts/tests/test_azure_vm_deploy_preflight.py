"""Contract tests for the reusable Azure VM deploy preflight boundary."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "azure-vm-deploy.yml"
SNAPSHOT_ACTION = (
    REPO_ROOT / ".github" / "actions" / "snapshot-azure-vm-disk" / "action.yml"
)


class GithubActionsLoader(yaml.SafeLoader):
    """Keep the YAML 1.1 parser from coercing the GitHub Actions `on` key."""


GithubActionsLoader.yaml_implicit_resolvers = {
    key: [
        (tag, pattern)
        for tag, pattern in resolvers
        if tag != "tag:yaml.org,2002:bool"
    ]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def _workflow() -> dict:
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=GithubActionsLoader)


def _step(name: str) -> dict:
    return next(
        step
        for step in _workflow()["jobs"]["deploy"]["steps"]
        if step.get("name") == name
    )


@pytest.fixture
def fake_remote_tools(tmp_path: Path) -> tuple[Path, Path]:
    """Execute the workflow's generated remote script behind fake Azure/yq CLIs."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    remote_script = tmp_path / "remote-script"

    yq = bin_dir / "yq"
    yq.write_text(
        """#!/usr/bin/env bash
case "$1" in
  length) echo 1 ;;
  '.[0].vm-name') echo vm-test ;;
  *) echo "unexpected yq expression: $1" >&2; exit 2 ;;
esac
""",
        encoding="utf-8",
    )
    az = bin_dir / "az"
    az.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
remote_script=""
while [[ $# -gt 0 ]]; do
  if [[ "$1" == "--scripts" ]]; then
    remote_script="$2"
    shift 2
    continue
  fi
  shift
done
printf '%s' "$remote_script" >"$FAKE_REMOTE_SCRIPT"
set +e
output=$(/bin/sh -c "$remote_script" 2>&1)
set -e
printf 'Enable succeeded:\n[stdout]\n%s\n[stderr]\n' "$output"
""",
        encoding="utf-8",
    )
    for executable in (yq, az):
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return bin_dir, remote_script


def _run_remote_step(
    tmp_path: Path,
    fake_remote_tools: tuple[Path, Path],
    *,
    step_name: str,
    script_env_name: str,
    payload: str,
) -> subprocess.CompletedProcess[str]:
    bin_dir, _ = fake_remote_tools
    runner_script = tmp_path / f"{step_name.lower().replace(' ', '-')}.sh"
    runner_script.write_text(_step(step_name)["run"], encoding="utf-8")
    github_output = tmp_path / "github-output"
    github_output.touch()
    env = os.environ.copy()
    env.update(
        {
            "GITHUB_OUTPUT": str(github_output),
            "GITHUB_RUN_ID": "123456",
            "FAKE_REMOTE_SCRIPT": str(fake_remote_tools[1]),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "RG": "rg-test",
            script_env_name: payload,
            "TARGETS_YAML": "- vm-name: vm-test\n",
        }
    )
    return subprocess.run(
        ["bash", str(runner_script)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_remote_preflight_is_before_snapshot_and_apply() -> None:
    workflow = _workflow()
    steps = workflow["jobs"]["deploy"]["steps"]
    names = [step.get("name", "") for step in steps]

    assert names.index("Remote preflight") < names.index("Snapshot all VMs")
    assert names.index("Snapshot all VMs") < names.index("Apply on each target + smoke")


def test_preflight_and_cleanup_are_optional_additive_inputs() -> None:
    inputs = _workflow()["on"]["workflow_call"]["inputs"]

    assert inputs["preflight-script"]["required"] in {False, "false"}
    assert inputs["preflight-script"]["default"] == ""
    assert inputs["failure-cleanup-script"]["required"] in {False, "false"}
    assert inputs["failure-cleanup-script"]["default"] == ""


def test_workflow_surfaces_preflight_and_snapshot_evidence() -> None:
    outputs = _workflow()["jobs"]["deploy"]["outputs"]

    assert outputs["preflight-status"] == "${{ steps.preflight.outputs.status }}"
    assert outputs["preflight-receipt-digest"] == (
        "${{ steps.preflight.outputs.receipt-digest }}"
    )
    assert outputs["snapshot-resource-id"] == (
        "${{ steps.snapshot.outputs.snapshot-resource-ids }}"
    )


def test_failure_cleanup_runs_after_any_preflight_attempt_when_later_work_fails() -> None:
    steps = _workflow()["jobs"]["deploy"]["steps"]
    preflight = next(step for step in steps if step.get("name") == "Remote preflight")
    cleanup = next(step for step in steps if step.get("name") == "Failure cleanup")

    assert "cleanup-required=false" in preflight["run"]
    assert "cleanup-required=true" in preflight["run"]
    assert "always()" in cleanup["if"]
    assert "failure() || cancelled()" in cleanup["if"]
    assert "steps.preflight.outputs.cleanup-required == 'true'" in cleanup["if"]
    assert "steps.preflight.outputs.status == 'passed'" not in cleanup["if"]
    assert "inputs.failure-cleanup-script != ''" in cleanup["if"]
    assert "CLEANUP_FAILED=1" in cleanup["run"]
    assert "TC_CLEANUP_REMOTE_SUCCESS_" in cleanup["run"]


@pytest.mark.parametrize("suffix", ["\n", "\n# terminal comment"])
def test_successful_multiline_preflight_reaches_remote_success_proof(
    tmp_path: Path,
    fake_remote_tools: tuple[Path, Path],
    suffix: str,
) -> None:
    receipt = f"sha256:{'a' * 64}"
    payload = f"printf '%s\\n' 'PREFLIGHT_RECEIPT_DIGEST={receipt}'{suffix}"

    result = _run_remote_step(
        tmp_path,
        fake_remote_tools,
        step_name="Remote preflight",
        script_env_name="PREFLIGHT_SCRIPT",
        payload=payload,
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("payload", ["true\n", "true\n# terminal comment"])
def test_successful_multiline_failure_cleanup_reaches_remote_success_proof(
    tmp_path: Path,
    fake_remote_tools: tuple[Path, Path],
    payload: str,
) -> None:
    result = _run_remote_step(
        tmp_path,
        fake_remote_tools,
        step_name="Failure cleanup",
        script_env_name="CLEANUP_SCRIPT",
        payload=payload,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_preflight_requires_one_content_addressed_receipt_marker() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    preflight = next(
        step
        for step in _workflow()["jobs"]["deploy"]["steps"]
        if step.get("name") == "Remote preflight"
    )["run"]

    assert "PREFLIGHT_RECEIPT_DIGEST=sha256:" in text
    assert "preflight produced no valid receipt digest" in text
    assert "preflight produced multiple receipt digests" in text
    assert "TC_PREFLIGHT_REMOTE_SUCCESS_" in text
    assert "did not prove success" in text
    assert "run_with_retry" in text
    assert preflight.count('echo "receipt-digest=${RECEIPTS[0]}"') == 1
    assert preflight.index("preflight produced multiple receipt digests") < preflight.index(
        'echo "receipt-digest=${RECEIPTS[0]}"'
    )


def test_terminal_conflict_does_not_sleep_before_failure() -> None:
    steps = _workflow()["jobs"]["deploy"]["steps"]
    preflight = next(step for step in steps if step.get("name") == "Remote preflight")[
        "run"
    ]
    cleanup = next(step for step in steps if step.get("name") == "Failure cleanup")[
        "run"
    ]

    for script in (preflight, cleanup):
        terminal_guard = "if (( attempt >= max_attempts )); then"
        assert terminal_guard in script
        assert script.index(terminal_guard) < script.index('sleep "$wait_seconds"')


def test_snapshot_standard_documents_reversible_preflight_path() -> None:
    standard = (
        REPO_ROOT / "governance" / "standards" / "snapshot-before-apply.md"
    ).read_text(encoding="utf-8")

    assert "Reversible pre-snapshot admission path" in standard
    assert "Keep preflight to writer freezes and lease acquisition" in standard
    assert "partial preflight" in standard
    assert "failure or cancellation" in standard


def test_snapshot_action_surfaces_created_resource_ids() -> None:
    action = yaml.load(
        SNAPSHOT_ACTION.read_text(encoding="utf-8"), Loader=GithubActionsLoader
    )

    assert action["outputs"]["snapshot-resource-ids"]["value"] == (
        "${{ steps.snap.outputs.snapshot-resource-ids }}"
    )


def test_snapshot_lifecycle_is_incremental_and_tagged_for_the_48_hour_pruner() -> None:
    action = yaml.load(
        SNAPSHOT_ACTION.read_text(encoding="utf-8"), Loader=GithubActionsLoader
    )
    step = action["runs"]["steps"][0]
    workflow_inputs = _workflow()["on"]["workflow_call"]["inputs"]

    assert action["inputs"]["retention-hours"]["default"] == "48"
    assert action["outputs"]["snapshot-expires-at"]["value"] == (
        "${{ steps.snap.outputs.snapshot-expires-at }}"
    )
    assert workflow_inputs["snapshot-retention-hours"]["default"] == "48"
    assert "retention-hours: ${{ inputs.snapshot-retention-hours }}" in WORKFLOW.read_text(
        encoding="utf-8"
    )
    assert "--incremental true" in step["run"]
    for tag in (
        "tc-managed-by=tc-pipelines",
        "tc-purpose=pre-deploy-recovery",
        "tc-source-vm=${vm}",
        "tc-created-at=${CREATED_AT}",
        "tc-expires-at=${EXPIRES_AT}",
    ):
        assert tag in step["run"]
    assert "retention-hours must be a positive whole number of hours" in step["run"]
    run = action["runs"]["steps"][0]["run"]
    assert "--query '{state:provisioningState,id:id}'" in run
    assert "snapshot-resource-ids<<EOF" in run
    assert "trap publish_outputs EXIT" in run
