"""Contract tests for the org-standard uv setup composite."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTION = REPO_ROOT / "actions" / "setup-uv-cached" / "action.yml"
UV_DEFAULT_CALLERS = (
    REPO_ROOT / "actions" / "pre-commit-cached" / "action.yml",
    REPO_ROOT / ".github" / "workflows" / "fitness-engine-canary.yml",
    REPO_ROOT / ".github" / "workflows" / "mutation-gate.yml",
    REPO_ROOT / ".github" / "workflows" / "python-quality-gate.yml",
)


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _action_uv_default() -> str:
    return _yaml(ACTION)["inputs"]["uv-version"]["default"]


def _caller_uv_default(path: Path) -> str:
    document = _yaml(path)
    if "inputs" in document:
        return document["inputs"]["uv-version"]["default"]
    # PyYAML parses the GitHub Actions key `on` as True under YAML 1.1.
    triggers = document.get(True) or document["on"]
    return triggers["workflow_call"]["inputs"]["uv-version"]["default"]


def test_org_default_uses_the_supported_hash_lock_installer() -> None:
    """The reusable default must consume the hashes it generates."""

    assert _action_uv_default() == "0.12.5"


@pytest.mark.parametrize("path", UV_DEFAULT_CALLERS)
def test_reusable_uv_defaults_match_the_setup_action(path: Path) -> None:
    """Callers that expose an optional uv pin must not silently drift."""
    assert _caller_uv_default(path) == _action_uv_default()


def test_hash_locked_ci_tools_do_not_reapply_project_configuration() -> None:
    """Project overrides are resolved by ``uv sync``, not the hash-only install."""
    action = ACTION.read_text(encoding="utf-8")

    assert "uv sync ${{ inputs.sync-args }}" in action
    assert "uv pip install --no-config --require-hashes --only-binary :all:" in action
