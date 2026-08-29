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


def test_hash_locked_ci_tools_do_not_reapply_project_configuration() -> None:
    """Project overrides are resolved by ``uv sync``, not the hash-only install."""
    action = ACTION.read_text(encoding="utf-8")

    assert "uv sync ${{ inputs.sync-args }}" in action
    assert "uv pip install --no-config --require-hashes --only-binary :all:" in action
