"""Contract for dispatching immutable tc-pipelines releases to consumers."""

from __future__ import annotations

from pathlib import Path

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/dispatch-consumer-repins.yml"


def test_published_release_dispatches_a_verified_sha_to_tc_agent_zone() -> None:
    """The consumer receives an immutable tag and its resolved commit, never a branch."""

    text = WORKFLOW.read_text(encoding="utf-8")

    assert "release:" in text
    assert "published" in text
    assert "workflow_dispatch:" in text
    assert "git rev-parse HEAD" in text
    assert "tc-pipelines-release" in text
    assert "repos/three-cubes/tc-agent-zone/dispatches" in text
    assert '"sha": $sha' in text
    assert '"version": $version' in text
    assert "repositories: tc-agent-zone" in text
