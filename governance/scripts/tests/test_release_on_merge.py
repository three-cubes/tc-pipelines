"""Behavioural tests for resolving a prepared release from a merge commit."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release-on-merge.yml"
RESOLVE_STEP = "Resolve prepared release from merge commit"


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*args], capture_output=True, text=True, cwd=cwd, check=False
    )


def _git(cwd: Path, *args: str) -> str:
    result = _run(cwd, "git", *args)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _resolve_step() -> str:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")) or {}
    for job in (document.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if isinstance(step, dict) and step.get("name") == RESOLVE_STEP:
                return str(step.get("run") or "")
    return ""


def _repository(tmp_path: Path, *, receipt_changes: bool) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-q", "-b", "main")
    _git(repository, "config", "user.name", "release-test")
    _git(repository, "config", "user.email", "release-test@example.invalid")
    (repository / ".release-prepared.json").write_text(
        json.dumps({"version": "v1.2.3"}) + "\n", encoding="utf-8"
    )
    (repository / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "base")
    _git(repository, "switch", "-qc", "feature")
    if receipt_changes:
        (repository / ".release-prepared.json").write_text(
            json.dumps({"version": "v1.2.4"}) + "\n", encoding="utf-8"
        )
    else:
        (repository / "tracked.txt").write_text("feature\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "feature")
    _git(repository, "switch", "-q", "main")
    _git(repository, "merge", "--no-ff", "feature", "-qm", "merge feature")
    return repository, _git(repository, "rev-parse", "HEAD")


def _resolve(
    repository: Path, merge_sha: str, output_file: Path
) -> subprocess.CompletedProcess[str]:
    step = _resolve_step()
    assert step, f"release-on-merge.yml has no `{RESOLVE_STEP}` step"
    prelude = (
        'export MERGE_SHA="$1" PREPARATION_FILE="$2" GITHUB_OUTPUT="$3"\n'
    )
    return _run(
        repository,
        "bash",
        "-c",
        prelude + step,
        "guard",
        merge_sha,
        ".release-prepared.json",
        str(output_file),
    )


def test_resolves_version_only_when_receipt_changed_in_exact_merge(
    tmp_path: Path,
) -> None:
    repository, merge_sha = _repository(tmp_path, receipt_changes=True)
    output_file = tmp_path / "github-output"

    resolved = _resolve(repository, merge_sha, output_file)

    assert resolved.returncode == 0, resolved.stderr
    output = output_file.read_text(encoding="utf-8")
    assert "version=v1.2.4" in output
    assert f"merge-sha={merge_sha}" in output


def test_rejects_merge_that_did_not_change_the_receipt(tmp_path: Path) -> None:
    repository, merge_sha = _repository(tmp_path, receipt_changes=False)

    rejected = _resolve(repository, merge_sha, tmp_path / "github-output")

    assert rejected.returncode != 0
    assert "did not change .release-prepared.json" in rejected.stderr


def test_rejects_a_non_merge_commit(tmp_path: Path) -> None:
    repository, _ = _repository(tmp_path, receipt_changes=True)
    non_merge = _git(repository, "rev-parse", "HEAD^2")

    rejected = _resolve(repository, non_merge, tmp_path / "github-output")

    assert rejected.returncode != 0
    assert "merge commit" in rejected.stderr
