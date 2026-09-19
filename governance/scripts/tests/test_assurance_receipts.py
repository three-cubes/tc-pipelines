"""Receipts bind real local executions; local evidence never proves GitHub execution."""

import copy
import hashlib
import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / "assurance/receipt.py"


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def call(*args):
    return subprocess.run(
        [sys.executable, str(CLI), *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )


def execution(tmp_path, negative=False):
    started = datetime.now(UTC).isoformat()
    command = [
        sys.executable,
        "-c",
        "from pathlib import Path; Path('result.txt').write_text('denied: missing-license' if "
        + str(negative)
        + " else 'verified license'); raise SystemExit("
        + str(int(negative))
        + ")",
    ]
    result = subprocess.run(
        command, cwd=tmp_path, capture_output=True, text=True, check=False
    )
    (tmp_path / "execution.log").write_text(
        f"command={command!r}\nexit={result.returncode}\n"
        + result.stdout
        + result.stderr
    )
    candidate = {
        "fitness_digest": None,
        "pipeline_commit": "a" * 40,
        "pipeline_package_digest": None,
        "pipeline_image_digest": None,
    }
    consumer = {
        "repository": "fixtures/license",
        "commit": "b" * 40,
        "sdlc_lock_digest": None,
    }
    tasks = [{"id": "license", "input_digest": digest(b"license input")}]
    expected = {
        "subject": "pipeline-adapter",
        "case_id": "license-deny" if negative else "license-pass",
        "expected": "deny" if negative else "pass",
        "candidate": candidate,
        "consumer": consumer,
        "execution": {
            "execution_id": str(uuid.uuid4()),
            "workflow_run_id": None,
            "attempt": 1,
            "command": command,
            "tasks": tasks,
            "executor": "local",
        },
        "output_ids": ["execution-log", "license-result"],
        "finding": "missing-license" if negative else None,
    }
    observation = {
        "actual": expected["expected"],
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "exit_code": result.returncode,
        "outputs": [
            {"id": "execution-log", "path": "execution.log"},
            {"id": "license-result", "path": "result.txt"},
        ],
        "fitness_ledger": None,
        "runtime_receipt": None,
        "finding": expected["finding"],
    }
    (tmp_path / "expectation.json").write_text(json.dumps(expected))
    (tmp_path / "observation.json").write_text(json.dumps(observation))
    return expected, observation


def write(tmp_path):
    result = call(
        "write",
        "--expectation",
        tmp_path / "expectation.json",
        "--observation",
        tmp_path / "observation.json",
        "--root",
        tmp_path,
        "--receipt",
        tmp_path / "receipt.json",
    )
    assert result.returncode == 0, result.stderr
    return json.loads((tmp_path / "receipt.json").read_text())


def validate(tmp_path):
    return call(
        "validate",
        "--expectation",
        tmp_path / "expectation.json",
        "--root",
        tmp_path,
        "--receipt",
        tmp_path / "receipt.json",
    )


@pytest.mark.parametrize("negative", [False, True])
def test_real_local_execution_round_trip(tmp_path, negative):
    execution(tmp_path, negative)
    receipt = write(tmp_path)
    assert receipt["schema"] == "tc.sdlc/assurance/v1"
    assert receipt["execution"]["executor"] == "local"
    assert receipt["evidence"]["outputs"][1]["digest"] == digest(
        (tmp_path / "result.txt").read_bytes()
    )
    assert validate(tmp_path).returncode == 0
    assert (
        call(
            "write",
            "--expectation",
            tmp_path / "expectation.json",
            "--observation",
            tmp_path / "observation.json",
            "--root",
            tmp_path,
            "--receipt",
            tmp_path / "receipt.json",
        ).returncode
        != 0
    )


@pytest.mark.parametrize(
    "defect",
    [
        "missing-field",
        "wrong-candidate",
        "wrong-consumer",
        "wrong-attempt",
        "wrong-execution",
        "wrong-task",
        "skipped",
        "output-free",
        "duplicate-output",
        "wrong-output",
        "wrong-digest",
        "wrong-exit",
        "stale",
        "local-as-hosted",
        "finding-absent",
        "finding-unrelated",
        "missing-log",
        "duplicate-task",
        "path-escape",
    ],
)
def test_receipt_rejects_false_pass(tmp_path, defect):
    expected, _ = execution(tmp_path, negative=defect.startswith("finding"))
    receipt = write(tmp_path)
    if defect == "missing-field":
        del receipt["candidate"]["pipeline_image_digest"]
    elif defect == "wrong-candidate":
        receipt["candidate"]["pipeline_commit"] = "c" * 40
    elif defect == "wrong-consumer":
        receipt["consumer"]["commit"] = "c" * 40
    elif defect == "wrong-attempt":
        receipt["execution"]["attempt"] = 2
    elif defect == "wrong-execution":
        receipt["execution"]["execution_id"] = str(uuid.uuid4())
    elif defect == "wrong-task":
        receipt["execution"]["tasks"][0]["input_digest"] = digest(b"other")
    elif defect == "skipped":
        receipt["actual"] = "skipped"
    elif defect == "output-free":
        receipt["evidence"]["outputs"] = []
    elif defect == "duplicate-output":
        receipt["evidence"]["outputs"].append(
            copy.deepcopy(receipt["evidence"]["outputs"][0])
        )
    elif defect == "wrong-output":
        receipt["evidence"]["outputs"][1]["id"] = "other"
    elif defect == "wrong-digest":
        (tmp_path / "result.txt").write_text("altered")
    elif defect == "wrong-exit":
        receipt["execution"]["exit_code"] = 1
    elif defect == "stale":
        receipt["execution"]["finished_at"] = "2000-01-01T00:00:00Z"
    elif defect == "local-as-hosted":
        expected["execution"]["executor"] = "github-actions"
        expected["execution"]["workflow_run_id"] = "123"
        (tmp_path / "expectation.json").write_text(json.dumps(expected))
    elif defect == "finding-absent":
        receipt["evidence"]["finding"] = None
    elif defect == "finding-unrelated":
        (tmp_path / "result.txt").write_text("unrelated failure")
        receipt["evidence"]["outputs"][1]["digest"] = digest(b"unrelated failure")
    elif defect == "missing-log":
        (tmp_path / "execution.log").unlink()
    elif defect == "duplicate-task":
        receipt["execution"]["tasks"] *= 2
    elif defect == "path-escape":
        receipt["evidence"]["outputs"][1]["path"] = "../result.txt"
    (tmp_path / "receipt.json").write_text(json.dumps(receipt))
    assert validate(tmp_path).returncode != 0, defect


def test_writer_cannot_mint_hosted_receipt_from_local_observation(tmp_path):
    expected, _ = execution(tmp_path)
    expected["execution"].update(executor="github-actions", workflow_run_id="123")
    (tmp_path / "expectation.json").write_text(json.dumps(expected))
    result = call(
        "write",
        "--expectation",
        tmp_path / "expectation.json",
        "--observation",
        tmp_path / "observation.json",
        "--root",
        tmp_path,
        "--receipt",
        tmp_path / "receipt.json",
    )
    assert result.returncode != 0
    assert "GitHub" in result.stderr


def test_writer_retains_failed_terminal_receipt_without_passing_it(tmp_path):
    _, observation = execution(tmp_path)
    observation.update(actual="error", exit_code=2)
    (tmp_path / "observation.json").write_text(json.dumps(observation))
    result = call(
        "write",
        "--expectation",
        tmp_path / "expectation.json",
        "--observation",
        tmp_path / "observation.json",
        "--root",
        tmp_path,
        "--receipt",
        tmp_path / "receipt.json",
    )
    assert result.returncode != 0
    assert json.loads((tmp_path / "receipt.json").read_text())["actual"] == "error"
    assert validate(tmp_path).returncode != 0
