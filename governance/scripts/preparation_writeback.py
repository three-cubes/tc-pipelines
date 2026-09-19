#!/usr/bin/env python3
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
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any


RECEIPT_SCHEMA = "tc.sdlc/preparation-receipt/v1"
PATCH_SCHEMA = "tc.sdlc/preparation-patch/v1"
MAX_PATCH_BYTES = 1024 * 1024
MAX_RECEIPT_AGE = timedelta(minutes=30)
ALLOWED_MODES = {0o644, 0o755}


class PreparationError(ValueError):
    """Evidence was not safe to apply."""


def fail(message: str) -> None:
    raise PreparationError(message)


def run_git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=root, text=True, capture_output=True, check=False
    )
    if result.returncode:
        fail(f"git {' '.join(arguments)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


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
    tracked = run_git(root, "ls-files", "-z").encode("utf-8").split(b"\0")
    untracked = run_git(root, "ls-files", "--others", "--exclude-standard", "-z").encode("utf-8").split(b"\0")
    paths = {piece.decode("utf-8") for piece in tracked + untracked if piece}
    return sorted(paths)


def manifest(root: Path, *, include_content: bool) -> tuple[list[dict[str, Any]], str]:
    entries: list[dict[str, Any]] = []
    for relative in visible_paths(root):
        path = checked_file(root, relative)
        if not path.exists():
            fail(f"tracked path disappeared: {relative!r}")
        mode = stat.S_IMODE(os.lstat(path).st_mode)
        if mode & ~0o777:
            fail(f"unsafe file mode: {relative!r}")
        content = path.read_bytes()
        entry: dict[str, Any] = {"path": relative, "mode": mode, "digest": sha256(content)}
        if include_content:
            entry["content_base64"] = base64.b64encode(content).decode("ascii")
        entries.append(entry)
    state = sha256(canonical_json([{key: value for key, value in entry.items() if key != "content_base64"} for entry in entries]))
    return entries, state


def read_document(path: Path, *, limit: int = MAX_PATCH_BYTES * 2) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        fail(f"cannot read evidence: {error}")
    if len(raw) > limit:
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
    entries, pre_tree = manifest(root, include_content=True)
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
    snapshot_document = read_document(arguments.snapshot, limit=MAX_PATCH_BYTES * 16)
    snapshot_fields = {
        "schema", "repository", "pull_request", "head_sha", "head_tree", "head_repository",
        "head_ref", "workflow_run_id", "workflow_run_attempt", "pre_tree", "entries",
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
        if not isinstance(entry, dict) or set(entry) != {"path", "mode", "digest", "content_base64"}:
            fail("invalid snapshot entry")
        validate_relative_path(entry["path"])
        before[entry["path"]] = entry
    current_entries, post_tree = manifest(root, include_content=True)
    after = {entry["path"]: entry for entry in current_entries}
    patch_entries: list[dict[str, Any]] = []
    for path in sorted(set(before) | set(after)):
        old, new = before.get(path), after.get(path)
        if new is None:
            patch_entries.append({"path": path, "kind": "delete"})
        elif old is None or old["digest"] != new["digest"] or old["mode"] != new["mode"]:
            patch_entries.append({
                "path": path,
                "kind": "file",
                "mode": new["mode"],
                "content_base64": new["content_base64"],
            })
    patch_document = {"schema": PATCH_SCHEMA, "entries": patch_entries}
    patch_bytes = canonical_json(patch_document)
    if len(patch_bytes) > MAX_PATCH_BYTES:
        fail("preparation patch exceeds bounded size")
    arguments.patch.parent.mkdir(parents=True, exist_ok=True)
    arguments.patch.write_bytes(patch_bytes)
    receipt = {
        "schema": RECEIPT_SCHEMA,
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


def validate_receipt(document: dict[str, Any], arguments: argparse.Namespace, root: Path, patch_bytes: bytes) -> None:
    fields = {
        "schema", "repository", "pull_request", "head_sha", "head_tree", "head_repository",
        "head_ref", "workflow_run_id", "workflow_run_attempt", "pre_tree", "post_tree",
        "patch_digest", "patch_bytes", "issued_at",
    }
    required(document, fields, "receipt")
    if document["schema"] != RECEIPT_SCHEMA:
        fail("unsupported receipt schema")
    if document["repository"] != arguments.repository:
        fail("receipt repository does not match consumer repository")
    if document["pull_request"] != arguments.pull_request:
        fail("receipt pull request does not match workflow-run pull request")
    if document["workflow_run_id"] != arguments.workflow_run_id or document[
        "workflow_run_attempt"
    ] != arguments.workflow_run_attempt:
        fail("receipt workflow run identity does not match artifact source")
    if document["head_repository"] != arguments.repository:
        fail("fork preparation evidence is not eligible for writeback")
    if document["head_sha"] != arguments.expected_head:
        fail("receipt head does not match expected pull-request head")
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
        issued_at = datetime.fromisoformat(document["issued_at"].replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise PreparationError("receipt issued_at is invalid") from error
    if issued_at.tzinfo is None:
        fail("receipt issued_at must include a timezone")
    now = datetime.now(UTC)
    if issued_at.astimezone(UTC) < now - MAX_RECEIPT_AGE or issued_at.astimezone(UTC) > now + timedelta(minutes=1):
        fail("receipt is stale or from the future")
    for field in ("head_sha", "head_tree"):
        if not isinstance(document[field], str) or len(document[field]) != 40 or any(
            character not in "0123456789abcdef" for character in document[field]
        ):
            fail(f"receipt {field} is malformed")
    for field in ("pre_tree", "post_tree", "patch_digest"):
        if not isinstance(document[field], str) or not document[field].startswith("sha256:"):
            fail(f"receipt {field} is malformed")
    if not isinstance(document["pull_request"], int) or document["pull_request"] < 1:
        fail("receipt pull request is invalid")
    if not isinstance(document["workflow_run_id"], int) or not isinstance(document["workflow_run_attempt"], int):
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


def apply(arguments: argparse.Namespace) -> None:
    receipt = read_document(arguments.receipt)
    try:
        patch_bytes = arguments.patch.read_bytes()
    except OSError as error:
        fail(f"cannot read patch artifact: {error}")
    root = arguments.root.resolve()
    validate_receipt(receipt, arguments, root, patch_bytes)
    entries = validate_patch(patch_bytes)
    _, current_tree = manifest(root, include_content=False)
    if current_tree != receipt["pre_tree"]:
        fail("temporary checkout is not the receipt pre-preparation tree")
    for entry in entries:
        target = checked_file(root, entry["path"])
        if entry["kind"] == "delete":
            if target.exists():
                target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        content = base64.b64decode(entry["content_base64"], validate=True)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), entry["mode"])
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
        os.chmod(target, entry["mode"])
    _, applied_tree = manifest(root, include_content=False)
    if applied_tree != receipt["post_tree"]:
        fail("applied preparation patch does not reproduce receipt post tree")


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
    apply_parser.add_argument("--workflow-run-id", type=positive_integer, required=True)
    apply_parser.add_argument("--workflow-run-attempt", type=positive_integer, required=True)
    apply_parser.add_argument("--root", type=Path, required=True)
    apply_parser.set_defaults(handler=apply)
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
