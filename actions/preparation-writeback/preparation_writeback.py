"""Create and verify deterministic-preparation writeback evidence.

The producer runs without credentials in the pull-request workflow.  The
consumer is deliberately small: it verifies an immutable receipt and writes
ordinary files into a detached temporary checkout.  It never invokes project
code, applies a git patch, or accepts a path outside that checkout.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

RECEIPT_SCHEMA = "tc.sdlc/preparation-receipt/v1"
PATCH_SCHEMA = "tc.sdlc/preparation-patch/v1"
MAX_PATCH_BYTES = 1024 * 1024
MAX_RECEIPT_BYTES = MAX_PATCH_BYTES * 2
MAX_ARTIFACT_BYTES = MAX_RECEIPT_BYTES + MAX_PATCH_BYTES
MAX_RECEIPT_AGE = timedelta(minutes=30)
ALLOWED_MODES = {0o644, 0o755}
# A receipt is not authority to make the bot author an arbitrary candidate
# rewrite. The policy is a closed trusted registry: its implementation and
# exact tool version are owned here, never by a candidate's workflow command.
POLICY = "python-ruff-v1"
RUFF_VERSION = "0.16.8"
UV_VERSION = "0.12.5"


def permitted_policy_path(path: str) -> bool:
    if path == "uv.lock":
        return True
    return bool(
        re.fullmatch(
            r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.pyi?",
            path,
        )
    )


def replay_trusted_policy(root: Path) -> tuple[list[dict[str, Any]], str]:
    """Replay pinned Ruff over tracked Python without executing candidate code."""
    paths = [
        os.fsdecode(path)
        for path in run_git_bytes(root, "ls-files", "-z", "--", "*.py", "*.pyi").split(b"\0")
        if path
    ]
    if not paths:
        return manifest(root, include_content=True)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"GH_TOKEN", "GITHUB_APP_TOKEN", "GITHUB_READ_TOKEN"}
    }
    if (root / "pyproject.toml").is_file():
        locked = subprocess.run(
            ["uvx", "--from", f"uv=={UV_VERSION}", "uv", "lock"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        if locked.returncode:
            fail(f"trusted uv lock failed: {locked.stderr.strip()}")
    for arguments in (
        [
            "check",
            "--force-exclude",
            "--select",
            "E,F,I,UP,B,S,RUF",
            "--target-version",
            "py312",
            "--ignore",
            "E501,RUF022",
            "--fix",
            "--no-unsafe-fixes",
            "--exit-zero",
            "--",
            *paths,
        ],
        [
            "format",
            "--force-exclude",
            "--line-length",
            "110",
            "--target-version",
            "py312",
            "--",
            *paths,
        ],
    ):
        result = subprocess.run(
            ["uvx", "--from", f"ruff=={RUFF_VERSION}", "ruff", *arguments],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        if result.returncode:
            fail(f"trusted Ruff replay failed: {result.stderr.strip()}")
    return manifest(root, include_content=True)


class PreparationError(ValueError):
    """Evidence was not safe to apply."""


def fail(message: str) -> None:
    raise PreparationError(message)


def run_git(root: Path, *arguments: str) -> str:
    result = subprocess.run(["git", *arguments], cwd=root, text=True, capture_output=True, check=False)
    if result.returncode:
        fail(f"git {' '.join(arguments)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def run_git_bytes(root: Path, *arguments: str) -> bytes:
    result = subprocess.run(["git", *arguments], cwd=root, capture_output=True, check=False)
    if result.returncode:
        fail(f"git {' '.join(arguments)} failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def validate_relative_path(raw_path: str) -> PurePosixPath:
    if not isinstance(raw_path, str) or not raw_path:
        fail("patch path must be a non-empty string")
    path = PurePosixPath(raw_path)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        fail(f"unsafe patch path: {raw_path!r}")
    if any(part in {"", ".git"} for part in path.parts):
        fail(f"unsafe patch path: {raw_path!r}")
    if str(path) != raw_path or "\\" in raw_path:
        fail(f"unsafe patch path: {raw_path!r}")
    return path


def checked_file(root: Path, relative: str) -> Path:
    path = validate_relative_path(relative)
    candidate = root.joinpath(*path.parts)
    parent = root
    for component in path.parts[:-1]:
        parent = parent / component
        if parent.exists() and stat.S_ISLNK(os.lstat(parent).st_mode):
            fail(f"unsafe symlink parent: {relative!r}")
    if candidate.exists() or candidate.is_symlink():
        mode = os.lstat(candidate).st_mode
        if stat.S_ISLNK(mode):
            fail(f"unsafe symlink target: {relative!r}")
        if not stat.S_ISREG(mode):
            fail(f"unsafe non-file target: {relative!r}")
    return candidate


def visible_paths(root: Path) -> list[str]:
    tracked = run_git_bytes(root, "ls-files", "-z").split(b"\0")
    untracked = run_git_bytes(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
    paths = {os.fsdecode(piece) for piece in tracked + untracked if piece}
    return sorted(paths)


def manifest(root: Path, *, include_content: bool) -> tuple[list[dict[str, Any]], str]:
    entries: list[dict[str, Any]] = []
    for relative in visible_paths(root):
        relative_path = validate_relative_path(relative)
        candidate = root.joinpath(*relative_path.parts)
        if candidate.is_symlink() or (candidate.exists() and candidate.is_dir()):
            # The committed head tree binds symlink/gitlink identity. They are
            # never inputs to, or writable targets of, the preparation policy.
            continue
        path = checked_file(root, relative)
        if not path.exists():
            # `git ls-files` retains deleted tracked paths.  A content-state
            # manifest describes the working tree, so a deleted file is absent.
            continue
        mode = stat.S_IMODE(os.lstat(path).st_mode)
        if mode & ~0o777:
            fail(f"unsafe file mode: {relative!r}")
        content = path.read_bytes()
        entry: dict[str, Any] = {
            "path": relative,
            "mode": mode,
            "digest": sha256(content),
        }
        if include_content:
            entry["content_base64"] = base64.b64encode(content).decode("ascii")
        entries.append(entry)
    state = sha256(
        canonical_json(
            [{key: value for key, value in entry.items() if key != "content_base64"} for entry in entries]
        )
    )
    return entries, state


def read_document(path: Path, *, limit: int | None = MAX_RECEIPT_BYTES) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        fail(f"cannot read evidence: {error}")
    if limit is not None and len(raw) > limit:
        fail("evidence document is too large")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        fail(f"invalid JSON evidence: {error}")
    if not isinstance(value, dict):
        fail("evidence document must be a JSON object")
    return value


def write_document(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(value))


def required(document: dict[str, Any], fields: set[str], label: str) -> None:
    if set(document) != fields:
        fail(f"{label} has unexpected or missing fields")


def snapshot(arguments: argparse.Namespace) -> None:
    root = arguments.root.resolve()
    head = run_git(root, "rev-parse", "HEAD")
    if head != arguments.head_sha:
        fail("snapshot head does not match supplied head SHA")
    entries, pre_tree = manifest(root, include_content=False)
    document = {
        "schema": "tc.sdlc/preparation-snapshot/v1",
        "repository": arguments.repository,
        "pull_request": arguments.pull_request,
        "head_sha": head,
        "head_tree": run_git(root, "rev-parse", "HEAD^{tree}"),
        "head_repository": arguments.head_repository,
        "head_ref": arguments.head_ref,
        "workflow_run_id": arguments.workflow_run_id,
        "workflow_run_attempt": arguments.workflow_run_attempt,
        "pre_tree": pre_tree,
        "entries": entries,
    }
    write_document(arguments.output, document)


def produce(arguments: argparse.Namespace) -> None:
    # Snapshots are a producer-local handoff, never privileged input.  They
    # contain only state identity and must scale with file count, not file size.
    snapshot_document = read_document(arguments.snapshot, limit=None)
    snapshot_fields = {
        "schema",
        "repository",
        "pull_request",
        "head_sha",
        "head_tree",
        "head_repository",
        "head_ref",
        "workflow_run_id",
        "workflow_run_attempt",
        "pre_tree",
        "entries",
    }
    required(snapshot_document, snapshot_fields, "snapshot")
    if snapshot_document["schema"] != "tc.sdlc/preparation-snapshot/v1":
        fail("unsupported snapshot schema")
    root = arguments.root.resolve()
    if run_git(root, "rev-parse", "HEAD") != snapshot_document["head_sha"]:
        fail("head moved while producing preparation evidence")
    if run_git(root, "rev-parse", "HEAD^{tree}") != snapshot_document["head_tree"]:
        fail("head tree moved while producing preparation evidence")
    original_entries = snapshot_document["entries"]
    if not isinstance(original_entries, list):
        fail("snapshot entries must be a list")
    before: dict[str, dict[str, Any]] = {}
    for entry in original_entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "mode", "digest"}:
            fail("invalid snapshot entry")
        validate_relative_path(entry["path"])
        before[entry["path"]] = entry
    current_entries, post_tree = manifest(root, include_content=True)
    after = {entry["path"]: entry for entry in current_entries}
    patch_entries: list[dict[str, Any]] = []
    for path in sorted(set(before) | set(after)):
        old, new = before.get(path), after.get(path)
        if new is None or old is None:
            fail("trusted policy cannot add or delete paths")
        if old["digest"] != new["digest"] or old["mode"] != new["mode"]:
            if not permitted_policy_path(path):
                fail(f"trusted policy does not permit path: {path}")
            if old["mode"] != new["mode"]:
                fail("trusted policy cannot change file modes")
            patch_entries.append(
                {
                    "path": path,
                    "kind": "file",
                    "mode": new["mode"],
                    "content_base64": new["content_base64"],
                }
            )
    patch_document = {"schema": PATCH_SCHEMA, "entries": patch_entries}
    patch_bytes = canonical_json(patch_document)
    if len(patch_bytes) > MAX_PATCH_BYTES:
        fail("preparation patch exceeds bounded size")
    arguments.patch.parent.mkdir(parents=True, exist_ok=True)
    arguments.patch.write_bytes(patch_bytes)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "policy": POLICY,
        "repository": snapshot_document["repository"],
        "pull_request": snapshot_document["pull_request"],
        "head_sha": snapshot_document["head_sha"],
        "head_tree": snapshot_document["head_tree"],
        "head_repository": snapshot_document["head_repository"],
        "head_ref": snapshot_document["head_ref"],
        "workflow_run_id": snapshot_document["workflow_run_id"],
        "workflow_run_attempt": snapshot_document["workflow_run_attempt"],
        "pre_tree": snapshot_document["pre_tree"],
        "post_tree": post_tree,
        "patch_digest": sha256(patch_bytes),
        "patch_bytes": len(patch_bytes),
        "issued_at": datetime.now(UTC).isoformat(),
    }
    write_document(arguments.receipt, receipt)


def validate_receipt(
    document: dict[str, Any],
    arguments: argparse.Namespace,
    root: Path,
    patch_bytes: bytes,
) -> None:
    fields = {
        "schema",
        "policy",
        "repository",
        "pull_request",
        "head_sha",
        "head_tree",
        "head_repository",
        "head_ref",
        "workflow_run_id",
        "workflow_run_attempt",
        "pre_tree",
        "post_tree",
        "patch_digest",
        "patch_bytes",
        "issued_at",
    }
    required(document, fields, "receipt")
    if document["schema"] != RECEIPT_SCHEMA:
        fail("unsupported receipt schema")
    if document["policy"] != POLICY or document["policy"] != arguments.expected_policy:
        fail("receipt policy is not trusted")
    if document["repository"] != arguments.repository:
        fail("receipt repository does not match consumer repository")
    if document["pull_request"] != arguments.pull_request:
        fail("receipt pull request does not match workflow-run pull request")
    if (
        document["workflow_run_id"] != arguments.workflow_run_id
        or document["workflow_run_attempt"] != arguments.workflow_run_attempt
    ):
        fail("receipt workflow run identity does not match artifact source")
    if document["head_repository"] != arguments.repository:
        fail("fork preparation evidence is not eligible for writeback")
    if document["head_sha"] != arguments.expected_head:
        fail("receipt head does not match expected pull-request head")
    if document["head_ref"] != arguments.expected_head_ref:
        fail("receipt head ref does not match expected pull-request head ref")
    if run_git(root, "rev-parse", "HEAD") != arguments.expected_head:
        fail("temporary checkout does not match expected pull-request head")
    if run_git(root, "rev-parse", "HEAD^{tree}") != document["head_tree"]:
        fail("receipt head tree does not match temporary checkout")
    if not isinstance(document["patch_bytes"], int) or document["patch_bytes"] != len(patch_bytes):
        fail("receipt patch size does not match patch artifact")
    if len(patch_bytes) > MAX_PATCH_BYTES:
        fail("preparation patch exceeds bounded size")
    if document["patch_digest"] != sha256(patch_bytes):
        fail("receipt patch digest does not match patch artifact")
    try:
        issued_at = datetime.fromisoformat(document["issued_at"])
    except (AttributeError, ValueError) as error:
        raise PreparationError("receipt issued_at is invalid") from error
    if issued_at.tzinfo is None:
        fail("receipt issued_at must include a timezone")
    now = datetime.now(UTC)
    if issued_at.astimezone(UTC) < now - MAX_RECEIPT_AGE or issued_at.astimezone(UTC) > now + timedelta(
        minutes=1
    ):
        fail("receipt is stale or from the future")
    for field in ("head_sha", "head_tree"):
        if (
            not isinstance(document[field], str)
            or len(document[field]) != 40
            or any(character not in "0123456789abcdef" for character in document[field])
        ):
            fail(f"receipt {field} is malformed")
    for field in ("pre_tree", "post_tree", "patch_digest"):
        if not isinstance(document[field], str) or not document[field].startswith("sha256:"):
            fail(f"receipt {field} is malformed")
    if not isinstance(document["pull_request"], int) or document["pull_request"] < 1:
        fail("receipt pull request is invalid")
    if not isinstance(document["workflow_run_id"], int) or not isinstance(
        document["workflow_run_attempt"], int
    ):
        fail("receipt workflow identity is invalid")


def validate_patch(patch_bytes: bytes) -> list[dict[str, Any]]:
    try:
        patch = json.loads(patch_bytes)
    except json.JSONDecodeError as error:
        raise PreparationError(f"invalid patch JSON: {error}") from error
    if not isinstance(patch, dict) or set(patch) != {"schema", "entries"} or patch["schema"] != PATCH_SCHEMA:
        fail("unsupported patch schema")
    entries = patch["entries"]
    if not isinstance(entries, list):
        fail("patch entries must be a list")
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            fail("patch entry is malformed")
        path = entry["path"]
        validate_relative_path(path)
        if path in seen:
            fail("patch contains duplicate paths")
        seen.add(path)
        if entry.get("kind") == "delete":
            if set(entry) != {"path", "kind"}:
                fail("delete entry is malformed")
        elif entry.get("kind") == "file":
            if set(entry) != {"path", "kind", "mode", "content_base64"}:
                fail("file entry is malformed")
            if not isinstance(entry["mode"], int) or entry["mode"] not in ALLOWED_MODES:
                fail("file entry has unsafe mode")
            try:
                base64.b64decode(entry["content_base64"], validate=True)
            except (TypeError, ValueError) as error:
                raise PreparationError("file entry content is invalid") from error
        else:
            fail("patch entry has unsupported kind")
    return entries


def validate_policy_entries(root: Path, entries: list[dict[str, Any]]) -> None:
    """Reject paths and mode changes outside the closed Ruff policy."""
    for entry in entries:
        if entry["kind"] != "file":
            fail("trusted policy cannot delete paths")
        if not permitted_policy_path(entry["path"]):
            fail("trusted policy does not permit this path")
        target = checked_file(root, entry["path"])
        if not target.exists():
            fail("trusted policy cannot add paths")
        current_mode = stat.S_IMODE(os.lstat(target).st_mode)
        if entry["mode"] != current_mode:
            fail("trusted policy cannot change file modes")


def expected_replay_entries(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Render the one canonical patch that a trusted Ruff replay produced."""
    before_by_path = {entry["path"]: entry for entry in before}
    after_by_path = {entry["path"]: entry for entry in after}
    entries: list[dict[str, Any]] = []
    for path in sorted(set(before_by_path) | set(after_by_path)):
        old, new = before_by_path.get(path), after_by_path.get(path)
        if old is None or new is None:
            fail("trusted Ruff replay attempted to add or delete a path")
        if old["mode"] != new["mode"]:
            fail("trusted Ruff replay attempted to change a file mode")
        if old["digest"] != new["digest"]:
            if not permitted_policy_path(path):
                fail("trusted Ruff replay changed a path outside its policy")
            entries.append(
                {
                    "path": path,
                    "kind": "file",
                    "mode": new["mode"],
                    "content_base64": new["content_base64"],
                }
            )
    return entries


