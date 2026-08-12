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


@pytest.mark.parametrize(("source", "line", "repo_path", "sha"), PINS, ids=PIN_IDS)
def test_the_revision_a_pin_loads_has_current_pins_of_its_own(
    source: str, line: int, repo_path: str, sha: str
) -> None:
    """Follow one hop: the revision a pin loads must not carry stale pins itself.

    Normalising pin SHAs keeps a repin from reading as a change, but it also
    hides the case that matters most in a nested chain: a workflow pinning a
    composite at a revision whose OWN pin is old. The outer content compares
    equal while the step three levels down loads something years behind.

    That shipped twice. A cache fix landed in `setup-uv-cached`, the consuming
    workflow was repinned, and it still ran the pre-fix action — because the
    composite revision in between pointed at the older one, and every check
    comparing normalised content saw no difference.
    """
    pinned = _blob_at(sha, _resolve(repo_path))
    if pinned is None:
        pytest.skip(f"commit {sha[:12]} unreadable — run with fetch-depth: 0")

    stale = []
    for nested in SELF_PIN.finditer(pinned):
        nested_path, nested_sha = nested.group("path"), nested.group("sha")
        nested_local = REPO_ROOT / _resolve(nested_path)
        if not nested_local.is_file():
            continue
        nested_pinned = _blob_at(nested_sha, _resolve(nested_path))
        if nested_pinned is None:
            continue
        if _without_pin_shas(nested_pinned) != _without_pin_shas(
            nested_local.read_text(encoding="utf-8")
        ):
            stale.append(f"{nested_path}@{nested_sha[:12]}")

    assert not stale, (
        f"{source}:{line} pins `{repo_path}` at {sha[:12]}, and THAT revision "
        f"pins {stale} at revisions whose content is no longer current. The "
        f"outer pin looks fresh while the step it loads reaches an old file — "
        f"a fix in that file reaches nobody. "
        f"fix: repin `{repo_path}` to a revision whose own pins are current, "
        f"normally the most recent release. next: re-run pytest."
    )


@pytest.mark.parametrize(("source", "line", "repo_path", "sha"), PINS, ids=PIN_IDS)
def test_self_pin_loads_the_file_this_repo_ships(
    source: str, line: int, repo_path: str, sha: str
) -> None:
    # A composite reference names the directory holding `action.yml`; a reusable
    # workflow reference names the file itself.
    local = REPO_ROOT / repo_path
    if local.is_dir():
        repo_path = f"{repo_path}/action.yml"
        local = REPO_ROOT / repo_path
    if not local.is_file():
        pytest.fail(
            f"{source}:{line} pins `{repo_path}`, which does not exist in this "
            f"tree. fix: correct the path, or drop the reference."
        )

    pinned = _blob_at(sha, repo_path)
    if pinned is None:
        pytest.skip(
            f"commit {sha[:12]} is not readable — a shallow clone cannot compare "
            f"the pinned revision. Run with fetch-depth: 0."
        )

    if repo_path in PINNED_BEHIND_BY_DESIGN:
        assert _without_pin_shas(pinned) != _without_pin_shas(
            local.read_text(encoding="utf-8")
        ), (
            f"{repo_path} is listed in PINNED_BEHIND_BY_DESIGN but now matches "
            f"its pin. fix: remove the entry so the staleness assertion covers it."
        )
        return

    assert _without_pin_shas(pinned) == _without_pin_shas(
        local.read_text(encoding="utf-8")
    ), (
        f"{source}:{line} pins `{repo_path}` at {sha[:12]}, whose copy differs "
        f"from the one in this tree. That step runs the OLD revision while every "
        f"reviewer and every other check reads the new one — a change to "
        f"`{repo_path}` reaches nobody until this pin moves. "
        f"fix: repin to a release SHA whose copy matches, normally the most "
        f"recent tag; or add `{repo_path}` to PINNED_BEHIND_BY_DESIGN with the "
        f"reason the older revision is wanted. next: re-run pytest."
    )
