"""Real-Git controls for the deterministic preparation receipt boundary."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / "actions/preparation-writeback/preparation_writeback.py"
WRITER = ROOT / ".github/workflows/preparation-writeback.yml"


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, text=True, capture_output=True).stdout.strip()


def invoke(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *map(str, args)],
        text=True,
        capture_output=True,
        check=False,
    )


def repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "source"
    root.mkdir()
    git(root, "init", "-q", "--initial-branch=main")
    git(root, "config", "user.name", "contract")
    git(root, "config", "user.email", "contract@example.invalid")
    (root / "tracked.txt").write_text("before\n")
    (root / "module.py").write_text("value = 1  \n")
    git(root, "add", "tracked.txt", "module.py")
    git(root, "commit", "-qm", "initial")
    return root, git(root, "rev-parse", "HEAD")


def snapshot(root: Path, head: str, out: Path) -> Path:
    pre = out / "pre.json"
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
    return pre


def produce_after(root: Path, pre: Path, out: Path) -> tuple[Path, Path]:
    receipt = out / "receipt.json"
    patch = out / "patch.json"
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


def produce(root: Path, head: str, out: Path) -> tuple[Path, Path]:
    pre = snapshot(root, head, out)
    (root / "module.py").write_text("value = 1\n")
    return produce_after(root, pre, out)


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
        "--expected-policy",
        "python-ruff-v1",
        "--expected-head-ref",
        "feature/prepare",
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
    document["patch_bytes"] = patch.stat().st_size
    receipt.write_text(json.dumps(document, sort_keys=True) + "\n")


def test_credential_free_producer_and_apply_round_trip_use_real_git(
    tmp_path: Path,
) -> None:
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
    assert all(
        "content_base64" not in entry for entry in json.loads((out / "pre.json").read_text())["entries"]
    )
    target = clone_at_head(source, tmp_path / "target")
    result = apply(target, receipt, patch, head)
    assert result.returncode == 0, result.stderr
    assert (target / "module.py").read_text() == "value = 1\n"

    replace_patch(
        receipt,
        patch,
        lambda data: data["entries"][0].update(
            content_base64=base64.b64encode(b"import os\nos.system('not a formatter')\n").decode("ascii")
        ),
    )
    untrusted_target = clone_at_head(source, tmp_path / "untrusted-target")
    result = apply(untrusted_target, receipt, patch, head)
    assert result.returncode == 1
    assert "trusted Ruff replay" in result.stderr


def test_writer_accepts_only_the_declared_trusted_transformation(
    tmp_path: Path,
) -> None:
    source, head = repository(tmp_path)
    out = tmp_path / "evidence"
    out.mkdir()
    pre = snapshot(source, head, out)
    (source / "module.py").write_text("value = 1\n")
    receipt, patch = produce_after(source, pre, out)

    target = clone_at_head(source, tmp_path / "target")
    result = apply(target, receipt, patch, head)
    assert result.returncode == 0, result.stderr
    assert (target / "module.py").read_text() == "value = 1\n"


def test_snapshot_scales_with_repository_identity_not_repository_content(
    tmp_path: Path,
) -> None:
    source, head = repository(tmp_path)
    (source / "large.bin").write_bytes(b"x" * (17 * 1024 * 1024))
    git(source, "add", "large.bin")
    git(source, "commit", "-qm", "large fixture")
    head = git(source, "rev-parse", "HEAD")
    out = tmp_path / "evidence"
    out.mkdir()
    pre = snapshot(source, head, out)
    assert pre.stat().st_size < 4096
    assert all("content_base64" not in entry for entry in json.loads(pre.read_text())["entries"])
    receipt, patch = produce_after(source, pre, out)
    assert receipt.exists()
    assert patch.stat().st_size < 4096


def test_snapshot_retains_git_valid_whitespace_filenames(tmp_path: Path) -> None:
    source, _ = repository(tmp_path)
    (source / " leading-name.txt").write_text("identity\n")
    git(source, "add", " leading-name.txt")
    git(source, "commit", "-qm", "whitespace filename")
    head = git(source, "rev-parse", "HEAD")
    out = tmp_path / "evidence"
    out.mkdir()
    pre = snapshot(source, head, out)
    assert " leading-name.txt" in {entry["path"] for entry in json.loads(pre.read_text())["entries"]}


@pytest.mark.parametrize("change", ["untracked", "delete"])
def test_producer_rejects_changes_outside_the_declared_transformation(tmp_path: Path, change: str) -> None:
    source, head = repository(tmp_path)
    out = tmp_path / "evidence"
    out.mkdir()
    pre = snapshot(source, head, out)
    if change == "untracked":
        (source / "only-generated.py").write_text("generated\n")
    else:
        (source / "tracked.txt").unlink()
    result = invoke(
        "produce",
        "--snapshot",
        pre,
        "--receipt",
        out / "receipt.json",
        "--patch",
        out / "patch.json",
        "--root",
        source,
    )
    assert result.returncode == 1
    assert "trusted policy" in result.stderr


def test_changed_and_push_use_real_git_without_persistent_credentials(
    tmp_path: Path,
) -> None:
    source, head = repository(tmp_path)
    clean = invoke("changed", "--root", source)
    assert clean.returncode == 0
    assert clean.stdout.strip() == "false"
    (source / "untracked.txt").write_text("generated\n")
    dirty = invoke("changed", "--root", source)
    assert dirty.returncode == 0
    assert dirty.stdout.strip() == "true"
    git(source, "add", "untracked.txt")
    git(source, "commit", "-qm", "prepared")
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", bare)
    git(source, "remote", "add", "origin", str(bare))
    git(source, "push", "-q", "origin", f"{head}:refs/heads/feature/prepare")
    environment = {**os.environ, "GITHUB_APP_TOKEN": "opaque-test-token"}
    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "push",
            "--root",
            str(source),
            "--remote",
            "origin",
            "--head-ref",
            "feature/prepare",
            "--expected-head",
            head,
        ],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "opaque-test-token" not in result.stdout + result.stderr
    assert git(bare, "rev-parse", "refs/heads/feature/prepare") == git(source, "rev-parse", "HEAD")
    assert (
        subprocess.run(
            ["git", "config", "--local", "--get-regexp", r"^http\\..*extraheader$"],
            cwd=source,
            text=True,
            capture_output=True,
            check=False,
        ).returncode
        == 1
    )


def test_producer_accepts_tracked_python_under_dot_prefixed_source_directory(
    tmp_path: Path,
) -> None:
    source, _ = repository(tmp_path)
    hidden_source = source / ".github" / "actions" / "check.py"
    hidden_source.parent.mkdir(parents=True)
    hidden_source.write_text("value = 1  \n")
    git(source, "add", hidden_source.relative_to(source))
    git(source, "commit", "-qm", "add workflow implementation")
    head = git(source, "rev-parse", "HEAD")
    out = tmp_path / "evidence"
    out.mkdir()
    pre = snapshot(source, head, out)
    hidden_source.write_text("value = 1\n")

    receipt, patch = produce_after(source, pre, out)

    assert receipt.exists()
    assert [entry["path"] for entry in json.loads(patch.read_text())["entries"]] == [
        ".github/actions/check.py"
    ]


def test_authenticated_fetch_uses_real_git_without_persistent_credentials(
    tmp_path: Path,
) -> None:
    source, head = repository(tmp_path)
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", bare)
    git(source, "remote", "add", "origin", str(bare))
    git(source, "push", "-q", "origin", f"{head}:refs/heads/feature/prepare")
    target = tmp_path / "target"
    git(tmp_path, "init", "-q", target)
    environment = {**os.environ, "GITHUB_READ_TOKEN": "opaque-read-token"}
    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "fetch",
            "--root",
            str(target),
            "--remote-url",
            str(bare),
            "--head-sha",
            head,
        ],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "opaque-read-token" not in result.stdout + result.stderr
    assert git(target, "rev-parse", f"{head}^{{commit}}") == head
    assert (
        subprocess.run(
            ["git", "config", "--local", "--get-regexp", r"^http\\..*extraheader$"],
            cwd=target,
            text=True,
            capture_output=True,
            check=False,
        ).returncode
        == 1
    )


def test_private_consumer_fetch_receives_the_read_token_in_the_fetch_step() -> None:
    workflow = yaml.safe_load(WRITER.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["write-preparation"]["steps"]
    fetch = next(step for step in steps if step.get("name") == "Validate and apply without executing PR code")
    assert "preparation_writeback.py fetch" in fetch["run"]
    assert fetch["env"]["GITHUB_READ_TOKEN"] == "${{ github.token }}"


@pytest.mark.parametrize(
    "entries",
    [
        ("preparation-patch.json", "preparation-receipt.json"),
        ("preparation-receipt.json", "preparation-patch.json"),
    ],
)
def test_receipt_artifact_accepts_exact_names_in_any_zip_order(
    tmp_path: Path, entries: tuple[str, str]
) -> None:
    archive = tmp_path / "receipt.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for name in entries:
            output.writestr(name, b"{}")
    destination = tmp_path / "evidence"
    result = invoke("artifact", "--archive", archive, "--output", destination)
    assert result.returncode == 0, result.stderr
    assert (destination / "preparation-receipt.json").read_bytes() == b"{}"
    assert (destination / "preparation-patch.json").read_bytes() == b"{}"


@pytest.mark.parametrize(
    "entries",
    [
        ("preparation-receipt.json", "preparation-receipt.json"),
        ("nested/preparation-receipt.json", "preparation-patch.json"),
        ("preparation-receipt.json", "unexpected.json"),
    ],
)
def test_receipt_artifact_rejects_ambiguous_or_nested_entries(
    tmp_path: Path, entries: tuple[str, str]
) -> None:
    archive = tmp_path / "receipt.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for position, name in enumerate(entries):
            if entries[0] == entries[1] and position == 1:
                with pytest.warns(UserWarning, match="Duplicate name"):
                    output.writestr(name, b"{}")
            else:
                output.writestr(name, b"{}")
    result = invoke("artifact", "--archive", archive, "--output", tmp_path / "evidence")
    assert result.returncode == 1
    assert "preparation" in result.stderr


def test_receipt_artifact_rejects_oversized_extracted_stream(tmp_path: Path) -> None:
    archive = tmp_path / "receipt.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr("preparation-receipt.json", b"x" * (2 * 1024 * 1024 + 1))
        output.writestr("preparation-patch.json", b"{}")
    result = invoke("artifact", "--archive", archive, "--output", tmp_path / "evidence")
    assert result.returncode == 1
    assert "preparation" in result.stderr


@pytest.mark.parametrize(
    "defect",
    [
        "wrong-head",
        "wrong-pr",
        "wrong-run",
        "wrong-head-ref",
        "stale",
        "fork",
        "altered-patch",
        "oversize",
        "path-traversal",
        "symlink",
        "mode",
        "moved-head",
        "duplicate-path",
        "invalid-base64",
        "future",
        "altered-pre-tree",
        "altered-post-tree",
        "untrusted-policy",
        "unexpected-receipt-field",
        "unexpected-patch-field",
    ],
)
def test_apply_rejects_untrusted_or_nonidentical_preparation_evidence(tmp_path: Path, defect: str) -> None:
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
    elif defect == "wrong-head-ref":
        document["head_ref"] = "other-branch"
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
    elif defect == "duplicate-path":
        replace_patch(receipt, patch, lambda data: data["entries"].append(data["entries"][0]))
    elif defect == "invalid-base64":
        replace_patch(receipt, patch, lambda data: data["entries"][0].update(content_base64="%%%"))
    elif defect == "future":
        document["issued_at"] = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    elif defect == "altered-pre-tree":
        document["pre_tree"] = "sha256:" + "0" * 64
    elif defect == "altered-post-tree":
        document["post_tree"] = "sha256:" + "0" * 64
    elif defect == "untrusted-policy":
        document["policy"] = "candidate-arbitrary-rewrite-v1"
    elif defect == "unexpected-receipt-field":
        document["surplus"] = True
    elif defect == "unexpected-patch-field":
        replace_patch(receipt, patch, lambda data: data.update(surplus=True))
    if defect in {
        "wrong-head",
        "wrong-pr",
        "wrong-run",
        "wrong-head-ref",
        "stale",
        "fork",
        "oversize",
        "future",
        "altered-pre-tree",
        "altered-post-tree",
        "untrusted-policy",
        "unexpected-receipt-field",
    }:
        receipt.write_text(json.dumps(document, sort_keys=True) + "\n")
    target = clone_at_head(source, tmp_path / "target")
    result = apply(target, receipt, patch, head)
    assert result.returncode == 1
    assert "preparation" in result.stderr
