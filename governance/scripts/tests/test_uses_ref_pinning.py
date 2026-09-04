"""Every `uses:` must resolve the way the pinning canon says, or a pin buys nothing.

A git tag is writable. Moving one redefines the code inside every workflow
already released against it, with no commit here and no line in any consumer's
diff. The canon splits the rule by who owns the target
(`governance/standards/improving-fitness-gates.md`, `governance/security-scan.md`,
`README.md`): every external `uses:` is SHA-pinned to a full commit, including
this repo's references to its own actions and workflows. Nothing may sit on a
tag, `@main`, or a branch.

actionlint and yamllint accept any well-formed ref, so this test pins the shape.
`test_self_pin_freshness.py` separately reads full git history and proves that a
self-pin executes the current target content. CI checks out full history for
that contract.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]

SOURCE_GLOBS = (
    ".github/workflows/*.yml",
    "actions/*/action.yml",
    ".github/actions/*/action.yml",
)

# A local path carries no `@ref` by design: Actions resolves it against the
# calling workflow's own commit, and appending a ref is invalid syntax. It is
# already maximally pinned, so it is a branch of the rule rather than an
# exemption -- enumerating the sites would only rot.
LOCAL_PATH_PREFIX = "./"

# Calls into this repo's own composites and reusables. The canon self-pins these
# to the floating major, so the accepted forms differ from a third party's.
SELF_REPO_PREFIX = "three-cubes/tc-pipelines/"

FULL_COMMIT_SHA = re.compile(r"[0-9a-f]{40}")

# A container image is content-addressed by its digest, so a digest is as
# immutable as a commit. An image tag is not.
IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")

# "<repo-relative path>:<ref>" -> (occurrences, why this site may float).
#
# Keyed on the ref rather than the line number so an edit above the site does
# not invalidate the entry, and so changing the ref itself forces a reviewer to
# restate the reason. The count is part of the key's value because one file can
# carry the same ref twice: without it, exempting one deliberate call would
# silently exempt a second, unrelated one beside it. Never exempt a whole file:
# `.github/actions/github-app-token/action.yml` carries both a usage example in
# a `description:` block and a real call, and a file-level exemption would blind
# this guard to the real one.
FLOATING_BY_DESIGN: dict[str, tuple[int, str]] = {}


def _source_files() -> list[Path]:
    found: set[Path] = set()
    for pattern in SOURCE_GLOBS:
        found.update(REPO_ROOT.glob(pattern))
    return sorted(found)


def _uses_sites(path: Path) -> list[tuple[int, str]]:
    """(line of the `uses` key, ref) for every structural `uses` in the file.

    Composing the node graph rather than loading Python objects is what makes
    this exact. The parser drops `#` comments, and a `description: |` usage
    example stays a single scalar node whose text is never entered -- so neither
    the consumer copy-paste snippets nor the documented examples are counted as
    calls. A line regex counts both.
    """
    root = yaml.compose(path.read_text(encoding="utf-8"), Loader=yaml.SafeLoader)
    found: list[tuple[int, str]] = []

    def walk(node: yaml.Node) -> None:
        if isinstance(node, yaml.SequenceNode):
            for item in node.value:
                walk(item)
            return
        if not isinstance(node, yaml.MappingNode):
            return
        for key, value in node.value:
            names_uses = getattr(key, "value", None) == "uses"
            if names_uses and isinstance(value, yaml.ScalarNode):
                found.append((key.start_mark.line + 1, value.value))
            walk(value)

    if root is not None:
        walk(root)
    return found


def _sites() -> list[tuple[str, int, str]]:
    """(repo-relative path, line, ref), sorted so ids are stable."""
    return sorted(
        (str(path.relative_to(REPO_ROOT)), line, ref)
        for path in _source_files()
        for line, ref in _uses_sites(path)
    )


def _revision(ref: str) -> str | None:
    _, separator, revision = ref.rpartition("@")
    return revision if separator else None


def _is_acceptably_pinned(ref: str) -> bool:
    if ref.startswith(LOCAL_PATH_PREFIX):
        return True
    revision = _revision(ref)
    if revision is None:
        return False
    return bool(FULL_COMMIT_SHA.fullmatch(revision) or IMAGE_DIGEST.fullmatch(revision))


SITES = _sites()
SITE_IDS = [f"{path}:{line}" for path, line, _ in SITES]


def _actions_surfaces_on_disk() -> set[Path]:
    """Every workflow and action file, found without consulting SOURCE_GLOBS.

    An independent discovery path is what makes the coverage assertion below
    load-bearing: a glob deleted from SOURCE_GLOBS shrinks the parametrised
    suite silently, and a site-count floor is too coarse to notice -- the two
    action globs together contribute a small enough share that either could go
    unnoticed under any floor loose enough to survive a legitimate deletion.
    """
    found = set((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    found.update(
        path for path in REPO_ROOT.rglob("action.yml") if ".git" not in path.parts
    )
    return found


def test_the_scan_reads_every_actions_surface_on_disk() -> None:
    missed = sorted(
        str(path.relative_to(REPO_ROOT))
        for path in _actions_surfaces_on_disk() - set(_source_files())
    )
    assert not missed, (
        f"{missed} declare Actions surfaces that SOURCE_GLOBS does not reach, so "
        f"their `uses:` refs are unchecked while the suite still reports green. "
        f"fix: extend SOURCE_GLOBS to cover them."
    )


DECLARES_USES = re.compile(r"^\s*uses:", re.MULTILINE)


def test_the_walk_reaches_every_file_that_declares_uses() -> None:
    """A walk that stopped descending would shrink the suite, not fail it."""
    silent = sorted(
        str(path.relative_to(REPO_ROOT))
        for path in _source_files()
        if DECLARES_USES.search(path.read_text(encoding="utf-8"))
        and not _uses_sites(path)
    )
    assert not silent, (
        f"{silent} contain a `uses:` key that the structural walk did not reach. "
        f"Those calls are then unchecked while every assertion below still "
        f"passes. "
        f"fix: confirm the walk descends into job mappings and into a composite "
        f"action's `runs.steps`, not only into top-level step sequences."
    )


def test_the_scan_found_uses_sites() -> None:
    """A scan that silently matches nothing would pass every assertion below."""
    assert len(SITES) >= 120, (
        f"only {len(SITES)} `uses:` sites discovered across {SOURCE_GLOBS} — the "
        f"structural walk has drifted, so ref pinning is no longer being checked. "
        f"fix: confirm the globs still name every workflow and action file, and "
        f"that the walk still reaches step-level `uses` inside composite actions."
    )


def test_the_scan_reaches_self_references() -> None:
    """Self-references are the class that defeats a consumer's pin."""
    self_refs = [s for s in SITES if s[2].startswith(SELF_REPO_PREFIX)]
    assert len(self_refs) >= 15, (
        f"only {len(self_refs)} `{SELF_REPO_PREFIX}...` sites discovered. "
        f"A consumer pins this repo by SHA; these are the calls that can still "
        f"float underneath that pin, so dropping them guts the guard. "
        f"fix: check the walk still descends into composite action steps."
    )


