"""Public inventory rejects missing, orphaned and understated obligations."""

import importlib.util
import json
import os
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
            assert all((tmp_path / "evidence" / output).is_file() for output in run["outputs"])


def test_fresh_render_rejects_stale_checked_in_consumer(tmp_path):
    import shutil

    root = tmp_path / "pipeline"
    for name in ("governance", "assurance"):
        shutil.copytree(ROOT / name, root / name, ignore=shutil.ignore_patterns("__pycache__"))
    (root / "assurance/fixtures/generated/rendered/Makefile").write_text("stale\n")
    result = invoke("lab", "--root", root, "--output", tmp_path / "evidence")
    assert result.returncode == 1
    assert "generated-render-drift" in result.stderr


def test_prepare_refreshes_generated_consumer_and_reaches_a_fixed_point(tmp_path):
    import shutil

    root = tmp_path / "pipeline"
    for name in ("governance", "assurance"):
        shutil.copytree(ROOT / name, root / name, ignore=shutil.ignore_patterns("__pycache__"))
    generated = root / "assurance/fixtures/generated/rendered"
    (generated / "Makefile").write_text("stale\n")

    first = invoke("prepare", "--root", root)
    assert first.returncode == 0, first.stderr
    assert (generated / "Makefile").read_text() != "stale\n"
    first_tree = {
        path.relative_to(generated): (path.read_bytes(), path.stat().st_mode & 0o777)
        for path in generated.rglob("*")
        if path.is_file()
    }

    second = invoke("prepare", "--root", root)
    assert second.returncode == 0, second.stderr
    assert {
        path.relative_to(generated): (path.read_bytes(), path.stat().st_mode & 0o777)
        for path in generated.rglob("*")
        if path.is_file()
    } == first_tree


@pytest.mark.parametrize(
    "defect, diagnostic",
    [
        ("preparation", "preparation-not-fixed-point"),
        ("output", "missing-required-output"),
        ("unrelated", "unexpected-exit"),
    ],
)
def test_lab_rejects_actual_preparation_output_and_execution_defects(tmp_path, defect, diagnostic):
    import shutil

    root = tmp_path / "pipeline"
    for name in ("governance", "assurance"):
        shutil.copytree(ROOT / name, root / name, ignore=shutil.ignore_patterns("__pycache__"))
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
        shutil.copytree(ROOT / name, root / name, ignore=shutil.ignore_patterns("__pycache__"))
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
        assert not re.search(r"^\++ (?:gh|az|detect-secrets) ", result.stderr, re.MULTILINE)
        snapshots.append(
            {p.relative_to(destination): p.read_bytes() for p in destination.rglob("*") if p.is_file()}
        )
    assert snapshots[0] == snapshots[1]
    assert json.loads((tmp_path / "rendered/.secrets.baseline").read_text())["results"] == {}
    assert (tmp_path / "rendered/Makefile").is_file()


@pytest.mark.parametrize(
    "defect",
    ["ten-failures", "ten-skips", "ten-todos", "ten-aborted", "wrong-identity"],
)
def test_workspace_validator_rejects_real_incorrect_tap(tmp_path, defect):
    import shutil

    shutil.copytree(ROOT / "assurance/fixtures/python/project", tmp_path, dirs_exist_ok=True)
    env = {**os.environ, "PYTHONPATH": str(tmp_path / "src")}
    for argv in (
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            "--source=consumer",
            "-m",
            "pytest",
            "-q",
            "tests",
            "--junitxml=artifacts/junit.xml",
        ],
        [sys.executable, "-m", "coverage", "xml", "-o", "artifacts/coverage.xml"],
    ):
        result = subprocess.run(argv, cwd=tmp_path, env=env, text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
    cases = {
        "ten-failures": "for (let i = 0; i < 10; i++) test('generated-total', () => assert.equal(9, 5));",
        "ten-skips": "test('generated-total', () => assert.equal(5, 5)); for (let i = 0; i < 10; i++) test.skip('unused', () => {});",
        "ten-todos": "test('generated-total', () => assert.equal(5, 5)); for (let i = 0; i < 10; i++) test.todo('pending');",
        "ten-aborted": "test('generated-total', () => assert.equal(5, 5)); for (let i = 0; i < 10; i++) test('unfinished', { signal: AbortSignal.abort() }, () => {});",
        "wrong-identity": "test('not-generated-total', () => assert.equal(5, 5));",
    }
    (tmp_path / "negative.mjs").write_text(
        "import { test } from 'node:test';\nimport assert from 'node:assert/strict';\n" + cases[defect]
    )
    node = subprocess.run(
        [
            "node",
            "--test",
            "--test-reporter=tap",
            "--test-reporter-destination=artifacts/workspace.tap",
            "negative.mjs",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert node.returncode == (1 if defect in {"ten-failures", "ten-aborted"} else 0)
    spec = importlib.util.spec_from_file_location("surface_assurance", CLI)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(module.AssuranceError, match="unexpected-workspace-result"):
        module.output_evidence(
            tmp_path,
            tmp_path / "retained",
            "workspace-failure" if defect == "ten-failures" else "pass",
            workspace=True,
        )


@pytest.mark.parametrize("defect", ["skip", "duplicate", "reordered"])
def test_generated_terminal_validator_rejects_real_altered_result(tmp_path, defect):
    import shutil

    root = tmp_path / "pipeline"
    for name in ("governance", "assurance"):
        shutil.copytree(ROOT / name, root / name, ignore=shutil.ignore_patterns("__pycache__"))
    path = root / "assurance/consumers.yaml"
    manifest = yaml.safe_load(path.read_text())
    generated = next(row for row in manifest["consumers"] if row["id"] == "generated")
    original = generated["evaluate"]["affected"]
    terminal_pattern = r"^(?:PASS \[[^]\n]+\].*|FAIL \[[^]\n]+\].* \(exit [1-9][0-9]*\))$"
    alteration = {
        "skip": "text = text.replace('FAIL [harness-canon-reference]', 'SKIP [harness-canon-reference]')",
        "duplicate": "text += '\\nPASS [consumer-tests] consumer-tests\\n'",
        "reordered": (
            f"rows = re.findall({terminal_pattern!r}, text, re.MULTILINE); "
            "assert len(rows) == 9; reversed_rows = iter(rows[::-1]); "
            f"text = re.sub({terminal_pattern!r}, lambda match: next(reversed_rows), text, flags=re.MULTILINE)"
        ),
    }[defect]
    # Execute the actual gate and alter only its generated sabotage transcript.
    # The engine, returned status, produced files and positive path remain real.
    script = (
        "import re, subprocess, sys\n"
        f"result = subprocess.run({original!r}, text=True, capture_output=True)\n"
        "text = re.sub(r'\\x1b\\[[0-9;]*m', '', result.stdout + result.stderr)\n"
        "if 'missing required harness entrypoint: CLAUDE.md' in text:\n"
        f"    {alteration}\n"
        "print(text)\nsys.exit(result.returncode)\n"
    )
    generated["evaluate"]["affected"] = ["python", "-c", script]
    path.write_text(yaml.safe_dump(manifest))
    result = invoke("lab", "--root", root, "--output", tmp_path / "evidence")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "unexpected-terminal-result" in result.stderr
