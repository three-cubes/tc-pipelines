"""Real-Git contract tests for post-merge PR evidence promotion."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / ".github" / "actions" / "postmerge-pr-evidence" / "postmerge_pr_evidence.py"
SPEC = importlib.util.spec_from_file_location("postmerge_pr_evidence", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence)


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        input=stdin,
    ).stdout.strip()


def _commit(repo: Path, name: str, content: str) -> str:
    (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


def _shallow_clone(source: Path, destination: Path) -> Path:
    subprocess.run(
        ["git", "clone", "--depth", "1", f"file://{source}", str(destination)],
        check=True,
        capture_output=True,
        text=True,
    )
    return destination


@pytest.fixture
def merged_tree(tmp_path: Path) -> dict[str, str | Path]:
    repo = tmp_path / "repository"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    _git(repo, "config", "user.name", "contract")
    _git(repo, "config", "user.email", "contract@example.invalid")
    base = _commit(repo, "base.txt", "base\n")
    _git(repo, "switch", "-c", "feature")
    head = _commit(repo, "feature.txt", "feature\n")
    tree = _git(repo, "merge-tree", "--write-tree", base, head)
    tested_merge = _git(repo, "commit-tree", tree, "-p", base, "-p", head, stdin="tested\n")
    _git(repo, "switch", "main")
    landed_merge = _git(repo, "commit-tree", tree, "-p", base, "-p", head, stdin="landed\n")
    _git(repo, "reset", "--hard", landed_merge)
    return {
        "repo": repo,
        "base": base,
        "head": head,
        "tree": tree,
        "tested": tested_merge,
        "landed": landed_merge,
    }


def _evidence(case: dict[str, str | Path]) -> dict[str, object]:
    return evidence.capture_document(
        repo_root=case["repo"],
        repository="three-cubes/example",
        pull_request_number=116,
        base_sha=case["base"],
        head_sha=case["head"],
        workflow_run_id=42,
        workflow_run_attempt=1,
        tested_merge_sha=case["tested"],
    )


def test_promotes_an_identical_real_merge_tree(
    merged_tree: dict[str, str | Path],
) -> None:
    assert (
        evidence.verify_document(
            repo_root=merged_tree["repo"],
            before_sha=merged_tree["base"],
            merge_sha=merged_tree["landed"],
            expected_repository="three-cubes/example",
            expected_pull_request=116,
            expected_head_sha=merged_tree["head"],
            expected_run_id=42,
            expected_run_attempt=1,
            document=_evidence(merged_tree),
        )["verified"]
        is True
    )


def test_capture_reads_merge_headers_at_a_shallow_boundary(
    merged_tree: dict[str, str | Path], tmp_path: Path
) -> None:
    shallow = _shallow_clone(merged_tree["repo"], tmp_path / "shallow-capture")
    assert _git(shallow, "rev-parse", "--is-shallow-repository") == "true"
    assert _git(shallow, "rev-list", "--parents", "-n", "1", "HEAD").split() == [merged_tree["landed"]]

    document = evidence.capture_document(
        repo_root=shallow,
        repository="three-cubes/example",
        pull_request_number=116,
        base_sha=merged_tree["base"],
        head_sha=merged_tree["head"],
        workflow_run_id=42,
        workflow_run_attempt=1,
        tested_merge_sha=merged_tree["landed"],
    )

    assert document["tested_tree_sha"] == merged_tree["tree"]


def test_verification_does_not_require_the_unreachable_synthetic_merge_object(
    merged_tree: dict[str, str | Path], tmp_path: Path
) -> None:
    document = _evidence(merged_tree)
    shallow = _shallow_clone(merged_tree["repo"], tmp_path / "shallow-verify")
    absent = subprocess.run(
        ["git", "cat-file", "-e", f"{merged_tree['tested']}^{{commit}}"],
        cwd=shallow,
        check=False,
        capture_output=True,
        text=True,
    )
    assert absent.returncode != 0

    result = evidence.verify_document(
        repo_root=shallow,
        before_sha=merged_tree["base"],
        merge_sha=merged_tree["landed"],
        expected_repository="three-cubes/example",
        expected_pull_request=116,
        expected_head_sha=merged_tree["head"],
        expected_run_id=42,
        expected_run_attempt=1,
        document=document,
    )

    assert result["verified"] is True


def test_evaluated_tree_guard_rejects_tracked_and_untracked_normalizer_changes(
    tmp_path: Path,
) -> None:
    guard = ROOT / "actions" / "python-gate-body" / "assert-clean-evaluated-tree.sh"
    repo = tmp_path / "normalized"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    _git(repo, "config", "user.name", "contract")
    _git(repo, "config", "user.email", "contract@example.invalid")
    _commit(repo, "tracked.txt", "before\n")

    clean = subprocess.run(["bash", str(guard)], cwd=repo, capture_output=True, text=True, check=False)
    assert clean.returncode == 0, clean.stderr

    (repo / "tracked.txt").write_text("after\n", encoding="utf-8")
    tracked = subprocess.run(["bash", str(guard)], cwd=repo, capture_output=True, text=True, check=False)
    assert tracked.returncode != 0
    assert "tracked.txt" in tracked.stderr
    assert "commit" in tracked.stderr
    assert "evaluation withheld" in tracked.stderr

    _git(repo, "reset", "--hard", "HEAD")
    (repo / "generated.txt").write_text("generated\n", encoding="utf-8")
    untracked = subprocess.run(["bash", str(guard)], cwd=repo, capture_output=True, text=True, check=False)
    assert untracked.returncode != 0
    assert "generated.txt" in untracked.stderr


@pytest.mark.parametrize("mutation", ["before", "head", "run", "tree"])
def test_stale_or_changed_evidence_fails_closed(merged_tree: dict[str, str | Path], mutation: str) -> None:
    document = _evidence(merged_tree)
    if mutation == "before":
        before = "f" * 40
        head = merged_tree["head"]
        run_id = 42
    elif mutation == "head":
        before = merged_tree["base"]
        head = "f" * 40
        run_id = 42
    elif mutation == "run":
        before = merged_tree["base"]
        head = merged_tree["head"]
        run_id = 43
    else:
        before = merged_tree["base"]
        head = merged_tree["head"]
        run_id = 42
        document["tested_tree_sha"] = "f" * 40

    with pytest.raises(ValueError):
        evidence.verify_document(
            repo_root=merged_tree["repo"],
            before_sha=before,
            merge_sha=merged_tree["landed"],
            expected_repository="three-cubes/example",
            expected_pull_request=116,
            expected_head_sha=head,
            expected_run_id=run_id,
            expected_run_attempt=1,
            document=document,
        )


def test_direct_push_and_non_merge_commit_fail_closed(
    merged_tree: dict[str, str | Path],
) -> None:
    _git(merged_tree["repo"], "reset", "--hard", merged_tree["head"])
    with pytest.raises(ValueError, match="two-parent merge"):
        evidence.verify_document(
            repo_root=merged_tree["repo"],
            before_sha=merged_tree["base"],
            merge_sha=merged_tree["head"],
            expected_repository="three-cubes/example",
            expected_pull_request=116,
            expected_head_sha=merged_tree["head"],
            expected_run_id=42,
            expected_run_attempt=1,
            document=_evidence(merged_tree),
        )


def test_duplicate_json_keys_fail_closed(tmp_path: Path) -> None:
    payload = tmp_path / "evidence.json"
    payload.write_text('{"schema":"one","schema":"two"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate JSON field"):
        evidence.load_json(payload)


def test_capture_and_verify_cli_round_trip_emits_a_verified_output(
    merged_tree: dict[str, str | Path], tmp_path: Path
) -> None:
    document = tmp_path / "evidence.json"
    output = tmp_path / "github-output"
    assert (
        evidence.main(
            [
                "capture",
                "--repo-root",
                str(merged_tree["repo"]),
                "--repository",
                "three-cubes/example",
                "--pull-request-number",
                "116",
                "--base-sha",
                merged_tree["base"],
                "--head-sha",
                merged_tree["head"],
                "--workflow-run-id",
                "42",
                "--workflow-run-attempt",
                "1",
                "--tested-merge-sha",
                merged_tree["tested"],
                "--output",
                str(document),
            ]
        )
        == 0
    )
    assert (
        evidence.main(
            [
                "verify",
                "--repo-root",
                str(merged_tree["repo"]),
                "--repository",
                "three-cubes/example",
                "--before-sha",
                merged_tree["base"],
                "--merge-sha",
                merged_tree["landed"],
                "--pull-request-number",
                "116",
                "--head-sha",
                merged_tree["head"],
                "--workflow-run-id",
                "42",
                "--workflow-run-attempt",
                "1",
                "--document",
                str(document),
                "--github-output",
                str(output),
            ]
        )
        == 0
    )
    assert json.loads(document.read_text(encoding="utf-8"))["tested_tree_sha"] == merged_tree["tree"]
    assert output.read_text(encoding="utf-8").splitlines() == [
        "verified=true",
        "pull_request_number=116",
    ]
