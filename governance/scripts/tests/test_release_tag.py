"""Behavioural tests for exact-SHA idempotent release tags."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE = REPO_ROOT / ".github" / "workflows" / "release.yml"
TAG_STEP = "Ensure exact release tag"


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([*args], capture_output=True, text=True, cwd=cwd, check=False)


def _git(cwd: Path, *args: str) -> str:
    result = _run(cwd, "git", *args)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "release-test")
    _git(repository, "config", "user.email", "release-test@example.invalid")
    tracked = repository / "tracked.txt"
    tracked.write_text("first\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "-qm", "first")
    first = _git(repository, "rev-parse", "HEAD")
    tracked.write_text("second\n", encoding="utf-8")
    _git(repository, "commit", "-qam", "second")
    second = _git(repository, "rev-parse", "HEAD")
    return repository, first, second


def _tag_step() -> str:
    document = yaml.safe_load(RELEASE.read_text(encoding="utf-8")) or {}
    for job in (document.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if isinstance(step, dict) and step.get("name") == TAG_STEP:
                return str(step.get("run") or "")
    return ""


def _tag(repository: Path, target: str, output_file: Path) -> subprocess.CompletedProcess[str]:
    _git(repository, "checkout", "--detach", "-q", target)
    step = _tag_step()
    assert step, f"release.yml has no `{TAG_STEP}` step"
    prelude = 'export VERSION="$1" RELEASE_TARGET_SHA="$2" TAG_MESSAGE="$3" GITHUB_OUTPUT="$4"\n'
    return _run(
        repository,
        "bash",
        "-c",
        prelude + step,
        "guard",
        "v1.2.4",
        target,
        "release v1.2.4",
        str(output_file),
    )


def test_creates_annotated_tag_at_exact_target_and_replay_is_a_noop(
    tmp_path: Path,
) -> None:
    repository, first, _ = _repository(tmp_path)
    output_file = tmp_path / "github-output"

    created = _tag(repository, first, output_file)

    assert created.returncode == 0, created.stderr
    assert "created=true" in output_file.read_text(encoding="utf-8")
    assert _git(repository, "cat-file", "-t", "refs/tags/v1.2.4") == "tag"
    assert _git(repository, "rev-list", "-n", "1", "v1.2.4") == first

    output_file.write_text("", encoding="utf-8")
    replayed = _tag(repository, first, output_file)
    assert replayed.returncode == 0, replayed.stderr
    assert "created=false" in output_file.read_text(encoding="utf-8")
    assert _git(repository, "rev-list", "-n", "1", "v1.2.4") == first


def test_rejects_existing_tag_at_a_different_commit(tmp_path: Path) -> None:
    repository, first, second = _repository(tmp_path)
    _git(repository, "tag", "-a", "v1.2.4", second, "-m", "wrong target")

    rejected = _tag(repository, first, tmp_path / "github-output")

    assert rejected.returncode != 0
    assert first in rejected.stderr
    assert second in rejected.stderr
    assert _git(repository, "rev-list", "-n", "1", "v1.2.4") == second


def test_rejects_lightweight_tag_even_when_target_matches(tmp_path: Path) -> None:
    repository, first, _ = _repository(tmp_path)
    _git(repository, "tag", "v1.2.4", first)

    rejected = _tag(repository, first, tmp_path / "github-output")

    assert rejected.returncode != 0
    assert "annotated" in rejected.stderr