def apply(arguments: argparse.Namespace) -> None:
    receipt = read_document(arguments.receipt)
    try:
        patch_bytes = arguments.patch.read_bytes()
    except OSError as error:
        fail(f"cannot read patch artifact: {error}")
    root = arguments.root.resolve()
    validate_receipt(receipt, arguments, root, patch_bytes)
    entries = validate_patch(patch_bytes)
    before_entries, current_tree = manifest(root, include_content=True)
    if current_tree != receipt["pre_tree"]:
        fail("temporary checkout is not the receipt pre-preparation tree")
    validate_policy_entries(root, entries)
    replayed_entries, replayed_tree = replay_trusted_policy(root)
    if replayed_tree != receipt["post_tree"]:
        fail("receipt post tree is not the trusted Ruff replay")
    if entries != expected_replay_entries(before_entries, replayed_entries):
        fail("receipt patch is not the trusted Ruff replay")
    run_git(root, "reset", "--hard", "HEAD")
    _, restored_tree = manifest(root, include_content=False)
    if restored_tree != receipt["pre_tree"]:
        fail("trusted Ruff replay did not restore the receipt pre-preparation tree")
    for entry in entries:
        target = checked_file(root, entry["path"])
        if entry["kind"] == "delete":
            if target.exists():
                target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        content = base64.b64decode(entry["content_base64"], validate=True)
        descriptor = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
            entry["mode"],
        )
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
        os.chmod(target, entry["mode"])
    _, applied_tree = manifest(root, include_content=False)
    if applied_tree != receipt["post_tree"]:
        fail("applied preparation patch does not reproduce receipt post tree")


