"""Contract for automatic tc-pipelines self-pin adoption after a release."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[3]
UPDATER = ROOT / "governance/scripts/repin_self_references.py"
WORKFLOW = ROOT / ".github/workflows/dispatch-consumer-repins.yml"
OLD_SHA = "1c2944c0cca248bd42fa2e56e84fc3d97a9c698b"  # pragma: allowlist secret
NEW_SHA = "8eac47d7519032e61b1d4fe00f3e4ac1ef67579e"  # pragma: allowlist secret


def test_repin_self_references_updates_each_immutable_self_pin(tmp_path: Path) -> None:
    """The release successor advances every self-pin in one reviewed change."""

    workflow = tmp_path / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        f"uses: three-cubes/tc-pipelines/actions/setup-uv-cached@{OLD_SHA} # v1.19.11\n",
        encoding="utf-8",
    )
    action = tmp_path / "actions/python-gate-body/action.yml"
    action.parent.mkdir(parents=True)
    action.write_text(
        f"uses: three-cubes/tc-pipelines/actions/setup-uv-cached@{OLD_SHA} # v1.19.11\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(UPDATER),
            "--root",
            str(tmp_path),
            "--sha",
            NEW_SHA,
            "--version",
            "v1.19.12",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "updated 2 file(s) to v1.19.12" in completed.stdout
    assert workflow.read_text(encoding="utf-8").count(NEW_SHA) == 1
    assert action.read_text(encoding="utf-8").count(NEW_SHA) == 1


def test_published_release_opens_a_self_repin_pr_before_the_next_tag() -> None:
    """The producer advances its own pins without a manual release chore."""

    text = WORKFLOW.read_text(encoding="utf-8")

    assert "Mint three-cubes-agent token for tc-pipelines" in text
    assert (
        'governance/scripts/repin_self_references.py --sha "$SHA" --version "$VERSION"'
        in text
    )
    assert "chore: repin tc-pipelines self references" in text
    assert "gh pr merge --auto --merge" in text