def test_the_scan_reaches_local_path_references() -> None:
    """The local-path branch must stay exercised rather than become dead code."""
    local = [s for s in SITES if s[2].startswith(LOCAL_PATH_PREFIX)]
    assert len(local) >= 10, (
        f"only {len(local)} `./` sites discovered. If local paths have genuinely "
        f"gone, delete the LOCAL_PATH_PREFIX branch; otherwise the walk is "
        f"missing job-level `uses` on reusable-workflow calls. "
        f"fix: confirm the walk visits job mappings, not only step sequences."
    )


# (ref, accepted?) — a positive control, so the rule cannot rot into one that
# accepts everything. Built from repeated characters rather than literal hashes
# to keep a secret scanner from reading them as credentials.
CLASSIFIER_CASES = (
    ("./.github/workflows/python-quality-gate.yml", True),
    ("./.github/actions/github-app-token", True),
    (f"owner/repo@{'a' * 40}", True),
    (f"owner/repo/path/to/action@{'0' * 40}", True),
    (f"docker://ghcr.io/owner/image@sha256:{'b' * 64}", True),
    (f"{SELF_REPO_PREFIX}actions/setup-uv-cached@{'c' * 40}", True),
    # A self-reference gets no exemption. A floating major only stays correct
    # while something advances that tag on every release; nothing here does, so
    # `@v1` froze and a step loaded a revision of the composite that no longer
    # emitted the output its workflow read.
    (f"{SELF_REPO_PREFIX}actions/setup-uv-cached@v1", False),
    (f"{SELF_REPO_PREFIX}.github/workflows/release.yml@v2", False),
    (f"{SELF_REPO_PREFIX}actions/setup-uv-cached@v1.17.0", False),
    (f"{SELF_REPO_PREFIX}actions/setup-uv-cached@main", False),
    ("owner/repo@v1", False),
    ("owner/repo@v1.10.0", False),
    ("owner/repo@main", False),
    ("docker://alpine:3.19", False),
    (f"owner/repo@{'a' * 7}", False),
    (f"owner/repo@{'A' * 40}", False),
    ("owner/repo", False),
)


