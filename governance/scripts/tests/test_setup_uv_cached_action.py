"""Contract tests for the org-standard uv setup composite."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTION = REPO_ROOT / "actions" / "setup-uv-cached" / "action.yml"
LEGACY_CARRIER_CALLERS = (
    REPO_ROOT / "actions" / "pre-commit-cached" / "action.yml",
    REPO_ROOT / ".github" / "workflows" / "python-quality-gate.yml",
)
LEGACY_DEFAULTS = {"uv-version": "0.12.5", "python-version": "3.12"}
PYTHON_INSTALL_SURFACES = (
    ACTION,
    REPO_ROOT / "actions" / "pre-commit-cached" / "action.yml",
    REPO_ROOT / ".github" / "workflows" / "test-shard-routing.yml",
    REPO_ROOT / ".github" / "workflows" / "example-pytest-durations-refresh.yml",
    REPO_ROOT / "governance" / "skeletons" / "workflows" / "ci.yml.tmpl",
    REPO_ROOT / "governance" / "standards" / "python-dependency-locking.md",
    REPO_ROOT / "governance" / "standards" / "js-ts-tooling-baseline.md",
    REPO_ROOT / "README.md",
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


def _resolve(
    tmp_path: Path, *, uv_version: str = "", python_version: str = ""
) -> dict[str, str]:
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
    return dict(
        line.split("=", maxsplit=1)
        for line in output_path.read_text(encoding="utf-8").splitlines()
    )


def test_org_action_resolves_repository_toolchain_files_before_legacy_fallback() -> (
    None
):
    """One source file drives local bootstrap and every reusable gate lane."""

    action = ACTION.read_text(encoding="utf-8")
    assert _action_uv_default() == ""
    assert _yaml(ACTION)["inputs"]["python-version"]["default"] == ""
    assert (
        'resolve_version uv_version "$INPUT_UV_VERSION" .uv-version 0.12.5 valid_uv_version'
        in action
    )
    assert (
        'resolve_version python_version "$INPUT_PYTHON_VERSION" .python-version 3.12 valid_python_request'
        in action
    )
    assert "version: ${{ steps.toolchain.outputs.uv_version }}" in action
    assert "python-version: ${{ steps.toolchain.outputs.python_version }}" in action
    assert "UV_PYTHON: ${{ steps.toolchain.outputs.python_version }}" in action


@pytest.mark.parametrize("path", LEGACY_CARRIER_CALLERS)
@pytest.mark.parametrize("input_name, expected", LEGACY_DEFAULTS.items())
def test_carrier_callers_keep_legacy_defaults_until_their_self_pins_move(
    path: Path, input_name: str, expected: str
) -> None:
    """The carrier must feed its pinned pre-resolver composite valid inputs."""
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


def test_default_ci_sync_installs_the_explicit_dev_dependency_group() -> None:
    """The published default installs CI tools declared in the locked dev group."""
    action = _yaml(ACTION)
    assert action["inputs"]["sync-args"]["default"] == (
        "--locked --all-packages --group dev"
    )
    workflow = _yaml(REPO_ROOT / ".github" / "workflows" / "python-quality-gate.yml")
    triggers = workflow.get(True) or workflow["on"]
    assert triggers["workflow_call"]["inputs"]["sync-args"]["default"] == (
        "--locked --all-packages --group dev"
    )


@pytest.mark.parametrize(
    "path", PYTHON_INSTALL_SURFACES, ids=lambda path: str(path.relative_to(REPO_ROOT))
)
def test_python_install_surfaces_have_no_ci_requirements_overlay(path: Path) -> None:
    """Every published install surface must derive Python tools from uv.lock."""
    text = path.read_text(encoding="utf-8")
    assert "ci-requirements" not in text
    assert "requirements-ci.txt" not in text
