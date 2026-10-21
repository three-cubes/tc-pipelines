"""Public inventory rejects missing, orphaned and understated obligations."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / "assurance/run.py"


def invoke(*args):
    return subprocess.run(
        [sys.executable, str(CLI), *map(str, args)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def surface_repo(tmp_path):
    workflow = tmp_path / ".github/workflows/gate.yaml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("on: {workflow_call: {}}\njobs: {}\n")
    action = tmp_path / "actions/check/action.yml"
    action.parent.mkdir(parents=True)
    action.write_text("runs: {using: composite, steps: []}\n")
    return tmp_path


def write_inventory(root, entries):
    folder = root / "assurance"
    folder.mkdir(exist_ok=True)
    (folder / "surfaces.yaml").write_text(
        yaml.safe_dump(
            {
                "schema": "tc.sdlc/surface-assurance/v1",
                "surfaces": entries,
            }
        )
    )


def entry(identity, path):
    return {
        "id": identity,
        "path": path,
        "risk": "control-plane",
        "required": {
            "pr": ["structural", "hermetic"],
            "release": ["structural", "hermetic", "hosted"],
        },
        "evidence": {"structural": [], "hermetic": [], "hosted": []},
        "sabotage": ["missing-required-output"],
    }


def test_discovery_includes_only_callable_workflows_and_composites(tmp_path):
    root = surface_repo(tmp_path)
    (root / ".github/workflows/private.yml").write_text("on: push\njobs: {}\n")
    result = invoke("discover", "--root", root)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        {"id": "workflow.gate", "path": ".github/workflows/gate.yaml"},
        {"id": "action.actions.check", "path": "actions/check/action.yml"},
    ]


@pytest.mark.parametrize("events", ["workflow_call", "[push, workflow_call]"])
def test_discovery_cannot_miss_short_form_workflow_call(tmp_path, events):
    root = surface_repo(tmp_path)
    (root / ".github/workflows/gate.yaml").write_text(f"on: {events}\njobs: {{}}\n")
    result = invoke("discover", "--root", root)
    assert result.returncode == 0, result.stderr
    assert {row["id"] for row in json.loads(result.stdout)} == {
        "workflow.gate",
        "action.actions.check",
    }


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "orphan",
        "duplicate",
        "wrong-id",
        "understated",
        "noncumulative",
        "bad-reference",
    ],
)
def test_inventory_rejects_incomplete_or_downgraded_contract(tmp_path, defect):
    root = surface_repo(tmp_path)
    entries = [
        entry("workflow.gate", ".github/workflows/gate.yaml"),
        entry("action.actions.check", "actions/check/action.yml"),
    ]
    if defect == "missing":
        entries.pop()
    elif defect == "orphan":
        entries.append(entry("workflow.orphan", ".github/workflows/orphan.yml"))
    elif defect == "duplicate":
        entries.append(entries[0])
    elif defect == "wrong-id":
        entries[0]["id"] = "workflow.other"
    elif defect == "understated":
        entries[0]["required"]["pr"] = ["structural"]
    elif defect == "noncumulative":
        entries[0]["required"]["release"] = ["hosted"]
    else:
        entries[0]["evidence"]["structural"] = ["missing.py"]
    write_inventory(root, entries)
    result = invoke("inventory", "--root", root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "inventory:" in result.stderr


def test_inventory_reports_declared_requirements_without_claiming_execution(tmp_path):
    root = surface_repo(tmp_path)
    write_inventory(
        root,
        [
            entry("workflow.gate", ".github/workflows/gate.yaml"),
            entry("action.actions.check", "actions/check/action.yml"),
        ],
    )
    result = invoke("inventory", "--root", root)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["evidence_produced"] == ["structural"]


def test_checked_in_public_inventory_is_exact():
    result = invoke("inventory")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("command", ["prepare", "all"])
def test_the_public_makefile_entry_points_still_run(command):
    result = invoke(
        command, "--output", "/nonexistent/ignored", "--fitness-wheel", "/nonexistent/ignored.whl"
    )
    assert result.returncode == 0, result.stderr
