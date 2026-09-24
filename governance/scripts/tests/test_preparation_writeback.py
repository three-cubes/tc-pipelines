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
ACTION = ROOT / "actions/preparation-writeback/action.yml"


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
    assert document["uv_version"] == "0.12.5"
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


def test_trusted_replay_uses_consumer_ruff_config_without_executing_project_code(
    tmp_path: Path,
) -> None:
    source, _ = repository(tmp_path)
    (source / "pyproject.toml").write_text(
        '[project]\nname = "ruff-consumer"\nversion = "0.1.0"\nrequires-python = ">=3.13,<3.14"\n',
        encoding="utf-8",
    )
    nested = source / "package"
    nested.mkdir()
    (source / "ruff-base.toml").write_text('target-version = "py310"\nline-length = 100\n', encoding="utf-8")
    (nested / "pyproject.toml").write_text(
        '[tool.ruff]\ntarget-version = "py313"\nline-length = 88\n', encoding="utf-8"
    )
    (nested / "ruff.toml").write_text('target-version = "py311"\nline-length = 100\n', encoding="utf-8")
    (nested / ".ruff.toml").write_text('extend = "../ruff-base.toml"\nline-length = 120\n', encoding="utf-8")
    (source / "-root_formatting.py").write_text(
        "result = compute(\n"
        "    first_argument, second_argument, third_argument,\n"
        "    fourth_argument, fifth_argument\n"
        ")\n",
        encoding="utf-8",
    )
    (nested / "nested_formatting.py").write_text(
        "result = compute(\n"
        "    first_argument, second_argument, third_argument,\n"
        "    fourth_argument, fifth_argument, sixth_argument\n"
        ")\n",
        encoding="utf-8",
    )
    (source / "execution_guard.py").write_text('raise RuntimeError("candidate code executed")\n')
    git(
        source,
        "add",
        "--",
        "pyproject.toml",
        "ruff-base.toml",
        "-root_formatting.py",
        "package",
        "execution_guard.py",
    )
    subprocess.run(["uvx", "--from", "uv==0.12.5", "uv", "lock"], cwd=source, check=True)
    git(source, "add", "uv.lock")
    git(source, "commit", "-qm", "add Ruff consumer configuration")
    head = git(source, "rev-parse", "HEAD")

    out = tmp_path / "evidence"
    out.mkdir()
    pre = snapshot(source, head, out)
    action = yaml.safe_load((ROOT / "actions/python-preparation/action.yml").read_text())
    script = action["runs"]["steps"][0]["run"]
    environment = {
        **os.environ,
        "GITHUB_ACTION_PATH": str(ROOT / "actions/python-preparation"),
        "RUFF_VERSION": "0.16.8",
        "UV_VERSION": "",
    }
    prepared = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script], cwd=source, env=environment, check=False
    )
    assert prepared.returncode == 0
    assert "result = compute(first_argument," in (source / "-root_formatting.py").read_text()
    assert "result = compute(first_argument," in (nested / "nested_formatting.py").read_text()
    assert 'raise RuntimeError("candidate code executed")' in (source / "execution_guard.py").read_text()

    receipt, patch = produce_after(source, pre, out)
    target = clone_at_head(source, tmp_path / "target")
    result = apply(target, receipt, patch, head)

    assert result.returncode == 0, result.stderr
    assert "result = compute(first_argument," in (target / "-root_formatting.py").read_text()
    assert "result = compute(first_argument," in (target / "package/nested_formatting.py").read_text()
    assert 'raise RuntimeError("candidate code executed")' in (target / "execution_guard.py").read_text()


def test_trusted_replay_keeps_ancestor_ruff_policy_with_nested_python_metadata(
    tmp_path: Path,
) -> None:
    source, _ = repository(tmp_path)
    (source / "pyproject.toml").write_text(
        '[project]\nname = "root-policy"\nversion = "0.1.0"\n'
        'requires-python = ">=3.13,<3.14"\n\n'
        '[tool.ruff]\ntarget-version = "py313"\nline-length = 120\n',
        encoding="utf-8",
    )
    nested = source / "package"
    nested.mkdir()
    (nested / "pyproject.toml").write_text(
        '[project]\nname = "nested-metadata"\nversion = "0.1.0"\nrequires-python = ">=3.13,<3.14"\n',
        encoding="utf-8",
    )
    module = nested / "module.py"
    module.write_text(
        "result = compute(\n"
        "    first_argument, second_argument, third_argument,\n"
        "    fourth_argument, fifth_argument, sixth_argument\n"
        ")\n",
        encoding="utf-8",
    )
    git(source, "add", "pyproject.toml", "package/pyproject.toml", "package/module.py")
    subprocess.run(["uvx", "--from", "uv==0.12.5", "uv", "lock"], cwd=source, check=True)
    git(source, "add", "uv.lock")
    git(source, "commit", "-qm", "add ancestor Ruff policy and nested metadata")
    head = git(source, "rev-parse", "HEAD")

    out = tmp_path / "evidence"
    out.mkdir()
    pre = snapshot(source, head, out)
    action = yaml.safe_load((ROOT / "actions/python-preparation/action.yml").read_text())
    environment = {
        **os.environ,
        "GITHUB_ACTION_PATH": str(ROOT / "actions/python-preparation"),
        "RUFF_VERSION": "0.16.8",
        "UV_VERSION": "",
    }
    prepared = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", action["runs"]["steps"][0]["run"]],
        cwd=source,
        env=environment,
        check=False,
    )
    assert prepared.returncode == 0
    prepared_source = module.read_text(encoding="utf-8")
    assert "result = compute(first_argument," in prepared_source

    receipt, patch = produce_after(source, pre, out)
    target = clone_at_head(source, tmp_path / "target")
    result = apply(target, receipt, patch, head)

    assert result.returncode == 0, result.stderr
    assert "result = compute(first_argument," in (target / "package/module.py").read_text()


