"""Public inventory rejects missing, orphaned and understated obligations."""

import json
import re
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


def test_lab_executes_all_variants_and_retains_actual_outputs(tmp_path):
    result = invoke("lab", "--output", tmp_path / "evidence")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "evidence/results.json").read_text())
    assert report["evidence_mode"] == "compatibility-terminal"
    assert report["generated_render_equal"] is True
    assert {(row["consumer"], row["variant"]) for row in report["cases"]} == {
        (consumer, variant)
        for consumer in ("python", "mixed", "generated")
        for variant in ("compliant", "sabotage")
    }
    for row in report["cases"]:
        assert row["preparation_fixed_point"] is True
        assert {run["phase"] for run in row["evaluations"]} == {"affected", "complete"}
        for run in row["evaluations"]:
            assert run["exit_code"] == (0 if row["variant"] == "compliant" else 1)
            assert run["outputs"]
            assert all(
                (tmp_path / "evidence" / output).is_file() for output in run["outputs"]
            )


def test_fresh_render_rejects_stale_checked_in_consumer(tmp_path):
    import shutil

    root = tmp_path / "pipeline"
    for name in ("governance", "assurance"):
        shutil.copytree(
            ROOT / name, root / name, ignore=shutil.ignore_patterns("__pycache__")
        )
    (root / "assurance/fixtures/generated/rendered/Makefile").write_text("stale\n")
    result = invoke("lab", "--root", root, "--output", tmp_path / "evidence")
    assert result.returncode == 1
    assert "generated-render-drift" in result.stderr


@pytest.mark.parametrize(
    "defect, diagnostic",
    [
        ("preparation", "preparation-not-fixed-point"),
        ("output", "missing-required-output"),
        ("unrelated", "unexpected-exit"),
    ],
)
def test_lab_rejects_actual_preparation_output_and_execution_defects(
    tmp_path, defect, diagnostic
):
    import shutil

    root = tmp_path / "pipeline"
    for name in ("governance", "assurance"):
        shutil.copytree(
            ROOT / name, root / name, ignore=shutil.ignore_patterns("__pycache__")
        )
    if defect == "preparation":
        manifest_path = root / "assurance/consumers.yaml"
        manifest = yaml.safe_load(manifest_path.read_text())
        manifest["consumers"][0]["prepare"].append(
            [
                "python",
                "-c",
                "from pathlib import Path; p=Path('drift.txt'); p.write_text((p.read_text() if p.exists() else '') + 'changed\\n')",
            ]
        )
        manifest_path.write_text(yaml.safe_dump(manifest))
    else:
        project = root / "assurance/fixtures/python/project/pyproject.toml"
        program = (
            "from pathlib import Path; Path('artifacts/coverage.xml').unlink()"
            if defect == "output"
            else "raise SystemExit(7)"
        )
        with project.open("a") as target:
            target.write(
                '\n[[tool.tc_fitness.steps]]\nid = "injected-defect"\nrun = ["python", "-c", '
                + json.dumps(program)
                + "]\n"
            )
    result = invoke("lab", "--root", root, "--output", tmp_path / "evidence")
    assert result.returncode == 1, result.stdout
    assert diagnostic in result.stderr
    report = json.loads((tmp_path / "evidence/results.json").read_text())
    assert report["status"] == "fail"


def test_evidence_attempt_directory_cannot_be_overwritten(tmp_path):
    output = tmp_path / "retained"
    output.mkdir()
    (output / "results.json").write_text("previous failure")
    result = invoke("lab", "--output", output)
    assert result.returncode == 1
    assert (output / "results.json").read_text() == "previous failure"


def test_consumer_manifest_cannot_omit_required_cases(tmp_path):
    import shutil

    root = tmp_path / "pipeline"
    for name in ("governance", "assurance"):
        shutil.copytree(
            ROOT / name, root / name, ignore=shutil.ignore_patterns("__pycache__")
        )
    manifest_path = root / "assurance/consumers.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    manifest["consumers"] = []
    manifest_path.write_text(yaml.safe_dump(manifest))
    result = invoke("lab", "--root", root, "--output", tmp_path / "evidence")
    assert result.returncode == 1, result.stdout
    assert "consumer-manifest" in result.stderr


def test_bootstrap_render_only_runs_without_remote_configuration(tmp_path):
    argv = [
        "bash",
        "-x",
        str(ROOT / "governance/scripts/bootstrap-repo-governance.sh"),
        "--render-only",
        "--repo",
        "three-cubes/assurance-generated",
        "--fitness-tag",
        "v0.15.2",
        "--pipelines-sha",
        "02bc49afcffb7e0d01fc8c2dadc0352791a46046",
        "--out-dir",
    ]
    snapshots = []
    for directory in ("rendered", "again"):
        destination = tmp_path / directory
        result = subprocess.run(
            argv + [str(destination)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        # Execution trace, not source inspection: neither credential/API CLI
        # nor the optional scanner was executed by the real shell process.
        assert not re.search(
            r"^\++ (?:gh|az|detect-secrets) ", result.stderr, re.MULTILINE
        )
        snapshots.append(
            {
                p.relative_to(destination): p.read_bytes()
                for p in destination.rglob("*")
                if p.is_file()
            }
        )
    assert snapshots[0] == snapshots[1]
    assert (
        json.loads((tmp_path / "rendered/.secrets.baseline").read_text())["results"]
        == {}
    )
    assert (tmp_path / "rendered/Makefile").is_file()
