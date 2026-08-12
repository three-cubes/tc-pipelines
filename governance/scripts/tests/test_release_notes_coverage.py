"""Release notes need a section to come from, and a blank one must not ship.

`release.yml` builds the entire GitHub Release body by `eval`-ing a
caller-supplied extractor against the CHANGELOG section named by
`changelog-label`. Nothing else contributes to that body, and the two ways that
section can fail to supply one are not symmetric.

An absent section extracts to zero bytes, which the step's own emptiness check
rejects, so the release stops and the failure is visible. A section that exists
but is empty extracts to the single blank line before the next heading, and an
emptiness check written as a file-size test counts that one byte as content: the
extractor's output reaches `--notes-file` unchanged, the step prints an empty
preview group, the job reports success, and the Release publishes with nothing
in it. That is the state the documented CHANGELOG flow leaves `## [Unreleased]`
in — the release PR moves its bullets into a dated section — and
`changelog-label` defaults to `Unreleased`.

A missing section costs the record rather than the run.
`governance/standards/sdlc-release-workflow.md` requires the release PR to add
the dated section, and consumers pinned to `@vN` read it to decide whether to
move the pin. Every tag in LEGACY_TAGS_WITHOUT_NOTES lacks one, so that range
carries no such record.

None of this is reachable by actionlint, yamllint or the script-level tests: the
tag list, the CHANGELOG and the workflow are three separate artefacts and each
one is individually valid.

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
EXAMPLE_RELEASE = REPO_ROOT / ".github" / "workflows" / "example-release.yml"

EXTRACT_STEP = "Extract release notes from CHANGELOG"

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
    return re.search(rf"^## \[{re.escape(version)}\]", text, re.M) is not None


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
        f"pushed. Without it a caller passing `changelog-label: {version}` "
        f"extracts zero bytes and release.yml stops the release, and a consumer "
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


def _release_input_default(name: str) -> str:
    document = yaml.safe_load(RELEASE.read_text(encoding="utf-8")) or {}
    # `on:` parses as the boolean True under YAML 1.1.
    triggers = document.get(True) or document.get("on") or {}
    inputs = (triggers.get("workflow_call") or {}).get("inputs") or {}
    return str((inputs.get(name) or {}).get("default") or "")


def _caller_extraction() -> tuple[str, str]:
    """Label and extractor from the same example caller, so they cannot drift."""
    document = yaml.safe_load(EXAMPLE_RELEASE.read_text(encoding="utf-8")) or {}
    for job in (document.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        supplied = job.get("with") or {}
        command = supplied.get("changelog-extract-command")
        if command:
            label = supplied.get("changelog-label") or _release_input_default(
                "changelog-label"
            )
            return str(label), str(command)
    return "", ""


NOTES_SENTINEL = "a bullet the release notes must carry"

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


def _bash(
    script: str, cwd: Path, label: str, extract: str
) -> subprocess.CompletedProcess[str]:
    """Run a step body under the two variables release.yml binds through `env:`.

    They arrive as positional arguments and are exported by a prelude, so the
    step body itself executes verbatim and the runner's PATH is inherited.
    """
    prelude = 'export CHANGELOG_LABEL="$1"\nexport EXTRACT_COMMAND="$2"\n'
    return subprocess.run(
        ["bash", "-c", prelude + script, "guard", label, extract],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        check=False,
    )


def _extract_step_against(tmp_path: Path, body: str) -> tuple[int, str]:
    """Run the real step body over a fixture CHANGELOG, returning rc and notes."""
    label, command = _caller_extraction()
    step = _extract_step_run()
    assert step, (
        f"no step named `{EXTRACT_STEP}` in {RELEASE.name}, so the notes "
        f"emptiness check is not being exercised at all and every assertion "
        f"over it is vacuous. "
        f"fix: point EXTRACT_STEP at the step's current name."
    )
    assert command, (
        f"no `changelog-extract-command` found in {EXAMPLE_RELEASE.name}, so "
        f"the step would run against an empty command and every assertion over "
        f"it is vacuous. "
        f"fix: keep a real consumer-shaped extractor in the example caller."
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
        _changelog_fixture(label, body), encoding="utf-8"
    )
    script = step.replace(redirect.group(1), str(notes))
    result = _bash(script, tmp_path, label, command)
    written = notes.read_text(encoding="utf-8") if notes.exists() else ""
    return result.returncode, written


def test_the_caller_extractor_emits_whitespace_for_an_empty_section(
    tmp_path: Path,
) -> None:
    """A zero-byte extraction would satisfy a size test honestly.

    The rejection assertion below only proves anything if the extractor produces
    a body that is non-empty yet blank, so pin that precondition separately.
    """
    label, command = _caller_extraction()
    assert command, (
        f"no `changelog-extract-command` found in {EXAMPLE_RELEASE.name}, so "
        f"this precondition and the assertions relying on it are vacuous. "
        f"fix: keep a real consumer-shaped extractor in the example caller."
    )
    (tmp_path / "CHANGELOG.md").write_text(
        _changelog_fixture(label, EMPTY_BODY), encoding="utf-8"
    )
    result = _bash(
        'set -euo pipefail\neval "$EXTRACT_COMMAND"', tmp_path, label, command
    )
    assert result.returncode == 0, (
        f"the example caller's extractor exited {result.returncode} on the "
        f"fixture CHANGELOG, so the assertions below would be testing a broken "
        f"extractor rather than the step. stderr: {result.stderr.strip()!r} "
        f"fix: reconcile EMPTY_BODY with what the extractor in "
        f"{EXAMPLE_RELEASE.name} expects to parse."
    )
    assert result.stdout and not result.stdout.strip(), (
        f"the extractor emitted {result.stdout!r} for an empty section, not the "
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