def changed(arguments: argparse.Namespace) -> None:
    """Report Git-visible changes, including additions and deletions."""
    status = run_git(arguments.root.resolve(), "status", "--porcelain=v1", "--untracked-files=all")
    print("true" if status else "false")


def push(arguments: argparse.Namespace) -> None:
    """Push a prepared commit with an ephemeral GitHub App credential header."""
    root = arguments.root.resolve()
    if arguments.remote != "origin":
        fail("writeback remote must be origin")
    run_git(root, "check-ref-format", "--branch", arguments.head_ref)
    if len(arguments.expected_head) != 40 or any(
        character not in "0123456789abcdef" for character in arguments.expected_head
    ):
        fail("expected head is malformed")
    token = os.environ.get("GITHUB_APP_TOKEN")
    if not token:
        fail("GitHub App token is unavailable after validation")
    authorization = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
    environment = {
        **os.environ,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {authorization}",
    }
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "push",
            f"--force-with-lease=refs/heads/{arguments.head_ref}:{arguments.expected_head}",
            arguments.remote,
            f"HEAD:refs/heads/{arguments.head_ref}",
        ],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )
    if result.returncode:
        fail(f"leased writeback push failed: {result.stderr.strip()}")


def fetch(arguments: argparse.Namespace) -> None:
    """Fetch an exact head through a non-persistent read-token header."""
    root = arguments.root.resolve()
    if len(arguments.head_sha) != 40 or any(
        character not in "0123456789abcdef" for character in arguments.head_sha
    ):
        fail("expected head is malformed")
    token = os.environ.get("GITHUB_READ_TOKEN")
    if not token:
        fail("read token is unavailable")
    authorization = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
    environment = {
        **os.environ,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {authorization}",
    }
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "fetch",
            "--depth=1",
            "--no-tags",
            arguments.remote_url,
            arguments.head_sha,
        ],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )
    if result.returncode:
        fail(f"authenticated head fetch failed: {result.stderr.strip()}")
    run_git(root, "cat-file", "-e", f"{arguments.head_sha}^{{commit}}")


