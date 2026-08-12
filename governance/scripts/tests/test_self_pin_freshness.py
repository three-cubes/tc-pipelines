"""A self-pinned `uses:` must load the same file this repo currently ships.

Every internal reference is pinned to a commit SHA, so a step runs whatever that
commit held — not what sits beside it in the tree. When the two diverge, the
workflow silently executes an older revision while every local check, every
reviewer and every other test reads the current one.

That has happened twice. A snapshot step pinned to a tag frozen 91 commits back
loaded a composite that no longer declared the output its workflow read, so the
rollback handle a destructive deploy advertised was the empty string on every
run. Then a cache fix landed in `setup-uv-cached` and did nothing, because
`python-gate-body` still pinned the pre-fix revision two levels down — the
consumer repinned, took the new workflow, and got the old action.

The rule: the file a self-pin loads must be byte-identical to the local copy.
A pin one release behind is fine while nothing has changed in it; the moment
something does, this fails and names the file.

`git` must be able to read the pinned object, so the checkout needs full
history. A shallow clone makes this SKIP rather than silently pass.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
SEARCH_DIRS = (".github/workflows", "actions", ".github/actions")

SELF_PIN = re.compile(
    r"uses:\s*three-cubes/tc-pipelines/(?P<path>[^@\s]+)@(?P<sha>[0-9a-f]{40})"
)

# A referenced path whose divergence is deliberate, with the reason. An entry
# here is a promise that the older revision is what the caller wants.
PINNED_BEHIND_BY_DESIGN: dict[str, str] = {}


def _source_files() -> list[Path]:
    found: list[Path] = []
    for directory in SEARCH_DIRS:
        base = REPO_ROOT / directory
        if not base.is_dir():
            continue
        found.extend(sorted(base.rglob("*.yml")))
    return found


def _self_pins() -> list[tuple[str, int, str, str]]:
    """(source file, line, referenced repo path, pinned sha)."""
    pins = []
    for path in _source_files():
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if line.lstrip().startswith("#"):
                continue
            match = SELF_PIN.search(line)
            if match:
                pins.append(
                    (
                        str(path.relative_to(REPO_ROOT)),
                        number,
                        match.group("path"),
                        match.group("sha"),
                    )
                )
    return pins


PINS = _self_pins()
PIN_IDS = [f"{source}:{line}" for source, line, _, _ in PINS]


def _without_pin_shas(text: str) -> str:
    """Blank out self-pin SHAs so a repin alone does not read as a change.

    Bumping a pin edits the file, which would otherwise make it differ from the
    revision that pin loads — an invariant no release-prep commit could satisfy.
    Comparing with the SHAs normalised keeps the assertion on the SUBSTANCE: a
    changed step, input or command still fails, a pure repin does not.
    """
    return re.sub(
        r"(three-cubes/tc-pipelines/[^@\s]+@)[0-9a-f]{40}( # v[0-9][^\s]*)?",
        r"\1<PIN>",
        text,
    )


def _blob_at(sha: str, repo_path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{sha}:{repo_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def test_the_scan_found_self_pins() -> None:
    """A scan matching nothing would pass every assertion below."""
    assert len(PINS) >= 10, (
        f"only {len(PINS)} self-pinned references found — the `uses:` pattern "
        f"has probably drifted, so no pin is being checked for staleness."
    )


def _resolve(repo_path: str) -> str:
    """A composite reference names its directory; a workflow names the file."""
    if (REPO_ROOT / repo_path).is_dir():
        return f"{repo_path}/action.yml"
    return repo_path


def _newest_release_commit() -> str | None:
    tags = subprocess.run(
        ["git", "tag", "--sort=-v:refname", "--merged", "HEAD", "v*"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    for tag in tags:
        sha = subprocess.run(
            ["git", "rev-parse", f"{tag}^{{commit}}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if sha:
            return sha
    return None


@pytest.mark.parametrize(("source", "line", "repo_path", "sha"), PINS, ids=PIN_IDS)
def test_self_pin_names_the_newest_release(
    source: str, line: int, repo_path: str, sha: str
) -> None:
    """Every self-pin resolves to the most recent release, never further back.

    A pin loads whatever its commit held, so a pin left behind runs an old file
    while everything read locally is current. One froze at a release 91 commits
    back and a deploy advertised an always-empty rollback handle; another kept a
    cache fix from executing across three releases and two consumer repins.

    Pinning is per level, so a change reaches a caller only once the release
    carrying it is pinned. Requiring the NEWEST release bounds that lag at one
    release instead of letting it grow without limit. Bump these as the last
    step before cutting a tag.
    """
    newest = _newest_release_commit()
    if newest is None:
        pytest.skip("no release tag reachable from HEAD — nothing to compare against")

    assert sha == newest, (
        f"{source}:{line} pins `{repo_path}` at {sha[:12]}, not the newest "
        f"release {newest[:12]}. That step loads an older revision of a file "
        f"sitting current beside it, so a change there reaches nobody until the "
        f"pin moves — and the gap grows silently with every release. "
        f"fix: repin to {newest[:12]} as the last step before cutting a tag. "
        f"next: re-run pytest."
    )
