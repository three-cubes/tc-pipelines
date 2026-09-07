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
in — the release PR moves its bullets into a dated section before the tag is
cut.

A missing section costs the record rather than the run.
`governance/standards/sdlc-release-workflow.md` requires the release PR to add
the dated section, and consumers pinned to `@vN` read it to decide whether to
move the pin. Every tag in LEGACY_TAGS_WITHOUT_NOTES lacks one, so that range
carries no such record.

The tag and CHANGELOG still need the release-history coverage check below, but
the reusable no longer accepts an independently maintained heading label that
can make its release notes drift from its tag.

Only tag -> section is checked. A section with no tag is the correct state of a
release PR, which adds the dated section before the tag is pushed, so the
reverse direction would be unsatisfiable on every such PR.

Tags cut before this guard are frozen in LEGACY_TAGS_WITHOUT_NOTES with their
reason, making the guard a ratchet: satisfiable as the repo stands, and binding
on every tag cut from here.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
RELEASE = REPO_ROOT / ".github" / "workflows" / "release.yml"
PREPARE_RELEASE = (
    REPO_ROOT / "actions" / "prepare-release-metadata" / "prepare_release.py"
)

EXTRACT_STEP = "Extract release notes from CHANGELOG"
PREPARE_STEP = "Validate prepared release metadata"

# Only `vX.Y.Z` ships. A bare-major tag (`v1`) is the floating alias consumers
# pin: it moves rather than releasing, so it never owns a section of its own.
# Stated as a shape rule so a future `v2` needs no edit here.
RELEASE_TAG = re.compile(r"^v(\d+\.\d+\.\d+)$")

# Tags cut before this guard existed. Their record survives only in tag
# annotations and merge-commit subjects, which name the branch or the release
# theme but not the consumer-facing input changes, so a section written now
# would be a reconstruction rather than the release PR's own statement.
LEGACY_TAGS_WITHOUT_NOTES = frozenset(
    {
        "v1.1.0",
        "v1.2.0",
        "v1.3.1",
        "v1.4.0",
        "v1.5.0",
        "v1.6.0",
        "v1.7.0",
        "v1.8.0",
        "v1.8.1",
        "v1.8.2",
        "v1.8.3",
        "v1.8.4",
        "v1.9.0",
        "v1.10.0",
        "v1.11.0",
        "v1.11.1",
        "v1.12.0",
        "v1.13.0",
        "v1.14.0",
        "v1.15.0",
        "v1.16.0",
        "v1.16.1",
    }
)


def _release_tags() -> list[str]:
    result = subprocess.run(
        ["git", "tag", "--list"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    if result.returncode != 0:
        return []
    return sorted(tag for tag in result.stdout.split() if RELEASE_TAG.match(tag))


def _has_section(version: str) -> bool:
    text = CHANGELOG.read_text(encoding="utf-8")
    return re.search(rf"^## \[{re.escape(version)}\]", text, re.MULTILINE) is not None


RELEASE_TAGS = _release_tags()
ENFORCED_TAGS = [tag for tag in RELEASE_TAGS if tag not in LEGACY_TAGS_WITHOUT_NOTES]


def test_the_scan_found_release_tags() -> None:
    """A tagless checkout parametrizes the coverage assertion to nothing."""
    assert len(RELEASE_TAGS) >= len(LEGACY_TAGS_WITHOUT_NOTES), (
        f"only {len(RELEASE_TAGS)} release tags visible, fewer than the "
        f"{len(LEGACY_TAGS_WITHOUT_NOTES)} already declared legacy. A checkout "
        f"without tags collapses the coverage case below to nothing, so it "
        f"passes without testing a single release. "
        f"fix: set `fetch-depth: 0` on the `tests` job checkout in "
        f".github/workflows/ci.yml — the default fetches no tags."
    )


@pytest.mark.parametrize("tag", ENFORCED_TAGS)
def test_released_tag_has_a_changelog_section(tag: str) -> None:
    version = RELEASE_TAG.match(tag).group(1)
    major = version.split(".")[0]
    assert _has_section(version), (
        f"tag {tag} has no `## [{version}]` section in CHANGELOG.md. "
        f"governance/standards/sdlc-release-workflow.md has the release PR move "
        f"the `## [Unreleased]` bullets into a dated section before the tag is "
        f"pushed. Without it release.yml extracts zero bytes and stops the "
        f"release, and a consumer "
        f"pinned to @v{major} has no written record of what changed. "
        f"fix: add a `## [{version}] — <date>` section in the PR that cuts the "
        f"release, before the tag is pushed."
    )


@pytest.mark.parametrize("tag", sorted(LEGACY_TAGS_WITHOUT_NOTES))
def test_legacy_exception_still_names_a_tag_without_a_section(tag: str) -> None:
    """A stale exception widens the set of tags allowed to ship blank notes."""
    version = RELEASE_TAG.match(tag).group(1)
    assert not _has_section(version), (
        f"LEGACY_TAGS_WITHOUT_NOTES exempts {tag}, but CHANGELOG.md now carries "
        f"a `## [{version}]` section for it. "
        f"fix: delete the entry, so the exemption cannot outlive its reason and "
        f"quietly cover a tag that no longer needs it."
    )
    # A tagless checkout is reported once by the scan meta-test; asserting tag
    # existence there too would bury that single cause under an entry per tag.
    if RELEASE_TAGS:
        assert tag in RELEASE_TAGS, (
            f"LEGACY_TAGS_WITHOUT_NOTES names {tag}, which is not a tag in this "
            f"repo. "
            f"fix: correct the name or drop the entry — an exemption naming "
            f"nothing exempts nothing and hides the typo that made it inert."
        )


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
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=cwd, check=False
    )
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
TRAILING_SECTION = (
    "## [9.9.9] — 1970-01-01\n\n### Added\n\n- an entry outside the label.\n"
)
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
    notes = tmp_path / "release-notes.md"
    (tmp_path / "CHANGELOG.md").write_text(
        _changelog_fixture(RELEASE_LABEL, body), encoding="utf-8"
    )
    script = step.replace(redirect.group(1), str(notes))
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
