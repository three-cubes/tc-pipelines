"""Contract for dispatching immutable tc-pipelines releases to consumers."""

from __future__ import annotations

from pathlib import Path

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/dispatch-consumer-repins.yml"
RELEASE_WORKFLOW = ROOT / ".github/workflows/release.yml"


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
    assert "environment: production" in text
    assert 'repos/three-cubes/tc-pipelines/releases/tags/${version}' in text


def test_release_uses_the_agent_app_token_for_tags_releases_and_fan_out() -> None:
    """An App-created release emits the published event that starts consumer repins."""

    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "id-token: write" in text
    assert "Mint three-cubes-agent token for release" in text
    assert "three-cubes/tc-pipelines/.github/actions/github-app-token@" in text
    assert "GH_TOKEN: ${{ steps.app.outputs.token }}" in text
    assert "secrets.gh-token || github.token" not in text