@pytest.mark.parametrize(("ref", "accepted"), CLASSIFIER_CASES)
def test_the_classifier_separates_a_moving_ref_from_a_pinned_one(
    ref: str, accepted: bool
) -> None:
    assert _is_acceptably_pinned(ref) is accepted, (
        f"the pinning rule now judges {ref!r} "
        f"{'unpinned' if accepted else 'pinned'}, which is backwards. A rule "
        f"that accepts a branch, a point tag on a self-reference or an "
        f"abbreviated SHA lets the whole suite below pass while every ref still "
        f"floats. "
        f"fix: keep FULL_COMMIT_SHA a 40-character lowercase match under "
        f"fullmatch and keep `./` the only ref-free form."
    )


@pytest.mark.parametrize(("path", "line", "ref"), SITES, ids=SITE_IDS)
def test_uses_ref_is_pinned_the_way_the_canon_requires(
    path: str, line: int, ref: str
) -> None:
    key = f"{path}:{ref}"
    if key in FLOATING_BY_DESIGN:
        return

    if ref.startswith(SELF_REPO_PREFIX):
        remedy = (
            f"fix: repin to a full 40-character lowercase commit SHA of a "
            f"released tag, with a `# vX.Y.Z` trailing comment. A floating "
            f"major such as `@v1` only works while something advances that tag "
            f"on every release; nothing here does, so it froze and a step "
            f"loaded a revision of the composite that no longer emitted the "
            f"output the workflow read — silently, because "
            f"test_internal_call_contracts.py validates against the LOCAL file, "
            f"not the ref that runs."
        )
    else:
        remedy = (
            "fix: repin to the full 40-character lowercase commit SHA with a "
            "`# vX.Y.Z` trailing comment, in the style used by every other "
            "third-party call in this repo."
        )

    assert _is_acceptably_pinned(ref), (
        f"{path}:{line} calls `{ref}` through a moving ref. A tag is writable, "
        f"so moving it retroactively redefines this step for every release "
        f"already cut against it — and a consumer who SHA-pins this repo still "
        f"runs whatever that ref points at today, which defeats their pin. "
        f"{remedy} Or add '{key}' to FLOATING_BY_DESIGN with its occurrence "
        f"count and the reason it must float."
    )


def test_every_declared_exception_still_covers_exactly_its_sites() -> None:
    """A stale or under-counted exemption would silently excuse a live call."""
    live: dict[str, int] = {}
    for path, _line, ref in SITES:
        if not _is_acceptably_pinned(ref):
            live[f"{path}:{ref}"] = live.get(f"{path}:{ref}", 0) + 1

    drifted = sorted(
        (key, declared, live.get(key, 0))
        for key, (declared, _reason) in FLOATING_BY_DESIGN.items()
        if live.get(key, 0) != declared
    )
    assert not drifted, (
        f"FLOATING_BY_DESIGN entries no longer match the tree "
        f"(key, declared, present): {drifted}. At zero the exemption outlives "
        f"the call it explains and would excuse a future ref that reuses the "
        f"key; above the declared count it is silently excusing a second call "
        f"beside the reviewed one. "
        f"fix: delete the entry, or restate the count with the reason the new "
        f"call must float."
    )
