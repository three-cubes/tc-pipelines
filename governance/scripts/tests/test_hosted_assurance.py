"""Exact Git selection and admission reject missing hosted proof."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / "assurance/hosted.py"


def git(root, *args):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def invoke(*args):
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GITHUB_")}
    return subprocess.run(
        [sys.executable, str(CLI), *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def repository(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "three-cubes-agent[bot]")
    git(
        tmp_path,
        "config",
        "user.email",
        "295831460+three-cubes-agent[bot]@users.noreply.github.com",
    )
    (tmp_path / "assurance").mkdir()
    (tmp_path / ".github/workflows").mkdir(parents=True)
    surfaces = []
    for name, boundary in [
        ("safe", "safe-hosted"),
        ("deploy", "protected-live"),
        ("example-safe", "structural-example"),
    ]:
        path = f".github/workflows/{name}.yml"
        (tmp_path / path).write_text("on: {workflow_call: {}}\njobs: {}\n")
        surfaces.append(
            {
                "id": f"workflow.{name}",
                "path": path,
                "hosted": {
                    "boundary": boundary,
                    "dependencies": ["shared/**"],
                    "case": name if boundary == "safe-hosted" else None,
                    "release_probe": "approved-status" if boundary == "protected-live" else None,
                },
            }
        )
    (tmp_path / "assurance/surfaces.yaml").write_text(yaml.safe_dump({"surfaces": surfaces}))
    (tmp_path / "assurance/hosted-cases.yaml").write_text(
        yaml.safe_dump({"cases": {"safe": {"jobs": ["Adapter"], "steps": ["Assert"]}}})
    )
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "test: selection fixture")
    return git(tmp_path, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    "changed,want",
    [
        (".github/workflows/safe.yml", ["safe"]),
        ("shared/driver.py", ["safe"]),
        ("README.md", []),
        (".github/workflows/example-safe.yml", []),
    ],
)
def test_exact_committed_diff_selects_safe_and_routes_protected(tmp_path, changed, want):
    base = repository(tmp_path)
    target = tmp_path / changed
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(target.read_text() + "# changed\n" if target.exists() else "new\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "test: exact candidate")
    head = git(tmp_path, "rev-parse", "HEAD")
    # Uncommitted changes must not contaminate the exact candidate selection.
    (tmp_path / ".github/workflows/deploy.yml").write_text("dirty\n")
    result = invoke("select", "--root", tmp_path, "--base", base, "--head", head)
    assert result.returncode == 0, result.stderr
    selection = json.loads(result.stdout)
    assert selection["safe"] == want
    assert selection["protected"] == (["workflow.deploy"] if changed == "shared/driver.py" else [])
    assert selection["head"] == head


def test_removed_surface_cannot_disappear_from_selection(tmp_path):
    base = repository(tmp_path)
    (tmp_path / ".github/workflows/safe.yml").unlink()
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "test: delete required adapter")
    result = invoke(
        "select",
        "--root",
        tmp_path,
        "--base",
        base,
        "--head",
        git(tmp_path, "rev-parse", "HEAD"),
    )
    assert result.returncode != 0
    assert "missing" in result.stderr


@pytest.mark.parametrize("case", [None, "undeclared"])
def test_safe_surface_requires_an_executable_case(tmp_path, case):
    base = repository(tmp_path)
    path = tmp_path / "assurance/surfaces.yaml"
    data = yaml.safe_load(path.read_text())
    data["surfaces"][0]["hosted"]["case"] = case
    path.write_text(yaml.safe_dump(data))
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "test: missing case")
    result = invoke(
        "select",
        "--root",
        tmp_path,
        "--base",
        base,
        "--head",
        git(tmp_path, "rev-parse", "HEAD"),
    )
    assert result.returncode != 0
    assert "case" in result.stderr


@pytest.mark.parametrize("probe", ["gate", "mutation", "precommit"])
def test_hosted_fixture_commands_produce_real_outputs(tmp_path, probe):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "assurance/adapter_probe.py"),
            probe,
            "--output",
            str(tmp_path / "result.json"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads((tmp_path / "result.json").read_text())
    assert data["status"] == "pass"
    if probe == "mutation":
        assert data["original_exit"] == 0
        assert data["mutant_exit"] == 1
        assert data["killed"] == 1
    elif probe == "gate":
        assert data["surfaces"] >= 35


def test_adapter_verifier_checks_real_license_and_rejects_wrong_change_output(tmp_path):
    verifier = ROOT / "assurance/verify_adapter.py"
    for case, observed, expected in [
        ("action-actions-license-present", "", 0),
        ("action-actions-detect-code-changes", "", 1),
        ("action-actions-detect-code-changes", "false", 1),
        ("action-actions-detect-code-changes", "true", 0),
    ]:
        result = subprocess.run(
            [
                sys.executable,
                str(verifier),
                "--output",
                str(tmp_path / (case + ".json")),
            ],
            cwd=ROOT,
            env={**os.environ, "CASE_ID": case, "CODE_CHANGED": observed},
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == expected, result.stderr


def hosted_module():
    sys.path.insert(0, str(ROOT / "assurance"))
    spec = importlib.util.spec_from_file_location("hosted_assurance", CLI)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "skipped-job",
        "wrong-run",
        "wrong-attempt",
        "wrong-head",
        "missing-step",
        "skipped-step",
        "duplicate-job",
        "duplicate-step",
    ],
)
def test_terminal_validation_rejects_incomplete_github_protocol_data(defect):
    # Protocol data is not a hosted receipt and never submitted to the writer.
    module = hosted_module()
    jobs = [
        {
            "id": 1,
            "run_id": 25,
            "run_attempt": 1,
            "head_sha": "a" * 40,
            "status": "completed",
            "conclusion": "success",
            "steps": [
                {
                    "name": "assert output",
                    "status": "completed",
                    "conclusion": "success",
                }
            ],
        }
    ]
    if defect == "missing":
        jobs = []
    elif defect == "skipped-job":
        jobs[0]["conclusion"] = "skipped"
    elif defect == "wrong-run":
        jobs[0]["run_id"] = 24
    elif defect == "wrong-attempt":
        jobs[0]["run_attempt"] = 2
    elif defect == "wrong-head":
        jobs[0]["head_sha"] = "b" * 40
    elif defect == "missing-step":
        jobs[0]["steps"] = []
    elif defect == "skipped-step":
        jobs[0]["steps"][0]["conclusion"] = "skipped"
    elif defect == "duplicate-job":
        jobs *= 2
    elif defect == "duplicate-step":
        jobs[0]["steps"] *= 2
    with pytest.raises(ValueError):
        module.validate_jobs(jobs, ["assert output"], "25", 1, "a" * 40)


def test_release_admission_rejects_missing_receipts(tmp_path):
    base = repository(tmp_path)
    result = invoke(
        "plan",
        "--root",
        tmp_path,
        "--base",
        base,
        "--head",
        base,
        "--complete",
        "--output",
        tmp_path / "evidence",
    )
    assert result.returncode == 0, result.stderr
    result = invoke("admit", "--root", tmp_path, "--output", tmp_path / "evidence")
    assert result.returncode != 0
    assert "missing required receipt" in result.stderr


def test_release_plan_names_nonmutating_external_requirements(tmp_path):
    base = repository(tmp_path)
    result = invoke(
        "plan",
        "--root",
        tmp_path,
        "--base",
        base,
        "--head",
        base,
        "--complete",
        "--output",
        tmp_path / "evidence",
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads((tmp_path / "evidence/selection.json").read_text())
    assert plan["required_probes"][0]["operation"] == "status"
    assert plan["required_probes"][0]["candidate_commit"] == base
    assert plan["required_probes"][0]["external_mutation"] is False
