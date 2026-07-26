"""Contract tests for the reusable Azure VM deploy preflight boundary."""

from __future__ import annotations

from pathlib import Path

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


def test_failure_cleanup_runs_after_preflight_when_snapshot_or_apply_fails() -> None:
    steps = _workflow()["jobs"]["deploy"]["steps"]
    cleanup = next(step for step in steps if step.get("name") == "Failure cleanup")

    assert "always()" in cleanup["if"]
    assert "failure() || cancelled()" in cleanup["if"]
    assert "steps.preflight.outputs.status == 'passed'" in cleanup["if"]
    assert "inputs.failure-cleanup-script != ''" in cleanup["if"]
    assert "CLEANUP_FAILED=1" in cleanup["run"]
    assert "TC_CLEANUP_REMOTE_SUCCESS_" in cleanup["run"]


def test_preflight_requires_one_content_addressed_receipt_marker() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "PREFLIGHT_RECEIPT_DIGEST=sha256:" in text
    assert "preflight produced no valid receipt digest" in text
    assert "preflight produced multiple receipt digests" in text
    assert "TC_PREFLIGHT_REMOTE_SUCCESS_" in text
    assert "did not prove success" in text
    assert "run_with_retry" in text


def test_snapshot_action_surfaces_created_resource_ids() -> None:
    action = yaml.load(
        SNAPSHOT_ACTION.read_text(encoding="utf-8"), Loader=GithubActionsLoader
    )

    assert action["outputs"]["snapshot-resource-ids"]["value"] == (
        "${{ steps.snap.outputs.snapshot-resource-ids }}"
    )
    run = action["runs"]["steps"][0]["run"]
    assert "--query '{state:provisioningState,id:id}'" in run
    assert "snapshot-resource-ids<<EOF" in run
    assert "trap publish_outputs EXIT" in run
