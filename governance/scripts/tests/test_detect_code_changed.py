"""Contract test for the change-gate decision helper (SGO-280).

`actions/detect-code-changes/decide-code-changed.sh` is the PURE decision the
`python-quality-gate.yml` reusable uses to gate the pytest shard fan-out: given a
repo-relative changed-file list and a consumer-supplied extended-regex filter, it
answers "did code change?" (`true`) or "docs/config-only?" (`false`). Extracting
the decision here (rather than burying it in workflow YAML) makes the
skip-the-shards logic unit-testable off a real runner.

Backward-compat contract (the reason no consumer breaks): an EMPTY filter means
"change-detection disabled" → the helper answers `true`, so the shard matrix runs
exactly as it does today. Any ambiguity (no changed-file list) fails OPEN to
`true` — the helper never wrongly SKIPS the tests.

Interface: shell-entrypoint.actions.detect-code-changes.decide-code-changed
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = "actions/detect-code-changes/decide-code-changed.sh"

# A representative "code changed" filter: Python sources/tests + the lockable
# dependency surface. Anchored ERE alternation (the shape a consumer declares).
CODE_FILTER = r"\.py$|^src/|^tests/|^pyproject\.toml$|^uv\.lock$"


def _decide(changed_files: str, filter_re: str, tmp_path: Path) -> str:
    # The script path is a literal (not a Path var) so an outcome-test gate can
    # match the surface name in the subprocess call; cwd resolves it.
    cf = tmp_path / "changed.txt"
    cf.write_text(changed_files, encoding="utf-8")
    result = subprocess.run(
        [
            "bash",
            "actions/detect-code-changes/decide-code-changed.sh",
            "--filter",
            filter_re,
            "--changed-files",
            str(cf),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_docs_only_change_skips_the_shards(tmp_path: Path) -> None:
    # A docs/config-only PR: no changed path matches the code filter → false → the
    # reusable skips the pytest shard fan-out.
    changed = "docs/architecture.md\nREADME.md\n.github/CODEOWNERS\n"
    assert _decide(changed, CODE_FILTER, tmp_path) == "false"


def test_code_change_runs_the_shards(tmp_path: Path) -> None:
    # A Python source change matches → true → the shard matrix runs.
    changed = "docs/architecture.md\nsrc/pkg/service.py\n"
    assert _decide(changed, CODE_FILTER, tmp_path) == "true"


def test_test_only_change_runs_the_shards(tmp_path: Path) -> None:
    # Editing a test is a code change — the suite must run.
    assert _decide("tests/test_service.py\n", CODE_FILTER, tmp_path) == "true"


def test_dependency_surface_change_runs_the_shards(tmp_path: Path) -> None:
    # A pyproject/lock bump changes what the suite runs against → run the shards.
    assert _decide("pyproject.toml\n", CODE_FILTER, tmp_path) == "true"
    assert _decide("uv.lock\n", CODE_FILTER, tmp_path) == "true"


def test_empty_filter_is_disabled_and_runs_the_shards(tmp_path: Path) -> None:
    # BACKWARD-COMPAT: an empty filter means detection is off → true → the shard
    # matrix runs exactly as it does for every consumer that sets no filter.
    changed = "docs/only.md\n"
    assert _decide(changed, "", tmp_path) == "true"


def test_empty_changed_list_fails_open(tmp_path: Path) -> None:
    # Ambiguity (no changed-file list, e.g. a diff the runner could not compute)
    # fails OPEN to true — never wrongly SKIP the tests.
    assert _decide("", CODE_FILTER, tmp_path) == "true"


def test_missing_changed_files_flag_fails_open(tmp_path: Path) -> None:
    # No --changed-files at all → fail open to true.
    result = subprocess.run(
        [
            "bash",
            "actions/detect-code-changes/decide-code-changed.sh",
            "--filter",
            CODE_FILTER,
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "true"


def test_filter_is_not_matched_as_a_substring_of_a_docs_path(tmp_path: Path) -> None:
    # Anchoring guard: a `.py` filter must not fire on a path that merely CONTAINS
    # ".py" without ending in it (e.g. a docs file named `pyproject-notes.md`).
    changed = "docs/pyproject-notes.md\nnotes/python-tips.md\n"
    assert _decide(changed, CODE_FILTER, tmp_path) == "false"
