"""Protocol controls for retained, GitHub-hosted scanner qualification receipts.

These tests validate receipt semantics only.  They deliberately do not stand in
for a Checkov or OSV Scanner invocation; the committed workflow is the live
qualification boundary.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from assurance.live_scanners import (
    TOOLS,
    WORKFLOW_PATH,
    ReceiptError,
    digest,
    scanner_outcome,
    validate_receipt,
)

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[3]


def _write(root: Path, name: str, contents: str) -> tuple[str, str]:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    return name, digest(path.read_bytes())


def receipt(root: Path) -> dict[str, object]:
    fixture_path = "assurance/fixtures/live-scanners/checkov/compliant"
    fixture_file = root / fixture_path / "main.tf"
    fixture_file.parent.mkdir(parents=True)
    fixture_file.write_text('acl = "private"\n')
    fixture_digest = digest(
        json.dumps(
            [{"path": "main.tf", "digest": digest(fixture_file.read_bytes())}],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    report_path, report_digest = _write(root, "report.json", '{"failed_checks": []}\n')
    rule_identity = "sha256:" + "c" * 64
    rule_path, rule_digest = _write(
        root,
        "rule-db.json",
        json.dumps({"policy": "CKV_AWS_20", "policy_tree_digest": rule_identity}) + "\n",
    )
    log_path, log_digest = _write(root, "execution.log", "checkov completed\n")
    now = datetime.now(UTC)
    return {
        "schema": "tc.sdlc/live-scanner-qualification/v1",
        "case_id": "checkov-compliant",
        "expected": "clean",
        "actual": "clean",
        "candidate": {"pipeline_commit": "a" * 40},
        "fixture": {"path": fixture_path, "digest": fixture_digest},
        "tool": {
            "name": "checkov",
            "version": TOOLS["checkov"],
            "executable_digest": "sha256:" + "b" * 64,
        },
        "rule_database": {
            "kind": "packaged-checkov-policy-tree",
            "identity": rule_identity,
        },
        "execution": {
            "executor": "github-actions",
            "repository": "three-cubes/tc-pipelines",
            "workflow_path": ".github/workflows/live-scanner-qualification.yml",
            "workflow_run_id": "42",
            "attempt": 1,
            "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
        },
        "evidence": {
            "kind": "native-live-scanner",
            "outputs": [
                {"id": "scanner-report", "path": report_path, "digest": report_digest},
                {"id": "rule-database", "path": rule_path, "digest": rule_digest},
                {"id": "execution-log", "path": log_path, "digest": log_digest},
            ],
        },
    }


def test_live_scanner_receipt_binds_native_fixture_tool_and_rule_database(tmp_path):
    value = receipt(tmp_path)
    validate_receipt(value, tmp_path, candidate="a" * 40)


@pytest.mark.parametrize(
    ("returncode", "report", "finding", "expected"),
    [
        (0, '{"results": {"failed_checks": []}}', "CKV_AWS_20", "clean"),
        (
            1,
            '{"results": {"failed_checks": [{"check_id": "CKV_AWS_20"}]}}',
            "CKV_AWS_20",
            "finding",
        ),
        (
            1,
            '{"results": [{"packages": [{"vulnerabilities": [{"id": "GHSA-35jh-r3h4-6jhm"}]}]}]}',
            "GHSA-35jh-r3h4-6jhm",
            "finding",
        ),
    ],
)
def test_scanner_outcome_parses_native_json_before_matching_findings(returncode, report, finding, expected):
    assert scanner_outcome(returncode, report, finding) == expected


def test_live_scanner_receipt_binds_repo_fixture_and_separate_retained_outputs(
    tmp_path,
):
    repository = tmp_path / "candidate"
    evidence = tmp_path / "retained"
    repository.mkdir()
    evidence.mkdir()
    value = receipt(repository)
    for name in ("report.json", "rule-db.json", "execution.log"):
        shutil.move(repository / name, evidence / name)
    validate_receipt(value, repository, candidate="a" * 40, evidence_root=evidence)


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "stale",
        "wrong-tool",
        "wrong-rule-db",
        "fixture-sabotage",
        "protocol-ledger",
    ],
)
def test_live_scanner_receipt_rejects_missing_stale_or_non_native_evidence(tmp_path, defect):
    value = receipt(tmp_path)
    if defect == "missing":
        value["evidence"]["outputs"] = value["evidence"]["outputs"][:-1]
    elif defect == "stale":
        value["execution"]["finished_at"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    elif defect == "wrong-tool":
        value["tool"]["version"] = "3.2.530"
    elif defect == "wrong-rule-db":
        value["rule_database"]["kind"] = "osv-scanner-remote-response"
    elif defect == "fixture-sabotage":
        (tmp_path / "assurance/fixtures/live-scanners/checkov/compliant/main.tf").write_text(
            'acl = "public-read"\n'
        )
    elif defect == "protocol-ledger":
        value["evidence"] = {
            "kind": "tc-fitness-protocol-unit",
            "outputs": value["evidence"]["outputs"],
        }
    with pytest.raises(ReceiptError):
        validate_receipt(value, tmp_path, candidate="a" * 40)


def test_receipt_rejects_an_unlisted_tc_fitness_ledger_even_with_matching_hashes(
    tmp_path,
):
    value = receipt(tmp_path)
    ledger_path, ledger_digest = _write(
        tmp_path, "ledger.json", json.dumps({"evidence_class": "protocol-unit"})
    )
    value["evidence"]["outputs"].append(
        {"id": "fitness-ledger", "path": ledger_path, "digest": ledger_digest}
    )
    with pytest.raises(ReceiptError, match="named scanner outputs|ledger"):
        validate_receipt(value, tmp_path, candidate="a" * 40)


def test_live_workflow_uses_the_catalogued_scanner_provisioner_and_retains_receipts():
    workflow = yaml.safe_load((ROOT / WORKFLOW_PATH).read_text())
    steps = workflow["jobs"]["qualify"]["steps"]
    checkouts = [step for step in steps if "actions/checkout@" in str(step.get("uses", ""))]
    assert [step["with"]["path"] for step in checkouts] == [
        ".tc-pipelines-trusted",
        "candidate",
    ]
    assert checkouts[0]["with"]["ref"] == "${{ github.workflow_sha }}"
    assert checkouts[1]["with"]["ref"] == "${{ inputs.candidate }}"
    provision = next(step for step in steps if step.get("name") == "Provision pinned native scanners")
    assert provision["run"].splitlines() == [
        "cd .tc-pipelines-trusted",
        'export TC_SCANNER_PATH_FILE="$GITHUB_PATH"',
        "bash actions/python-gate-body/provision-scanners.sh",
    ]
    assert provision["env"] == {
        "INSTALL_OSV_SCANNER": "true",
        "INSTALL_CHECKOV_SCANNER": "true",
        "TC_SCANNER_BIN_DIR": "${{ runner.temp }}/tc-pipelines-scanners/bin",
    }
    assert 'export TC_SCANNER_PATH_FILE="$GITHUB_PATH"' in provision["run"]
    assert "2.6.0" not in provision["run"]
    execute = next(
        step for step in steps if step.get("name") == "Execute compliant and violation scanner fixtures"
    )
    assert ".tc-pipelines-trusted/.venv/bin/python" in execute["run"]
    assert ".tc-pipelines-trusted/assurance/live_scanners.py qualify" in execute["run"]
    assert "--root candidate" in execute["run"]
    retained = next(
        step for step in steps if step.get("name") == "Retain native scanner qualification evidence"
    )
    assert retained["with"]["path"] == ".assurance-live-scanners/"


def test_live_scanner_writer_refuses_to_mint_a_local_success(tmp_path):
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GITHUB_")}
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "assurance/live_scanners.py"),
            "qualify",
            "--candidate",
            "a" * 40,
            "--output",
            str(tmp_path / "evidence"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )
    assert result.returncode == 1
    assert "requires GitHub Actions" in result.stderr
