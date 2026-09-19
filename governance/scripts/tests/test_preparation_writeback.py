"""Real-Git controls for the deterministic preparation receipt boundary."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / "governance/scripts/preparation_writeback.py"


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()


def invoke(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *map(str, args)], text=True, capture_output=True
    )


def repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "source"
    root.mkdir()
    git(root, "init", "-q", "--initial-branch=main")
    git(root, "config", "user.name", "contract")
    git(root, "config", "user.email", "contract@example.invalid")
    (root / "tracked.txt").write_text("before\n")
    git(root, "add", "tracked.txt")
    git(root, "commit", "-qm", "initial")
    return root, git(root, "rev-parse", "HEAD")


def produce(root: Path, head: str, out: Path) -> tuple[Path, Path]:
    pre = out / "pre.json"
    receipt = out / "receipt.json"
    patch = out / "patch.json"
    result = invoke(
        "snapshot",
        "--repository",
        "three-cubes/example",
        "--pull-request",
        "17",
        "--head-sha",
        head,
        "--head-repository",
        "three-cubes/example",
        "--head-ref",
        "feature/prepare",
        "--workflow-run-id",
        "99",
        "--workflow-run-attempt",
        "2",
        "--output",
        pre,
        "--root",
        root,
    )
    assert result.returncode == 0, result.stderr
    (root / "tracked.txt").write_text("after\n")
    (root / "generated.txt").write_text("generated\n")
    result = invoke(
        "produce",
        "--snapshot",
        pre,
        "--receipt",
        receipt,
        "--patch",
        patch,
        "--root",
        root,
    )
    assert result.returncode == 0, result.stderr
    return receipt, patch


def clone_at_head(source: Path, destination: Path) -> Path:
    subprocess.run(["git", "clone", "-q", str(source), str(destination)], check=True)
    return destination


def apply(destination: Path, receipt: Path, patch: Path, head: str) -> subprocess.CompletedProcess[str]:
    return invoke(
        "apply",
        "--receipt",
        receipt,
        "--patch",
        patch,
        "--repository",
        "three-cubes/example",
        "--pull-request",
        "17",
        "--expected-head",
        head,
        "--workflow-run-id",
        "99",
        "--workflow-run-attempt",
        "2",
        "--root",
        destination,
    )


def patch_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def replace_patch(receipt: Path, patch: Path, update) -> None:
    data = json.loads(patch.read_text())
    update(data)
    patch.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n")
    document = json.loads(receipt.read_text())
    document["patch_digest"] = patch_digest(patch)
    receipt.write_text(json.dumps(document, sort_keys=True) + "\n")


def test_credential_free_producer_and_apply_round_trip_use_real_git(tmp_path: Path) -> None:
    source, head = repository(tmp_path)
    out = tmp_path / "evidence"
    out.mkdir()
    receipt, patch = produce(source, head, out)
    document = json.loads(receipt.read_text())
    assert document["schema"] == "tc.sdlc/preparation-receipt/v1"
    assert document["head_sha"] == head
    assert document["head_tree"] == git(source, "rev-parse", f"{head}^{{tree}}")
    assert document["pre_tree"] != document["post_tree"]
    assert document["patch_digest"] == patch_digest(patch)
    target = clone_at_head(source, tmp_path / "target")
    result = apply(target, receipt, patch, head)
    assert result.returncode == 0, result.stderr
    assert (target / "tracked.txt").read_text() == "after\n"
    assert (target / "generated.txt").read_text() == "generated\n"


@pytest.mark.parametrize(
    "defect",
    [
        "wrong-head",
        "wrong-pr",
        "wrong-run",
        "stale",
        "fork",
        "altered-patch",
        "oversize",
        "path-traversal",
        "symlink",
        "mode",
        "moved-head",
    ],
)
def test_apply_rejects_untrusted_or_nonidentical_preparation_evidence(
    tmp_path: Path, defect: str
) -> None:
    source, head = repository(tmp_path)
    out = tmp_path / "evidence"
    out.mkdir()
    receipt, patch = produce(source, head, out)
    document = json.loads(receipt.read_text())
    if defect == "wrong-head":
        document["head_sha"] = "f" * 40
    elif defect == "wrong-pr":
        document["pull_request"] = 18
    elif defect == "wrong-run":
        document["workflow_run_attempt"] = 3
    elif defect == "stale":
        document["issued_at"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    elif defect == "fork":
        document["head_repository"] = "attacker/fork"
    elif defect == "altered-patch":
        patch.write_bytes(patch.read_bytes() + b" ")
    elif defect == "oversize":
        document["patch_bytes"] = 1
    elif defect == "path-traversal":
        replace_patch(receipt, patch, lambda data: data["entries"][0].update(path="../escape"))
    elif defect == "symlink":
        replace_patch(receipt, patch, lambda data: data["entries"][0].update(kind="symlink"))
    elif defect == "mode":
        replace_patch(receipt, patch, lambda data: data["entries"][0].update(mode=0o777))
    elif defect == "moved-head":
        (source / "other.txt").write_text("new head\n")
        git(source, "add", "other.txt")
        git(source, "commit", "-qm", "move head")
    if defect in {"wrong-head", "wrong-pr", "wrong-run", "stale", "fork", "oversize"}:
        receipt.write_text(json.dumps(document, sort_keys=True) + "\n")
    target = clone_at_head(source, tmp_path / "target")
    result = apply(target, receipt, patch, head)
    assert result.returncode == 1
    assert "preparation" in result.stderr
