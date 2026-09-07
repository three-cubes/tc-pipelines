"""Capture and verify the PR merge tree promoted by a protected main push."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


SCHEMA = "postmerge-pr-quality-evidence/v1"
SHA = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON evidence: {path.name}") from error


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA.fullmatch(value) is None:
        raise ValueError(f"{label} must be an exact lowercase Git SHA")
    return value


def _positive(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _git(repo_root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=repo_root, check=True, capture_output=True, text=True
        ).stdout.strip()
    except subprocess.CalledProcessError as error:
        raise ValueError("Git history does not contain the required merge evidence") from error


def _merge_identity(repo_root: Path, merge_sha: str) -> tuple[tuple[str, str], str]:
    fields = _git(repo_root, "rev-list", "--parents", "-n", "1", merge_sha).split()
    if len(fields) != 3 or fields[0] != merge_sha:
        raise ValueError("evidence requires one two-parent merge commit")
    return (fields[1], fields[2]), _git(repo_root, "rev-parse", f"{merge_sha}^{{tree}}")


def capture_document(
    *,
    repo_root: Path,
    repository: str,
    pull_request_number: int,
    base_sha: str,
    head_sha: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
    tested_merge_sha: str,
) -> dict[str, object]:
    """Build an immutable statement of the PR merge tree tested by CI."""
    if REPOSITORY.fullmatch(repository) is None:
        raise ValueError("repository must be an owner/name slug")
    base = _sha(base_sha, "PR base SHA")
    head = _sha(head_sha, "PR head SHA")
    tested_merge = _sha(tested_merge_sha, "tested merge SHA")
    parents, tree = _merge_identity(repo_root.resolve(), tested_merge)
    if parents != (base, head):
        raise ValueError("tested merge parents do not match PR base and head")
    return {
        "schema": SCHEMA,
        "repository": repository,
        "pull_request_number": _positive(pull_request_number, "pull request number"),
        "base_sha": base,
        "head_sha": head,
        "tested_merge_sha": tested_merge,
        "tested_tree_sha": tree,
        "workflow_run_id": _positive(workflow_run_id, "workflow run ID"),
        "workflow_run_attempt": _positive(workflow_run_attempt, "workflow run attempt"),
    }


def verify_document(
    *,
    repo_root: Path,
    before_sha: str,
    merge_sha: str,
    expected_repository: str,
    expected_pull_request: int,
    expected_head_sha: str,
    expected_run_id: int,
    expected_run_attempt: int,
    document: object,
) -> dict[str, object]:
    """Fail closed unless one trusted PR evidence record proves this exact tree."""
    root = repo_root.resolve()
    before = _sha(before_sha, "push before SHA")
    merge = _sha(merge_sha, "pushed merge SHA")
    head = _sha(expected_head_sha, "PR head SHA")
    if REPOSITORY.fullmatch(expected_repository) is None:
        raise ValueError("repository must be an owner/name slug")
    if _git(root, "rev-parse", "HEAD") != merge:
        raise ValueError("checked-out HEAD does not match pushed merge SHA")
    parents, tree = _merge_identity(root, merge)
    if parents != (before, head):
        raise ValueError("merge parents do not match the associated PR")
    if not isinstance(document, Mapping):
        raise ValueError("PR evidence must be an object")
    expected = {
        "schema": SCHEMA,
        "repository": expected_repository,
        "pull_request_number": _positive(expected_pull_request, "pull request number"),
        "base_sha": before,
        "head_sha": head,
        "workflow_run_id": _positive(expected_run_id, "workflow run ID"),
        "workflow_run_attempt": _positive(expected_run_attempt, "workflow run attempt"),
    }
    if set(document) != {*expected, "tested_merge_sha", "tested_tree_sha"}:
        raise ValueError("PR evidence has an unsupported shape")
    if any(document.get(key) != value for key, value in expected.items()):
        raise ValueError("PR evidence identity or workflow attempt is stale")
    tested_merge = _sha(document.get("tested_merge_sha"), "tested merge SHA")
    tested_tree = _sha(document.get("tested_tree_sha"), "tested tree SHA")
    tested_parents, actual_tested_tree = _merge_identity(root, tested_merge)
    if tested_parents != (before, head) or actual_tested_tree != tested_tree or tested_tree != tree:
        raise ValueError("landed merge tree was not the tree tested by the PR gate")
    return {"verified": True, "pull_request_number": expected_pull_request, "tested_tree_sha": tree}


def _capture(args: argparse.Namespace) -> int:
    document = capture_document(
        repo_root=args.repo_root, repository=args.repository, pull_request_number=args.pull_request_number,
        base_sha=args.base_sha, head_sha=args.head_sha, workflow_run_id=args.workflow_run_id,
        workflow_run_attempt=args.workflow_run_attempt, tested_merge_sha=args.tested_merge_sha or _git(args.repo_root, "rev-parse", "HEAD"),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
    return 0


def _verify(args: argparse.Namespace) -> int:
    result = verify_document(
        repo_root=args.repo_root, before_sha=args.before_sha, merge_sha=args.merge_sha,
        expected_repository=args.repository, expected_pull_request=args.pull_request_number,
        expected_head_sha=args.head_sha, expected_run_id=args.workflow_run_id,
        expected_run_attempt=args.workflow_run_attempt, document=load_json(args.document),
    )
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as stream:
            stream.write("verified=true\n")
            stream.write(f"pull_request_number={result['pull_request_number']}\n")
    print(f"PASS postmerge-pr-evidence pr={result['pull_request_number']} tree={result['tested_tree_sha']}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    command = parser.add_subparsers(dest="command", required=True)
    capture = command.add_parser("capture")
    for flag, kwargs in (("--repository", {"required": True}), ("--base-sha", {"required": True}), ("--head-sha", {"required": True}), ("--tested-merge-sha", {})):
        capture.add_argument(flag, **kwargs)
    capture.add_argument("--repo-root", type=Path, default=Path.cwd())
    capture.add_argument("--pull-request-number", type=int, required=True)
    capture.add_argument("--workflow-run-id", type=int, required=True)
    capture.add_argument("--workflow-run-attempt", type=int, required=True)
    capture.add_argument("--output", type=Path, required=True)
    capture.set_defaults(handler=_capture)
    verify = command.add_parser("verify")
    for flag in ("--repository", "--before-sha", "--merge-sha", "--head-sha"):
        verify.add_argument(flag, required=True)
    verify.add_argument("--repo-root", type=Path, default=Path.cwd())
    verify.add_argument("--pull-request-number", type=int, required=True)
    verify.add_argument("--workflow-run-id", type=int, required=True)
    verify.add_argument("--workflow-run-attempt", type=int, required=True)
    verify.add_argument("--document", type=Path, required=True)
    verify.add_argument("--github-output", type=Path)
    verify.set_defaults(handler=_verify)
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(arguments)
    try:
        return args.handler(args)
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
