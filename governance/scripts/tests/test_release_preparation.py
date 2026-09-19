"""Behavioural tests for mechanical release preparation."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
PREPARE_RELEASE = (
    REPO_ROOT / "actions" / "prepare-release-metadata" / "prepare_release.py"
)
PREPARE_ACTION = REPO_ROOT / "actions" / "prepare-release-metadata" / "action.yml"


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([*args], capture_output=True, text=True, cwd=cwd, check=False)


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        """[project]
name = "release-fixture"
version = "1.2.3"
requires-python = ">=3.12"
dependencies = []

[tool.uv]
package = false
""",
        encoding="utf-8",
    )
    (project / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- Release behaviour.\n\n"
        "## [1.2.3] — 2099-01-01\n\n- Previous.\n",
        encoding="utf-8",
    )
    locked = _run(project, "uv", "lock")
    assert locked.returncode == 0, locked.stderr
    return project


def test_semantic_bump_updates_project_lock_changelog_and_receipt(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)

    prepared = _run(
        project,
        "python3",
        str(PREPARE_RELEASE),
        "--bump",
        "patch",
        "--tag-prefix",
        "v",
        "--version-file",
        "",
        "--date",
        "2099-09-18",
    )

    assert prepared.returncode == 0, prepared.stderr
    assert "version=v1.2.4" in prepared.stdout
    assert 'version = "1.2.4"' in (project / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert 'version = "1.2.4"' in (project / "uv.lock").read_text(encoding="utf-8")
    changelog = (project / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Unreleased]\n\n## [1.2.4] — 2099-09-18" in changelog
    receipt = json.loads(
        (project / ".release-prepared.json").read_text(encoding="utf-8")
    )
    assert receipt["version"] == "v1.2.4"
    assert receipt["version_file"] == ""


def test_action_empty_version_file_skips_plain_file_binding(tmp_path: Path) -> None:
    project = _project(tmp_path)
    action = yaml.safe_load(PREPARE_ACTION.read_text(encoding="utf-8"))
    step = action["runs"]["steps"][-1]["run"]
    output_file = tmp_path / "github-output"
    environment = {
        **os.environ,
        "RELEASE_VERSION": "v1.2.4",
        "RELEASE_BUMP": "",
        "TAG_PREFIX": "v",
        "RELEASE_DATE": "2099-09-18",
        "CHANGELOG_FILE": "CHANGELOG.md",
        "VERSION_FILE": "",
        "PREPARATION_FILE": ".release-prepared.json",
        "GITHUB_ACTION_PATH": str(PREPARE_ACTION.parent),
        "GITHUB_OUTPUT": str(output_file),
    }

    prepared = subprocess.run(
        ["bash", "-c", step],
        capture_output=True,
        text=True,
        cwd=project,
        env=environment,
        check=False,
    )

    assert prepared.returncode == 0, prepared.stderr
    assert not (project / "VERSION").exists()
    receipt = json.loads(
        (project / ".release-prepared.json").read_text(encoding="utf-8")
    )
    assert receipt["version_file"] == ""


def test_explicit_tag_updates_pyproject_when_plain_version_file_is_empty(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)

    prepared = _run(
        project,
        "python3",
        str(PREPARE_RELEASE),
        "--version",
        "v1.4.0",
        "--version-file",
        "",
        "--date",
        "2099-09-18",
    )

    assert prepared.returncode == 0, prepared.stderr
    assert 'version = "1.4.0"' in (project / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert 'version = "1.4.0"' in (project / "uv.lock").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (("--version", "v1.2.4", "--bump", "patch"), "not allowed"),
        (("--bump", "dev"), "invalid choice"),
    ],
)
def test_preparation_rejects_ambiguous_or_unsupported_bumps(
    tmp_path: Path, arguments: tuple[str, ...], message: str
) -> None:
    project = _project(tmp_path)

    rejected = _run(
        project,
        "python3",
        str(PREPARE_RELEASE),
        *arguments,
        "--version-file",
        "",
    )

    assert rejected.returncode != 0
    assert message in rejected.stderr
