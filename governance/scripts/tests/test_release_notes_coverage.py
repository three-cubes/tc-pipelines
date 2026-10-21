"""Release notes need a section to come from, and a blank one must not ship.

`release.yml` builds the entire GitHub Release body from the CHANGELOG section
whose label is derived from its one release coordinate: the tag with a
conventional leading `v` removed. Nothing else contributes to that body, and
the two ways that section can fail to supply one are not symmetric.

An absent section extracts to zero bytes, which the step's own emptiness check
rejects, so the release stops and the failure is visible. A section that exists
but is empty extracts to the single blank line before the next heading, and an
emptiness check written as a file-size test counts that one byte as content: the
extractor's output reaches `--notes-file` unchanged, the step prints an empty
preview group, the job reports success, and the Release publishes with nothing
in it. That is the state the documented CHANGELOG flow leaves `## [Unreleased]`
in — the preparation action moves its bullets into a dated section before the tag is
cut.

These tests run the reusable's real preparation and extraction steps over
fixture repositories. tc-pipelines' check that each of its own release tags has
a CHANGELOG section read that repository's tags and stays with it (ledger
reusable-workflow-contract-ci).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
# In agent-platform the reusable workflows live at the repository root, two levels
# above execution/pipelines/; in the public tc-pipelines export REPO_ROOT is that
# root. Resolve whichever layout this file runs in.
PLATFORM_ROOT = REPO_ROOT if (REPO_ROOT / ".github" / "workflows").is_dir() else REPO_ROOT.parents[1]
RELEASE = PLATFORM_ROOT / ".github" / "workflows" / "release.yml"
PREPARE_RELEASE = REPO_ROOT / "actions" / "prepare-release-metadata" / "prepare_release.py"

EXTRACT_STEP = "Extract release notes from CHANGELOG"
PREPARE_STEP = "Validate prepared release metadata"


def _extract_step_run() -> str:
    document = yaml.safe_load(RELEASE.read_text(encoding="utf-8")) or {}
    for job in (document.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and step.get("name") == EXTRACT_STEP:
                return str(step.get("run") or "")
    return ""


def _prepare_step_run() -> str:
    document = yaml.safe_load(RELEASE.read_text(encoding="utf-8")) or {}
    for job in (document.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and step.get("name") == PREPARE_STEP:
                return str(step.get("run") or "")
    return ""


def _git(cwd: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd, check=False)
    assert result.returncode == 0, result.stderr


def _prepared_release_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "release-test")
    _git(repository, "config", "user.email", "release-test@example.invalid")
    (repository / "VERSION").write_text("0.0.0\n", encoding="utf-8")
    (repository / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Changed\n\n- A prepared release item.\n\n"
        "## [0.0.0] — 2000-01-01\n\n- Previous release.\n",
        encoding="utf-8",
    )
    _git(repository, "add", "CHANGELOG.md", "VERSION")
    _git(repository, "commit", "-qm", "initial release ledger")
    return repository


def test_prepare_release_metadata_mechanically_binds_version_and_changelog(
    tmp_path: Path,
) -> None:
    """The real preparation command writes the version, notes, and receipt.

    The tag workflow then executes its real validation step.  This is a
    filesystem-and-Git integration test: no mocked command, workflow, or
    subprocess can make a manually edited section look prepared.
    """
    repository = _prepared_release_repository(tmp_path)
    prepared = subprocess.run(
        [
            "python3",
            str(PREPARE_RELEASE),
            "--version",
            "v2099.9.9",
            "--date",
            "2099-09-09",
        ],
        capture_output=True,
        text=True,
        cwd=repository,
        check=False,
    )
    assert prepared.returncode == 0, prepared.stderr
    assert (repository / "VERSION").read_text(encoding="utf-8") == "2099.9.9\n"
    changelog = (repository / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Unreleased]\n\n## [2099.9.9] — 2099-09-09" in changelog
    assert "- A prepared release item." in changelog
    assert (repository / ".release-prepared.json").is_file()
    _git(repository, "add", "CHANGELOG.md", "VERSION", ".release-prepared.json")
    _git(repository, "commit", "-qm", "prepare v2099.9.9")

    step = _prepare_step_run()
    assert step, f"release.yml has no `{PREPARE_STEP}` step."
    validated = subprocess.run(
        ["bash", "-c", 'export VERSION="$1"\n' + step, "guard", "v2099.9.9"],
        capture_output=True,
        text=True,
        cwd=repository,
        check=False,
    )
    assert validated.returncode == 0, validated.stderr


def test_release_validation_preserves_an_explicit_empty_version_file(
    tmp_path: Path,
) -> None:
    """A pyproject-backed release must not silently fall back to VERSION."""
    repository = _prepared_release_repository(tmp_path)
    (repository / "VERSION").unlink()
    (repository / "pyproject.toml").write_text(
        '[project]\nname = "release-fixture"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    prepared = subprocess.run(
        [
            "python3",
            str(PREPARE_RELEASE),
            "--version",
            "v2099.9.9",
            "--version-file",
            "",
            "--date",
            "2099-09-09",
        ],
        capture_output=True,
        text=True,
        cwd=repository,
        check=False,
    )
    assert prepared.returncode == 0, prepared.stderr
    assert not (repository / "VERSION").exists()

    step = _prepare_step_run()
    assert step, f"release.yml has no `{PREPARE_STEP}` step."
    validated = subprocess.run(
        [
            "bash",
            "-c",
            (
                'export VERSION="$1"\n'
                'export CHANGELOG_FILE="CHANGELOG.md"\n'
                'export VERSION_FILE=""\n'
                'export PREPARATION_FILE=".release-prepared.json"\n' + step
            ),
            "guard",
            "v2099.9.9",
        ],
        capture_output=True,
        text=True,
        cwd=repository,
        check=False,
    )
    assert validated.returncode == 0, validated.stderr


def test_release_rejects_a_versioned_section_without_a_prepared_commit(
    tmp_path: Path,
) -> None:
    """A hand-edited CHANGELOG section cannot substitute for preparation."""
    repository = _prepared_release_repository(tmp_path)
    (repository / "VERSION").write_text("2099.9.9\n", encoding="utf-8")
    (repository / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [2099.9.9] — 2099-09-09\n\n- Manual.\n",
        encoding="utf-8",
    )
    _git(repository, "add", "CHANGELOG.md", "VERSION")
    _git(repository, "commit", "-qm", "manual release ledger")

    step = _prepare_step_run()
    assert step, f"release.yml has no `{PREPARE_STEP}` step."
    rejected = subprocess.run(
        ["bash", "-c", 'export VERSION="$1"\n' + step, "guard", "v2099.9.9"],
        capture_output=True,
        text=True,
        cwd=repository,
        check=False,
    )
    assert rejected.returncode != 0
    assert "release preparation receipt" in rejected.stderr


def test_release_notes_section_label_is_derived_from_the_release_version() -> None:
    """A release has one coordinate: its tag; its notes section follows it.

    A separate caller-maintained label allowed v2.0.0 to be tagged while its
    release notes remained under ``Unreleased``.  The reusable must derive the
    CHANGELOG heading from ``version`` (stripping only the tag's conventional
    leading ``v``) and must not accept a second release-notes coordinate.
    """
    document = yaml.safe_load(RELEASE.read_text(encoding="utf-8")) or {}
    triggers = document.get(True) or document.get("on") or {}
    inputs = (triggers.get("workflow_call") or {}).get("inputs") or {}
    assert (inputs.get("changelog-label") or {}).get("default") == "", (
        "release.yml gives changelog-label an independent default, so callers "
        "can tag one version while extracting another section. fix: retain it "
        "only as an empty deprecated compatibility input."
    )
    assert (inputs.get("changelog-extract-command") or {}).get("default") == "", (
        "release.yml gives a caller extractor release-note authority by default. "
        "fix: retain it only as an empty deprecated compatibility input."
    )
    step = _extract_step_run()
    assert 'CHANGELOG_LABEL="${VERSION#v}"' in step, (
        "the canonical extraction step does not derive its CHANGELOG label "
        'from VERSION. fix: set CHANGELOG_LABEL="${VERSION#v}" before '
        "extracting CHANGELOG.md."
    )


NOTES_SENTINEL = "a bullet the release notes must carry"
RELEASE_VERSION = "v2099.9.9"
RELEASE_LABEL = RELEASE_VERSION.removeprefix("v")

# A further heading after the labelled section, so extraction has to stop
# somewhere rather than running to end-of-file.
TRAILING_SECTION = "## [9.9.9] — 1970-01-01\n\n### Added\n\n- an entry outside the label.\n"
EMPTY_BODY = "\n"
POPULATED_BODY = f"\n### Added\n\n- {NOTES_SENTINEL}.\n\n"


def _changelog_fixture(label: str, body: str) -> str:
    return f"# Changelog\n\n## [{label}]\n{body}{TRAILING_SECTION}"


NOTES_REDIRECT = re.compile(r">\s*(\S*release-notes\.md)")


def _bash(script: str, cwd: Path, version: str) -> subprocess.CompletedProcess[str]:
    """Run the real step body with the version input it receives from GitHub."""
    prelude = 'export VERSION="$1"\n'
    return subprocess.run(
        ["bash", "-c", prelude + script, "guard", version],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        check=False,
    )


def _extract_step_against(tmp_path: Path, body: str) -> tuple[int, str]:
    """Run the real step body over a fixture CHANGELOG, returning rc and notes."""
    step = _extract_step_run()
    assert step, (
        f"no step named `{EXTRACT_STEP}` in {RELEASE.name}, so the notes "
        f"emptiness check is not being exercised at all and every assertion "
        f"over it is vacuous. "
        f"fix: point EXTRACT_STEP at the step's current name."
    )
    redirect = NOTES_REDIRECT.search(step)
    assert redirect, (
        f"the `{EXTRACT_STEP}` step no longer redirects the extractor into a "
        f"release-notes file, so this guard cannot retarget it at a scratch "
        f"path and would otherwise read a stale /tmp file. "
        f"fix: point NOTES_REDIRECT at the step's current notes path."
    )
    # Every scratch file the step names under /tmp moves into this test's own
    # directory, so cases running in parallel never share a notes file.
    notes = tmp_path / Path(redirect.group(1)).name
    (tmp_path / "CHANGELOG.md").write_text(_changelog_fixture(RELEASE_LABEL, body), encoding="utf-8")
    scratch = re.compile(r"(?<![\w/])/tmp/([A-Za-z0-9._-]+)")
    script = scratch.sub(lambda m: str(tmp_path / m.group(1)), step)
    # tmp_path itself may sit under /tmp, so check the step's own names, not the result.
    assert not scratch.search(script.replace(str(tmp_path), "")), (
        f"`{EXTRACT_STEP}` names a /tmp path this guard cannot isolate"
    )
    result = _bash(script, tmp_path, RELEASE_VERSION)
    written = notes.read_text(encoding="utf-8") if notes.exists() else ""
    return result.returncode, written


def test_the_canonical_extractor_emits_whitespace_for_an_empty_section(
    tmp_path: Path,
) -> None:
    """A zero-byte extraction would satisfy a size test honestly.

    The rejection assertion below only proves anything if the canonical
    extractor produces a body that is non-empty yet blank, so pin that
    precondition separately.
    """
    _, notes = _extract_step_against(tmp_path, EMPTY_BODY)
    assert notes and not notes.strip(), (
        f"the canonical extractor wrote {notes!r} for an empty section, not the "
        f"whitespace-only body this guard exercises release.yml against. "
        f"fix: rebuild EMPTY_BODY so the labelled section is empty but still "
        f"followed by a further heading."
    )


def test_release_notes_extraction_rejects_a_whitespace_only_body(
    tmp_path: Path,
) -> None:
    returncode, _ = _extract_step_against(tmp_path, EMPTY_BODY)
    assert returncode != 0, (
        f"the `{EXTRACT_STEP}` step accepted a whitespace-only extraction. An "
        f"existing but empty section extracts to a one-byte newline, which a "
        f"size test (`[ -s ]`) counts as content, so the step hands "
        f"`--notes-file` a blank body, the job reports success, and the Release "
        f"publishes empty. "
        f"fix: gate on non-whitespace content in .github/workflows/release.yml, "
        f"e.g. `if ! grep -q '[^[:space:]]' /tmp/release-notes.md; then`."
    )


def test_release_notes_extraction_accepts_a_populated_section(
    tmp_path: Path,
) -> None:
    """Without this, a step that always fails satisfies the rejection above."""
    returncode, notes = _extract_step_against(tmp_path, POPULATED_BODY)
    assert returncode == 0, (
        f"the `{EXTRACT_STEP}` step rejected a section with real content, so "
        f"every release stops at this step and none can be cut. "
        f"fix: narrow the emptiness check in .github/workflows/release.yml so "
        f"it rejects only whitespace, not a populated section."
    )
    assert NOTES_SENTINEL in notes, (
        f"the `{EXTRACT_STEP}` step exited 0 but the notes file does not carry "
        f"the section's content, so `--notes-file` would publish a Release body "
        f"that is not the CHANGELOG section. notes: {notes!r} "
        f"fix: keep the extractor's stdout as the whole notes file in "
        f".github/workflows/release.yml."
    )
