"""Contract for the release-safe repository merge-method verifier."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK = REPO_ROOT / "governance" / "scripts" / "check-repository-merge-settings.sh"
BOOTSTRAP_STANDARD = REPO_ROOT / "governance" / "standards" / "new-repo-bootstrap.md"


def test_merge_settings_check_reads_and_enforces_the_three_repository_fields() -> None:
    """Release ancestry requires merge commits and rejects squash/rebase."""
    text = CHECK.read_text(encoding="utf-8")
    assert "gh api \"repos/${REPOSITORY}\"" in text
    assert '"allow_merge_commit":true' in text
    assert '"allow_squash_merge":false' in text
    assert '"allow_rebase_merge":false' in text
    assert "gh api --method PATCH" not in text


def test_bootstrap_standard_contains_admin_action_and_readback_check() -> None:
    """The admin setting mutation is explicit and followed by a read-only check."""
    text = BOOTSTRAP_STANDARD.read_text(encoding="utf-8")
    assert "gh api --method PATCH repos/three-cubes/<name>" in text
    assert "-F allow_merge_commit=true" in text
    assert "-F allow_squash_merge=false" in text
    assert "-F allow_rebase_merge=false" in text
    assert "check-repository-merge-settings.sh three-cubes/<name>" in text
