"""Contract for the release-safe repository merge-method verifier."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK = REPO_ROOT / "governance" / "scripts" / "check-repository-merge-settings.sh"
BOOTSTRAP_STANDARD = REPO_ROOT / "governance" / "standards" / "new-repo-bootstrap.md"
NEXT = "next: uv run --frozen pytest -q assurance/governance/scripts/tests/test_repository_merge_settings.py"


@pytest.mark.parametrize(
    "required",
    [
        'gh api "repos/${REPOSITORY}"',
        '"allow_merge_commit":true',
        '"allow_squash_merge":false',
        '"allow_rebase_merge":false',
    ],
)
def test_merge_settings_check_reads_and_enforces_the_three_repository_fields(required: str) -> None:
    """Release ancestry requires merge commits and rejects squash/rebase."""
    assert required in CHECK.read_text(encoding="utf-8"), (
        f"{CHECK.name} no longer reads or requires `{required}`, so a repository that squashes or "
        f"rebases would pass the release-safety check. fix: restore the read-back of that field in "
        f"{CHECK.name}; {NEXT}"
    )


def test_merge_settings_check_never_mutates_the_repository() -> None:
    assert "gh api --method PATCH" not in CHECK.read_text(encoding="utf-8"), (
        f"{CHECK.name} now changes repository settings; it is a read-only verifier, and the mutation "
        f"is the admin step in {BOOTSTRAP_STANDARD.name}. fix: remove the PATCH call; {NEXT}"
    )


@pytest.mark.parametrize(
    "required",
    [
        "gh api --method PATCH repos/three-cubes/<name>",
        "-F allow_merge_commit=true",
        "-F allow_squash_merge=false",
        "-F allow_rebase_merge=false",
        "check-repository-merge-settings.sh three-cubes/<name>",
    ],
)
def test_bootstrap_standard_contains_admin_action_and_readback_check(required: str) -> None:
    """The admin setting mutation is explicit and followed by a read-only check."""
    assert required in BOOTSTRAP_STANDARD.read_text(encoding="utf-8"), (
        f"{BOOTSTRAP_STANDARD.name} no longer carries `{required}`, so a new repository's merge "
        f"settings are neither set by the admin step nor read back. fix: restore it in the "
        f"standard's merge-settings step; {NEXT}"
    )
