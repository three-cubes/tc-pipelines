"""Write and validate native GitHub-hosted Checkov and OSV Scanner receipts.

This module is intentionally separate from generic ``tc.sdlc/assurance/v1``
adapter receipts.  A tc-fitness contract ledger can describe a protocol-unit
collaborator, but it is not evidence that the pinned scanner executed on a
GitHub-hosted candidate.  Only ``qualify`` may write these receipts, and it
refuses to run outside the matching Actions checkout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

try:  # Executable both as ``python assurance/...`` and as a package module.
    from .github_evidence import archive_member, download
except ImportError:  # pragma: no cover - exercised by the workflow entrypoint.
    from github_evidence import archive_member, download


SCHEMA = "tc.sdlc/live-scanner-qualification/v1"
WORKFLOW_PATH = ".github/workflows/live-scanner-qualification.yml"
MAX_RECEIPT_AGE = timedelta(hours=6)
TOOLS = {"checkov": "3.2.531", "osv-scanner": "2.2.4"}
CASES = {
    "checkov-compliant": {
        "tool": "checkov",
        "expected": "clean",
        "fixture": "assurance/fixtures/live-scanners/checkov/compliant",
        "finding": "CKV_AWS_20",
    },
    "checkov-violation": {
        "tool": "checkov",
        "expected": "finding",
        "fixture": "assurance/fixtures/live-scanners/checkov/violation",
        "finding": "CKV_AWS_20",
    },
    "osv-compliant": {
        "tool": "osv-scanner",
        "expected": "clean",
        "fixture": "assurance/fixtures/live-scanners/osv/compliant/package-lock.json",
        "finding": None,
    },
    "osv-violation": {
        "tool": "osv-scanner",
        "expected": "finding",
        "fixture": "assurance/fixtures/live-scanners/osv/violation/package-lock.json",
        # lodash 4.17.20 is vulnerable to this advisory.  The receipt requires
        # the actual database response to name it, rather than trusting exit 1.
        "finding": "GHSA-35jh-r3h4-6jhm",
    },
}


class ReceiptError(ValueError):
    """The retained result cannot establish scanner qualification."""


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(char in "0123456789abcdef" for char in value[7:])
    )


def file_digest(path: Path) -> str:
    if not path.is_file() or path.stat().st_size == 0:
        raise ReceiptError(f"missing or empty output: {path}")
    return digest(path.read_bytes())


def tree_digest(path: Path) -> str:
    """Hash file names and bytes, preventing a fixture replacement after a run."""
    if path.is_file():
        return file_digest(path)
    if not path.is_dir():
        raise ReceiptError(f"missing fixture: {path}")
    entries = []
    for child in sorted(path.rglob("*")):
        if child.is_file():
            entries.append(
                {
                    "path": child.relative_to(path).as_posix(),
                    "digest": digest(child.read_bytes()),
                }
            )
    if not entries:
        raise ReceiptError(f"empty fixture: {path}")
    return digest(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode())


def safe_output(root: Path, value: str) -> Path:
    path = Path(value)
    target = (root / path).resolve()
    if path.is_absolute() or ".." in path.parts or not target.is_relative_to(root.resolve()):
        raise ReceiptError(f"unsafe output path: {value}")
    return target


def _expect_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ReceiptError(f"missing {key}")
    return value


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ReceiptError("invalid receipt timestamp") from error
    if parsed.tzinfo is None:
        raise ReceiptError("receipt timestamp has no timezone")
    return parsed


def validate_receipt(
    receipt: dict[str, Any],
    root: Path,
    *,
    candidate: str,
    evidence_root: Path | None = None,
) -> None:
    """Validate immutable identities and local retained bytes, without GitHub I/O."""
    evidence_root = evidence_root or root
    required = {
        "schema",
        "case_id",
        "expected",
        "actual",
        "candidate",
        "fixture",
        "tool",
        "rule_database",
        "execution",
        "evidence",
    }
    if set(receipt) != required or receipt.get("schema") != SCHEMA:
        raise ReceiptError("invalid live scanner receipt schema")
    case_id = _expect_string(receipt, "case_id")
    case = CASES.get(case_id)
    if case is None:
        raise ReceiptError("unknown scanner qualification case")
    if receipt.get("expected") != case["expected"] or receipt.get("actual") != case["expected"]:
        raise ReceiptError("unexpected scanner outcome")
    candidate_data = receipt.get("candidate")
    if not isinstance(candidate_data, dict) or candidate_data != {"pipeline_commit": candidate}:
        raise ReceiptError("candidate identity mismatch")
    if len(candidate) != 40 or any(char not in "0123456789abcdef" for char in candidate):
        raise ReceiptError("candidate must be an exact commit")
    fixture = receipt.get("fixture")
    if not isinstance(fixture, dict) or set(fixture) != {"path", "digest"}:
        raise ReceiptError("invalid fixture identity")
    fixture_path = _expect_string(fixture, "path")
    if fixture_path != case["fixture"] or fixture.get("digest") != tree_digest(
        safe_output(root, fixture_path)
    ):
        raise ReceiptError("fixture identity mismatch")
    tool = receipt.get("tool")
    if (
        not isinstance(tool, dict)
        or set(tool) != {"name", "version", "executable_digest"}
        or tool.get("name") != case["tool"]
        or tool.get("version") != TOOLS[case["tool"]]
        or not is_digest(tool.get("executable_digest"))
    ):
        raise ReceiptError("wrong scanner tool identity")
    rule_database = receipt.get("rule_database")
    if (
        not isinstance(rule_database, dict)
        or set(rule_database) != {"kind", "identity"}
        or not isinstance(rule_database.get("kind"), str)
        or not is_digest(rule_database.get("identity"))
        or rule_database["kind"]
        != ("packaged-checkov-policy-tree" if tool["name"] == "checkov" else "osv-scanner-remote-response")
    ):
        raise ReceiptError("invalid scanner rule-database identity")
    execution = receipt.get("execution")
    if not isinstance(execution, dict) or set(execution) != {
        "executor",
        "repository",
        "workflow_path",
        "workflow_run_id",
        "attempt",
        "started_at",
        "finished_at",
    }:
        raise ReceiptError("invalid hosted execution identity")
    if (
        execution["executor"] != "github-actions"
        or execution["workflow_path"] != WORKFLOW_PATH
        or not isinstance(execution["repository"], str)
        or not execution["repository"]
        or not isinstance(execution["workflow_run_id"], str)
        or not execution["workflow_run_id"].isdigit()
        or int(execution["workflow_run_id"]) <= 0
        or not isinstance(execution["attempt"], int)
        or execution["attempt"] < 1
    ):
        raise ReceiptError("receipt is not GitHub-hosted scanner evidence")
    started = _parse_time(_expect_string(execution, "started_at"))
    finished = _parse_time(_expect_string(execution, "finished_at"))
    now = datetime.now(UTC)
    if finished < started or finished > now or now - finished > MAX_RECEIPT_AGE:
        raise ReceiptError("stale or nonterminal scanner receipt")
    evidence = receipt.get("evidence")
    if not isinstance(evidence, dict) or set(evidence) != {"kind", "outputs"}:
        raise ReceiptError("invalid scanner evidence")
    if evidence["kind"] != "native-live-scanner":
        raise ReceiptError("tc-fitness protocol ledger cannot satisfy live scanner evidence")
    outputs = evidence["outputs"]
    if (
        not isinstance(outputs, list)
        or {row.get("id") for row in outputs if isinstance(row, dict)}
        != {
            "scanner-report",
            "rule-database",
            "execution-log",
        }
        or len(outputs) != 3
    ):
        raise ReceiptError("missing or unexpected named scanner outputs")
    by_id: dict[str, dict[str, Any]] = {}
    for row in outputs:
        if not isinstance(row, dict) or set(row) != {"id", "path", "digest"}:
            raise ReceiptError("invalid scanner output")
        output = safe_output(evidence_root, _expect_string(row, "path"))
        if row["digest"] != file_digest(output):
            raise ReceiptError(f"output digest mismatch: {row['id']}")
        by_id[row["id"]] = row
    try:
        rule_data = json.loads(safe_output(evidence_root, by_id["rule-database"]["path"]).read_text())
    except json.JSONDecodeError as error:
        raise ReceiptError("invalid retained scanner rule-database output") from error
    if tool["name"] == "checkov":
        bound_identity = rule_data.get("policy_tree_digest") if isinstance(rule_data, dict) else None
    else:
        bound_identity = digest(json.dumps(rule_data, sort_keys=True, separators=(",", ":")).encode())
    if rule_database["identity"] != bound_identity:
        raise ReceiptError("unbound scanner rule-database identity")


def _run(command: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)


def _tool_identity(name: str) -> tuple[Path, str]:
    executable = shutil.which(name)
    if not executable:
        raise ReceiptError(f"required scanner unavailable: {name}")
    path = Path(executable).resolve()
    version = _run([str(path), "--version"], Path.cwd())
    if version.returncode != 0 or TOOLS[name] not in version.stdout + version.stderr:
        raise ReceiptError(f"wrong scanner version for {name}")
    return path, digest(path.read_bytes())


def _rule_database(name: str, report: str) -> tuple[str, str, dict[str, Any]]:
    if name == "checkov":
        module = _run(
            [sys.executable, "-c", "import checkov; print(checkov.__path__[0])"],
            Path.cwd(),
        )
        if module.returncode != 0:
            raise ReceiptError("cannot locate packaged Checkov policies")
        identity = tree_digest(Path(module.stdout.strip()))
        return (
            "packaged-checkov-policy-tree",
            identity,
            {
                "policy_tree_digest": identity,
                "policy": "CKV_AWS_20",
            },
        )
    try:
        parsed = json.loads(report)
    except json.JSONDecodeError as error:
        raise ReceiptError("OSV scanner did not produce JSON") from error
    # OSV publishes no immutable database revision with each request.  The
    # retained, normalised response is therefore the exact rule-data identity;
    # it is deliberately not described as a database release version.
    identity = digest(json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode())
    return "osv-scanner-remote-response", identity, parsed


def _contains(value: Any, expected: str) -> bool:
    if value == expected:
        return True
    if isinstance(value, dict):
        return any(_contains(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(_contains(item, expected) for item in value)
    return False


def scanner_outcome(returncode: int, report: str, finding: str | None) -> str:
    """Classify a native JSON report and require the declared finding on failure."""
    try:
        parsed = json.loads(report)
    except json.JSONDecodeError as error:
        raise ReceiptError("scanner did not produce JSON") from error
    contains_expected = bool(finding and _contains(parsed, finding))
    actual = "clean" if returncode == 0 and not contains_expected else "finding"
    if actual == "finding" and not contains_expected:
        raise ReceiptError("scanner failure did not contain the declared finding")
    return actual


def _command(case: dict[str, str | None], executable: Path) -> list[str]:
    fixture = Path(case["fixture"])
    if case["tool"] == "checkov":
        return [
            str(executable),
            "-d",
            str(fixture),
            "--check",
            str(case["finding"]),
            "--output",
            "json",
            "--quiet",
        ]
    return [str(executable), "--lockfile", str(fixture), "--format", "json"]


def _qualify_case(root: Path, destination: Path, candidate: str, case_id: str) -> dict[str, Any]:
    case = CASES[case_id]
    executable, executable_digest = _tool_identity(str(case["tool"]))
    command = _command(case, executable)
    started = datetime.now(UTC)
    result = _run(command, root)
    finished = datetime.now(UTC)
    report = result.stdout
    (destination / "scanner-report.json").write_text(report)
    (destination / "execution.log").write_text(
        json.dumps(
            {
                "command": command,
                "exit_code": result.returncode,
                "stderr": result.stderr,
            },
            indent=2,
        )
        + "\n"
    )
    actual = scanner_outcome(result.returncode, report, case["finding"])
    if actual != case["expected"]:
        raise ReceiptError(f"{case_id} did not produce its declared scanner outcome")
    rule_kind, rule_identity, rule_data = _rule_database(str(case["tool"]), report)
    (destination / "rule-database.json").write_text(json.dumps(rule_data, sort_keys=True, indent=2) + "\n")
    outputs = [
        {"id": identity, "path": path, "digest": file_digest(destination / path)}
        for identity, path in (
            ("scanner-report", "scanner-report.json"),
            ("rule-database", "rule-database.json"),
            ("execution-log", "execution.log"),
        )
    ]
    return {
        "schema": SCHEMA,
        "case_id": case_id,
        "expected": case["expected"],
        "actual": actual,
        "candidate": {"pipeline_commit": candidate},
        "fixture": {
            "path": case["fixture"],
            "digest": tree_digest(root / str(case["fixture"])),
        },
        "tool": {
            "name": case["tool"],
            "version": TOOLS[str(case["tool"])],
            "executable_digest": executable_digest,
        },
        "rule_database": {
            "kind": rule_kind,
            "identity": rule_identity,
        },
        "execution": {
            "executor": "github-actions",
            "repository": os.environ["GITHUB_REPOSITORY"],
            "workflow_path": WORKFLOW_PATH,
            "workflow_run_id": os.environ["GITHUB_RUN_ID"],
            "attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
        },
        "evidence": {"kind": "native-live-scanner", "outputs": outputs},
    }


def qualify(root: Path, destination: Path, candidate: str) -> None:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or not os.environ.get("GITHUB_RUN_ID")
        or not os.environ.get("GITHUB_RUN_ATTEMPT")
        or not os.environ.get("GITHUB_REPOSITORY")
    ):
        raise ReceiptError("live scanner qualification requires GitHub Actions")
    if len(candidate) != 40 or any(char not in "0123456789abcdef" for char in candidate):
        raise ReceiptError("candidate must be an exact 40-hex commit")
    head = _run(["git", "rev-parse", "HEAD"], root)
    if head.returncode != 0 or head.stdout.strip() != candidate:
        raise ReceiptError("scanner checkout does not match candidate")
    destination.mkdir(parents=True, exist_ok=False)
    receipts = []
    for case_id in CASES:
        case_dir = destination / case_id
        case_dir.mkdir()
        receipt = _qualify_case(root, case_dir, candidate, case_id)
        validate_receipt(receipt, root, candidate=candidate, evidence_root=case_dir)
        (case_dir / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        receipts.append({"case_id": case_id, "digest": file_digest(case_dir / "receipt.json")})
    (destination / "index.json").write_text(
        json.dumps({"candidate": candidate, "receipts": receipts}, indent=2) + "\n"
    )


def admit(root: Path, directory: Path, candidate: str) -> None:
    """Reject local/protocol artifacts before release code consults GitHub provenance."""
    receipts = {}
    for case_id in CASES:
        path = directory / case_id / "receipt.json"
        if not path.is_file():
            raise ReceiptError(f"missing hosted scanner receipt: {case_id}")
        receipt = json.loads(path.read_text())
        validate_receipt(receipt, root, candidate=candidate, evidence_root=path.parent)
        receipts[case_id] = receipt
    if {path.parent.name for path in directory.rglob("receipt.json")} != set(CASES):
        raise ReceiptError("unexpected live scanner receipt")
    run_ids = {
        (
            row["execution"]["repository"],
            row["execution"]["workflow_run_id"],
            row["execution"]["attempt"],
        )
        for row in receipts.values()
    }
    if len(run_ids) != 1:
        raise ReceiptError("scanner receipts span multiple hosted attempts")
    repository, run_id, attempt = run_ids.pop()
    api = _run(
        ["gh", "api", f"repos/{repository}/actions/runs/{run_id}/attempts/{attempt}"],
        root,
    )
    if api.returncode != 0:
        raise ReceiptError("cannot verify hosted scanner run provenance")
    run = json.loads(api.stdout)
    if (
        run.get("id") != int(run_id)
        or run.get("run_attempt") != attempt
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or run.get("path") != WORKFLOW_PATH
        or run.get("repository", {}).get("full_name") != repository
    ):
        raise ReceiptError("wrong or unsuccessful hosted scanner run")
    artifact_pages = json.loads(
        _run(
            [
                "gh",
                "api",
                "--paginate",
                "--slurp",
                f"repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100",
            ],
            root,
        ).stdout
    )
    artifacts = [artifact for page in artifact_pages for artifact in page["artifacts"]]
    name = f"live-scanner-receipts-{run_id}-{attempt}"
    matches = [
        artifact
        for artifact in artifacts
        if artifact.get("name") == name
        and not artifact.get("expired")
        and artifact.get("workflow_run", {}).get("id") == int(run_id)
    ]
    if len(matches) != 1:
        raise ReceiptError("missing or duplicate hosted scanner receipt artifact")
    artifact = matches[0]
    archive = directory / "github-live-scanner-receipts.zip"
    data = download(
        f"https://api.github.com/repos/{repository}/actions/artifacts/{artifact['id']}/zip",
        archive,
    )
    if artifact.get("digest") != digest(data):
        raise ReceiptError("hosted scanner artifact digest does not match GitHub")
    for case_id in CASES:
        if (
            archive_member(archive, f"{case_id}/receipt.json")
            != (directory / case_id / "receipt.json").read_bytes()
        ):
            raise ReceiptError("retained scanner receipt differs from GitHub artifact")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["qualify", "admit"])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()
    try:
        if args.operation == "qualify":
            qualify(args.root.resolve(), args.output, args.candidate)
        else:
            admit(args.root.resolve(), args.output, args.candidate)
    except (ReceiptError, OSError, json.JSONDecodeError, TypeError) as error:
        print(f"assurance: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
