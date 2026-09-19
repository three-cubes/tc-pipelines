"""Review regressions exercise real Git, scanners, subprocesses and HTTP bytes."""

import functools
import hashlib
import http.server
import json
import subprocess
import sys
import threading
import zipfile
from datetime import UTC, datetime

import pytest
import yaml
from test_hosted_assurance import ROOT, git, hosted_module, repository

pytestmark = pytest.mark.contract


def test_arbitrary_hashed_files_cannot_satisfy_protected_admission(tmp_path):
    base = repository(tmp_path)
    inventory = tmp_path / "assurance/surfaces.yaml"
    data = yaml.safe_load(inventory.read_text())
    data["surfaces"] = [
        row for row in data["surfaces"] if row["hosted"]["boundary"] == "protected-live"
    ]
    inventory.write_text(yaml.safe_dump(data))
    (tmp_path / "assurance/hosted-cases.yaml").write_text("cases: {}\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "test: protected only")
    head = git(tmp_path, "rev-parse", "HEAD")
    module = hosted_module()
    directory = tmp_path / "evidence"
    selection = module.plan(tmp_path, base, head, directory, complete=True)
    expected = selection["required_probes"][0]["expectation"]
    outputs = []
    for identity in expected["output_ids"]:
        path = directory / (identity + ".txt")
        path.write_text("arbitrary claimed success\n")
        outputs.append(
            {
                "id": identity,
                "path": path.name,
                "digest": module.digest(path.read_bytes()),
            }
        )
    now = datetime.now(UTC).isoformat()
    receipt = {
        "schema": "tc.sdlc/assurance/v1",
        **{
            key: expected[key]
            for key in ("subject", "case_id", "expected", "candidate", "consumer")
        },
        "actual": "pass",
        "execution": {
            **expected["execution"],
            "started_at": now,
            "finished_at": now,
            "exit_code": 0,
        },
        "evidence": {
            "outputs": outputs,
            "finding": None,
            "fitness_ledger_digest": None,
            "runtime_receipt_digest": outputs[1]["digest"],
        },
    }
    (directory / "receipt.json").write_text(json.dumps(receipt))
    # This was accepted despite all three files being arbitrary text.
    with pytest.raises(ValueError, match="protected|runtime"):
        module.admit(tmp_path, directory)


def test_pr_selection_binds_branch_head_and_tested_merge(tmp_path):
    base = repository(tmp_path)
    git(tmp_path, "checkout", "-qb", "feature")
    (tmp_path / "feature.txt").write_text("candidate\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "test: branch")
    candidate = git(tmp_path, "rev-parse", "HEAD")
    git(tmp_path, "checkout", "--detach", base)
    git(tmp_path, "merge", "--no-ff", "-m", "test: merge", candidate)
    tested = git(tmp_path, "rev-parse", "HEAD")
    module = hosted_module()
    selection = module.plan(
        tmp_path, base, tested, tmp_path / "plan", candidate_head=candidate
    )
    assert selection["head"] == tested
    assert selection["candidate_head"] == candidate
    row = yaml.safe_load((tmp_path / "assurance/surfaces.yaml").read_text())[
        "surfaces"
    ][0]
    expected = module.expectation_for(tmp_path, selection, row, {})
    assert expected["candidate"]["pipeline_commit"] == tested
    assert expected["candidate"]["pipeline_head_commit"] == candidate
    with pytest.raises(ValueError, match="merge"):
        module.select(tmp_path, base, tested, candidate_head=base)


@pytest.mark.parametrize(
    "defect", [None, "head_sha", "status", "conclusion", "id", "run_attempt"]
)
def test_pr_api_run_uses_candidate_branch_identity_not_tested_merge(defect):
    module = hosted_module()
    selection = {
        "head": "a" * 40,
        "candidate_head": "b" * 40,
        "workflow_run_id": "42",
        "attempt": 2,
    }
    run = {
        "head_sha": "b" * 40,
        "status": "completed",
        "conclusion": "success",
        "id": 42,
        "run_attempt": 2,
    }
    if defect:
        run[defect] = "a" * 40 if defect == "head_sha" else "wrong"
        with pytest.raises(ValueError, match="GitHub"):
            module.validate_run(run, selection)
    else:
        module.validate_run(run, selection)


@pytest.mark.parametrize(
    "defect",
    [
        None,
        "actor",
        "workflow",
        "candidate",
        "status",
        "conclusion",
        "run",
        "attempt",
        "repository",
        "event",
    ],
)
def test_protected_provenance_protocol_requires_authorised_terminal_run(defect):
    hosted_module()
    from protected_evidence import validate_provenance

    # Protocol validation only: these records are never minted as hosted proof.
    selection = {"candidate_head": "a" * 40, "head": "b" * 40}
    policy = {
        "repository": "fixtures/runtime",
        "run_id": 42,
        "attempt_id": 2,
        "workflow_path": ".github/workflows/status.yml",
        "actor_id": 123,
        "environment": "protected-status",
    }
    run = {
        "head_sha": selection["candidate_head"],
        "status": "completed",
        "conclusion": "success",
        "path": policy["workflow_path"],
        "event": "workflow_dispatch",
        "actor": {"id": 123},
        "run_attempt": 2,
        "id": 42,
        "repository": {"full_name": policy["repository"]},
        "html_url": "https://github.com/fixtures/runtime/actions/runs/42",
    }
    if defect == "actor":
        run["actor"]["id"] = 999
    elif defect == "repository":
        run["repository"]["full_name"] = "fixtures/unauthorised"
    elif defect in {
        "workflow",
        "candidate",
        "status",
        "conclusion",
        "run",
        "attempt",
        "event",
    }:
        key = {
            "workflow": "path",
            "candidate": "head_sha",
            "run": "id",
            "attempt": "run_attempt",
        }.get(defect, defect)
        run[key] = "wrong"
    if defect:
        with pytest.raises(ValueError, match="protected"):
            validate_provenance(run, selection, policy)
    else:
        validate_provenance(run, selection, policy)


@pytest.mark.parametrize("finding", [False, True])
def test_semgrep_scans_actual_fixture_source(tmp_path, finding):
    path = tmp_path / "assurance/fixtures/python/project/src/control.py"
    path.parent.mkdir(parents=True)
    path.write_text("eval('1 + 1')\n" if finding else "answer = 1 + 1\n")
    result = subprocess.run(
        [
            "uvx",
            "--from",
            "semgrep==1.168.0",
            "semgrep",
            "scan",
            "--config",
            str(ROOT / "assurance/fixtures/hosted/semgrep.yaml"),
            "--json",
            "--error",
            "--metrics",
            "off",
            "--jobs",
            "1",
            "--no-git-ignore",
            ".",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    data = json.loads(result.stdout)
    assert (
        "assurance/fixtures/python/project/src/control.py" in data["paths"]["scanned"]
    )
    assert result.returncode == int(finding), result.stderr
    assert bool(data["results"]) is finding


def test_native_mutation_requires_real_terminal_result(tmp_path):
    module = hosted_module()
    path = tmp_path / "mutation.json"
    with pytest.raises((ValueError, OSError)):
        module.validate_mutation(path)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "assurance/adapter_probe.py"),
            "mutation",
            "--output",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    module.validate_mutation(path)
    # Actual failing subprocess status must not be hidden by a successful wrapper.
    failed = subprocess.run([sys.executable, "-c", "raise SystemExit(2)"], check=False)
    data = json.loads(path.read_text())
    data.update(status="fail", original_exit=failed.returncode, killed=0)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="mutation"):
        module.validate_mutation(path)


@pytest.mark.parametrize("defect", [None, "missing", "duplicate", "malformed"])
def test_native_artifact_requires_one_real_result_member(tmp_path, defect):
    module = hosted_module()
    archive = tmp_path / "native.zip"
    if defect == "malformed":
        archive.write_bytes(b"not a ZIP archive")
    else:
        with zipfile.ZipFile(archive, "w") as stream:
            if defect != "missing":
                stream.writestr("mutation.json", b'{"status":"pass"}')
            if defect == "duplicate":
                with pytest.warns(UserWarning, match="Duplicate"):
                    stream.writestr("mutation.json", b'{"status":"fail"}')
    if defect:
        with pytest.raises(ValueError, match="native artifact"):
            module.archive_member(archive, "mutation.json")
    else:
        assert module.archive_member(archive, "mutation.json") == b'{"status":"pass"}'


def test_raw_job_log_transport_accepts_ansi_and_retains_http_failure(tmp_path):
    module = hosted_module()
    raw = b"2026-09-19T00:00:00Z \x1b[32mPASS\x1b[0m\n"
    (tmp_path / "job.log").write_bytes(raw)
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=tmp_path
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        target = tmp_path / "download"
        text = module.download_log(url + "/job.log", target)
        assert "PASS" in text and "\x1b" not in text
        assert target.with_suffix(".raw").read_bytes() == raw
        with pytest.raises(ValueError, match="download"):
            module.download_log(url + "/missing", tmp_path / "missing")
        assert "404" in (tmp_path / "missing.stderr").read_text()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize(
    "defect",
    [
        None,
        "arbitrary",
        "contract_digest",
        "source_sha",
        "image_digest",
        "host_id",
        "runtime_user",
        "deployment_id",
        "configuration_identity",
        "run_id",
        "attempt_id",
        "skipped",
        "failed",
        "exit-only",
        "missing-check",
        "stale",
        "self-authorised",
    ],
)
def test_canonical_runtime_verifier_checks_real_protocol_receipt(tmp_path, defect):
    hosted_module()  # establishes the repository-owned module import path
    from protected_evidence import verify_runtime

    contract = {
        "schema": "tc-fitness/runtime-contract/v1",
        "environment": "prod",
        "target": "fixture",
        "filesystem": {},
        "access": {},
        "deployment": {},
        "evidence": {},
    }
    registry = {
        "schema": contract["schema"],
        "environments": {
            "prod": {
                "targets": {
                    "fixture": {
                        key: {}
                        for key in ("filesystem", "access", "deployment", "evidence")
                    }
                }
            }
        },
    }
    contract_file = tmp_path / "contract.json"
    contract_file.write_text(json.dumps(registry))
    policy = {
        "contract": str(contract_file),
        "environment": "prod",
        "target": "fixture",
        "image_digest": "sha256:" + "b" * 64,
        "host_id": "fixture-host",
        "runtime_user": "fixture-user",
        "deployment_id": "123",
        "configuration_identity": "sha256:" + "c" * 64,
        "run_id": 42,
        "attempt_id": 1,
        "required_checks": ["read-only-status"],
        "max_age_seconds": 300,
    }
    # Protocol fixtures exercise the actual canonical executable; they are not live receipts.
    canonical = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    evidence = {
        "schema": "tc-fitness/runtime-evidence/v1",
        "contract_digest": "sha256:" + hashlib.sha256(canonical).hexdigest(),
        "source_sha": "a" * 40,
        **{
            key: policy[key]
            for key in (
                "image_digest",
                "host_id",
                "runtime_user",
                "deployment_id",
                "configuration_identity",
                "run_id",
                "attempt_id",
            )
        },
        "captured_at": datetime.now(UTC).isoformat(),
        "artifacts": [],
        "checks": [
            {
                "id": "read-only-status",
                "status": "passed",
                "observation": {"kind": "process", "state": "healthy"},
            }
        ],
    }
    if defect in {"run_id", "attempt_id"}:
        evidence[defect] += 1
    elif defect in evidence and defect != "checks":
        evidence[defect] = "wrong-identity"
    elif defect in {"skipped", "failed"}:
        evidence["checks"][0]["status"] = defect
    elif defect == "exit-only":
        evidence["checks"][0]["observation"] = {"exit_code": 0}
    elif defect == "missing-check":
        evidence["checks"] = []
    elif defect == "stale":
        evidence["captured_at"] = "2020-01-01T00:00:00Z"
    elif defect == "self-authorised":
        evidence.update(
            source_sha="d" * 40,
            image_digest="sha256:" + "e" * 64,
            deployment_id="attacker-deployment",
        )
        evidence["expected_identity"] = {
            key: evidence[key]
            for key in ("source_sha", "image_digest", "deployment_id")
        }
        evidence["release_policy"] = {**policy, **evidence["expected_identity"]}
    path = tmp_path / "runtime.json"
    path.write_text(
        "arbitrary claimed success" if defect == "arbitrary" else json.dumps(evidence)
    )
    if defect:
        with pytest.raises(ValueError, match="canonical protected runtime"):
            verify_runtime(tmp_path, path, policy, "a" * 40)
    else:
        verify_runtime(tmp_path, path, policy, "a" * 40)
        assert json.loads((tmp_path / "canonical-verification.json").read_text()) == {
            "valid": True,
            "findings": [],
        }