def test_trusted_policy_repairs_a_stale_uv_lock_and_replays_it(tmp_path: Path) -> None:
    source, _ = repository(tmp_path)
    pyproject = source / "pyproject.toml"
    pyproject.write_text('[project]\nname = "fixture"\nversion = "0.1.0"\nrequires-python = ">=3.12"\n')
    (source / "module.py").write_text("value = 1\n")
    subprocess.run(["uvx", "--from", "uv==0.12.5", "uv", "lock"], cwd=source, check=True)
    git(source, "add", "module.py", "pyproject.toml", "uv.lock")
    git(source, "commit", "-qm", "add locked project")
    pyproject.write_text(pyproject.read_text().replace('version = "0.1.0"', 'version = "0.2.0"'))
    git(source, "add", "pyproject.toml")
    git(source, "commit", "-qm", "change project without lock")
    head = git(source, "rev-parse", "HEAD")
    out = tmp_path / "evidence"
    out.mkdir()
    pre = snapshot(source, head, out)
    subprocess.run(["uvx", "--from", "uv==0.12.5", "uv", "lock"], cwd=source, check=True)
    receipt, patch = produce_after(source, pre, out)
    assert "uv.lock" in {entry["path"] for entry in json.loads(patch.read_text())["entries"]}

    target = clone_at_head(source, tmp_path / "locked-target")
    result = apply(target, receipt, patch, head)

    assert result.returncode == 0, result.stderr
    assert 'version = "0.2.0"' in (target / "uv.lock").read_text()


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


@pytest.mark.parametrize("relative", ["pkg/__init__.py", "pkg/_helpers.py"])
def test_producer_accepts_standard_underscored_python_module_paths(tmp_path: Path, relative: str) -> None:
    source, _ = repository(tmp_path)
    module = source / relative
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text("value = 1  \n")
    git(source, "add", relative)
    git(source, "commit", "-qm", "add module")
    head = git(source, "rev-parse", "HEAD")
    out = tmp_path / "evidence"
    out.mkdir()
    pre = snapshot(source, head, out)
    module.write_text("value = 1\n")

    _, patch = produce_after(source, pre, out)

    assert [entry["path"] for entry in json.loads(patch.read_text())["entries"]] == [relative]


def test_snapshot_accepts_tracked_symlink_without_making_it_a_patch_target(
    tmp_path: Path,
) -> None:
    source, _ = repository(tmp_path)
    (source / "target.txt").write_text("target\n")
    (source / "linked.txt").symlink_to("target.txt")
    git(source, "add", "target.txt", "linked.txt")
    git(source, "commit", "-qm", "add tracked link")
    head = git(source, "rev-parse", "HEAD")
    out = tmp_path / "evidence"
    out.mkdir()

    pre = snapshot(source, head, out)
    document = json.loads(pre.read_text())

    assert document["head_tree"] == git(source, "rev-parse", "HEAD^{tree}")
    assert "linked.txt" not in {entry["path"] for entry in document["entries"]}


def test_snapshot_accepts_a_tracked_gitlink_without_making_it_a_patch_target(
    tmp_path: Path,
) -> None:
    source, head = repository(tmp_path)
    git(source, "update-index", "--add", "--cacheinfo", f"160000,{head},vendor/component")
    git(source, "commit", "-qm", "add gitlink")
    (source / "vendor/component").mkdir(parents=True)
    head = git(source, "rev-parse", "HEAD")
    out = tmp_path / "evidence"
    out.mkdir()

    pre = snapshot(source, head, out)
    document = json.loads(pre.read_text())

    assert document["head_tree"] == git(source, "rev-parse", "HEAD^{tree}")
    assert "vendor/component" not in {entry["path"] for entry in document["entries"]}


def test_composite_apply_mode_supplies_the_required_policy() -> None:
    action = yaml.safe_load(ACTION.read_text())
    assert action["inputs"]["expected-policy"]["default"] == "python-ruff-v1"
    step = action["runs"]["steps"][0]
    assert step["env"]["EXPECTED_POLICY"] == "${{ inputs.expected-policy }}"
    assert '--expected-policy "$EXPECTED_POLICY"' in step["run"]


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