def artifact(arguments: argparse.Namespace) -> None:
    """Extract exactly the two bounded receipt members, in either ZIP order."""
    try:
        if arguments.archive.stat().st_size > MAX_ARTIFACT_BYTES:
            fail("receipt artifact exceeds bounded compressed size")
        with zipfile.ZipFile(arguments.archive) as archive_file:
            members = archive_file.infolist()
            expected_limits = {
                "preparation-receipt.json": MAX_RECEIPT_BYTES,
                "preparation-patch.json": MAX_PATCH_BYTES,
            }
            names = [member.filename for member in members]
            if len(members) != len(expected_limits) or set(names) != set(expected_limits):
                fail("receipt artifact must contain exactly the receipt and patch")
            if len(set(names)) != len(names):
                fail("receipt artifact contains duplicate members")
            extracted: dict[str, bytes] = {}
            for member in members:
                if member.is_dir() or member.file_size > expected_limits[member.filename]:
                    fail("receipt artifact member exceeds bounded extracted size")
                with archive_file.open(member) as stream:
                    content = stream.read(expected_limits[member.filename] + 1)
                if len(content) != member.file_size or len(content) > expected_limits[member.filename]:
                    fail("receipt artifact member exceeds bounded extracted size")
                extracted[member.filename] = content
    except (OSError, zipfile.BadZipFile) as error:
        raise PreparationError(f"invalid receipt artifact: {error}") from error
    arguments.output.mkdir(parents=True, exist_ok=True)
    for name, content in extracted.items():
        (arguments.output / name).write_bytes(content)


