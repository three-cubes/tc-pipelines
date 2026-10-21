"""Contract tests for the org-standard uv setup composite."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
# In agent-platform the reusable workflows live at the repository root, two levels
# above execution/pipelines/; in the public tc-pipelines export the root is this
# tree's own. Resolve whichever layout this file runs in.
PLATFORM_ROOT = REPO_ROOT if (REPO_ROOT / ".github" / "workflows").is_dir() else REPO_ROOT.parents[1]
# tc-pipelines governance/ lives in assurance/governance/ (ADR-0001 D4).
GOVERNANCE_ROOT = next(
    root
    for root in (PLATFORM_ROOT / "assurance" / "governance", PLATFORM_ROOT / "governance")
    if root.is_dir()
)
ACTION = REPO_ROOT / "actions" / "setup-uv-cached" / "action.yml"
REPOSITORY_RESOLVED_CALLERS = (
    REPO_ROOT / "actions" / "pre-commit-cached" / "action.yml",
    PLATFORM_ROOT / ".github" / "workflows" / "python-quality-gate.yml",
)
REPOSITORY_RESOLVED_DEFAULTS = {"uv-version": "", "python-version": ""}
PYTHON_INSTALL_SURFACES = (
    ACTION,
    REPO_ROOT / "actions" / "pre-commit-cached" / "action.yml",
    GOVERNANCE_ROOT / "skeletons" / "workflows" / "ci.yml.tmpl",
    GOVERNANCE_ROOT / "standards" / "python-dependency-locking.md",
    GOVERNANCE_ROOT / "standards" / "js-ts-tooling-baseline.md",
)


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _action_uv_default() -> str:
    return _yaml(ACTION)["inputs"]["uv-version"]["default"]


def _caller_default(path: Path, input_name: str) -> str:
    document = _yaml(path)
    if "inputs" in document:
        return document["inputs"][input_name]["default"]
    # PyYAML parses the GitHub Actions key `on` as True under YAML 1.1.
    triggers = document.get(True) or document["on"]
    return triggers["workflow_call"]["inputs"][input_name]["default"]


def _resolver_script() -> str:
    return _yaml(ACTION)["runs"]["steps"][0]["run"]


def _resolve(tmp_path: Path, *, uv_version: str = "", python_version: str = "") -> dict[str, str]:
    output_path = tmp_path / "github-output"
    completed = subprocess.run(
        ["bash", "-c", _resolver_script()],
        cwd=tmp_path,
        env={
            **os.environ,
            "GITHUB_OUTPUT": str(output_path),
            "INPUT_UV_VERSION": uv_version,
            "INPUT_PYTHON_VERSION": python_version,
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return dict(line.split("=", maxsplit=1) for line in output_path.read_text(encoding="utf-8").splitlines())


def _resolve_root_python(steps: list[dict], tmp_path: Path) -> str:
    step = next(step for step in steps if step.get("id") == "root_python")
    output_path = tmp_path / "github-output"
    completed = subprocess.run(
        ["bash", "-c", step["run"]],
        cwd=REPO_ROOT,
        env={**os.environ, "GITHUB_OUTPUT": str(output_path)},
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    values = dict(
        line.split("=", maxsplit=1) for line in output_path.read_text(encoding="utf-8").splitlines()
    )
    return values["python_version"]


def test_org_action_resolves_repository_toolchain_files_before_legacy_fallback() -> None:
    """One source file drives local bootstrap and every reusable gate lane."""

    action = ACTION.read_text(encoding="utf-8")
    assert _action_uv_default() == ""
    assert _yaml(ACTION)["inputs"]["python-version"]["default"] == ""
    assert 'resolve_version uv_version "$INPUT_UV_VERSION" .uv-version 0.12.5 valid_uv_version' in action
    assert (
        'resolve_version python_version "$INPUT_PYTHON_VERSION" .python-version 3.12 valid_python_request'
        in action
    )
    assert "version: ${{ steps.toolchain.outputs.uv_version }}" in action
    assert "python-version: ${{ steps.toolchain.outputs.python_version }}" in action
    assert "UV_PYTHON: ${{ steps.toolchain.outputs.python_version }}" in action


@pytest.mark.parametrize("path", REPOSITORY_RESOLVED_CALLERS)
@pytest.mark.parametrize("input_name, expected", REPOSITORY_RESOLVED_DEFAULTS.items())
def test_carrier_callers_defer_to_repository_toolchain_files(
    path: Path, input_name: str, expected: str
) -> None:
    """The carrier must not duplicate repository-owned Python and uv pins."""
    assert _caller_default(path, input_name) == expected


def test_toolchain_resolver_reads_version_files_without_trailing_newlines(
    tmp_path: Path,
) -> None:
    """A one-line version file is valid whether or not it ends with a newline."""
    (tmp_path / ".uv-version").write_text("0.12.5", encoding="utf-8")
    (tmp_path / ".python-version").write_text("3.13", encoding="utf-8")

    assert _resolve(tmp_path) == {"uv_version": "0.12.5", "python_version": "3.13"}


def test_toolchain_resolver_uses_legacy_values_for_empty_version_files(
    tmp_path: Path,
) -> None:
    """Empty files preserve the documented fallback for repositories migrating to pins."""
    (tmp_path / ".uv-version").touch()
    (tmp_path / ".python-version").touch()

    assert _resolve(tmp_path) == {"uv_version": "0.12.5", "python_version": "3.12"}


@pytest.mark.parametrize("selector", ["pypy@3.10", "cpython-3.12.3", ">=3.12,<3.13"])
def test_toolchain_resolver_preserves_supported_explicit_python_selectors(
    tmp_path: Path, selector: str
) -> None:
    """Matrix values use uv's Python request grammar, not only numeric versions."""
    assert _resolve(tmp_path, python_version=selector)["python_version"] == selector


def test_org_action_installs_only_the_uv_locked_project_environment() -> None:
    """The install action must not overlay a second resolver graph."""
    action = ACTION.read_text(encoding="utf-8")

    assert "uv sync ${{ inputs.sync-args }}" in action
    assert "uv pip install" not in action


def test_merge_queue_restores_but_does_not_race_to_save_the_shared_cache() -> None:
    """Parallel merge-group lanes must not contend to create one cache key."""

    action = _yaml(ACTION)
    install = next(step for step in action["runs"]["steps"] if "astral-sh/setup-uv@" in step.get("uses", ""))

    assert install["with"]["enable-cache"] is True
    assert install["with"]["save-cache"] == "${{ github.event_name != 'merge_group' }}"


def test_default_ci_sync_installs_the_explicit_dev_dependency_group() -> None:
    """The published default installs CI tools declared in the locked dev group."""
    action = _yaml(ACTION)
    assert action["inputs"]["sync-args"]["default"] == ("--locked --all-packages --group dev")
    workflow = _yaml(PLATFORM_ROOT / ".github" / "workflows" / "python-quality-gate.yml")
    triggers = workflow.get(True) or workflow["on"]
    assert triggers["workflow_call"]["inputs"]["sync-args"]["default"] == (
        "--locked --all-packages --group dev"
    )


@pytest.mark.parametrize(
    "path", PYTHON_INSTALL_SURFACES, ids=lambda path: str(path.relative_to(PLATFORM_ROOT))
)
def test_python_install_surfaces_have_no_ci_requirements_overlay(path: Path) -> None:
    """Every published install surface must derive Python tools from uv.lock."""
    text = path.read_text(encoding="utf-8")
    assert "ci-requirements" not in text
    assert "requirements-ci.txt" not in text
