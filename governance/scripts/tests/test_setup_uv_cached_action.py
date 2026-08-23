"""Contract tests for the org-standard uv setup composite."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTION = REPO_ROOT / "actions" / "setup-uv-cached" / "action.yml"


def test_hash_locked_ci_tools_do_not_reapply_project_configuration() -> None:
    """Project overrides are resolved by ``uv sync``, not the hash-only install."""
    action = ACTION.read_text(encoding="utf-8")

    assert "uv sync ${{ inputs.sync-args }}" in action
    assert "uv pip install --no-config --require-hashes --only-binary :all:" in action