def parser() -> argparse.ArgumentParser:
    main_parser = argparse.ArgumentParser(description=__doc__)
    subparsers = main_parser.add_subparsers(dest="command", required=True)
    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("--repository", required=True)
    snapshot_parser.add_argument("--pull-request", type=positive_integer, required=True)
    snapshot_parser.add_argument("--head-sha", required=True)
    snapshot_parser.add_argument("--head-repository", required=True)
    snapshot_parser.add_argument("--head-ref", required=True)
    snapshot_parser.add_argument("--workflow-run-id", type=positive_integer, required=True)
    snapshot_parser.add_argument("--workflow-run-attempt", type=positive_integer, required=True)
    snapshot_parser.add_argument("--output", type=Path, required=True)
    snapshot_parser.add_argument("--root", type=Path, required=True)
    snapshot_parser.set_defaults(handler=snapshot)
    produce_parser = subparsers.add_parser("produce")
    produce_parser.add_argument("--snapshot", type=Path, required=True)
    produce_parser.add_argument("--receipt", type=Path, required=True)
    produce_parser.add_argument("--patch", type=Path, required=True)
    produce_parser.add_argument("--root", type=Path, required=True)
    produce_parser.set_defaults(handler=produce)
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--receipt", type=Path, required=True)
    apply_parser.add_argument("--patch", type=Path, required=True)
    apply_parser.add_argument("--repository", required=True)
    apply_parser.add_argument("--pull-request", type=positive_integer, required=True)
    apply_parser.add_argument("--expected-head", required=True)
    apply_parser.add_argument("--expected-policy", required=True)
    apply_parser.add_argument("--expected-head-ref", required=True)
    apply_parser.add_argument("--workflow-run-id", type=positive_integer, required=True)
    apply_parser.add_argument("--workflow-run-attempt", type=positive_integer, required=True)
    apply_parser.add_argument("--root", type=Path, required=True)
    apply_parser.set_defaults(handler=apply)
    changed_parser = subparsers.add_parser("changed")
    changed_parser.add_argument("--root", type=Path, required=True)
    changed_parser.set_defaults(handler=changed)
    push_parser = subparsers.add_parser("push")
    push_parser.add_argument("--root", type=Path, required=True)
    push_parser.add_argument("--remote", required=True)
    push_parser.add_argument("--head-ref", required=True)
    push_parser.add_argument("--expected-head", required=True)
    push_parser.set_defaults(handler=push)
    artifact_parser = subparsers.add_parser("artifact")
    artifact_parser.add_argument("--archive", type=Path, required=True)
    artifact_parser.add_argument("--output", type=Path, required=True)
    artifact_parser.set_defaults(handler=artifact)
    fetch_parser = subparsers.add_parser("fetch")
    fetch_parser.add_argument("--root", type=Path, required=True)
    fetch_parser.add_argument("--remote-url", required=True)
    fetch_parser.add_argument("--head-sha", required=True)
    fetch_parser.set_defaults(handler=fetch)
    return main_parser


def main() -> int:
    arguments = parser().parse_args()
    try:
        arguments.handler(arguments)
    except PreparationError as error:
        print(f"preparation: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
