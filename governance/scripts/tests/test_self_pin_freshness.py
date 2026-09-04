"""Every self-pinned `uses:` must execute the current target content.

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

The rule: a self-pin is an immutable ancestor of HEAD, is not older than the
newest release, and contains the same target content as the working tree. Pin
SHA differences inside that target are normalised because updating a pin changes
the commit hash. This permits a reviewed post-release commit to carry an action
fix immediately, without mutable refs or a two-release bootstrap cycle.

There is no way to name the SHA once and reuse it: `uses:` accepts no context of
any kind, in a reusable call or an action step. So this test, rather than a
variable, is what holds the set consistent, and the repetition it polices is the
platform's floor rather than a design choice. The architecture, and what a
consumer repin touches, are in `governance/standards/supply-chain-pinning.md`.

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


def _rev(ref: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", f"{ref}^{{commit}}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()


def _newest_release_commit() -> str | None:
    """Newest release BEFORE HEAD.

    A tag cut at HEAD is skipped. No commit can pin to its own SHA — writing the
    pin changes the hash — so treating the tag being cut as the target would
    fail on the release commit itself and on every commit after it until a
    separate repin landed, which is the flow this rule is meant to support.
    """
    head = _rev("HEAD")
    tags = subprocess.run(
        ["git", "tag", "--sort=-v:refname", "--merged", "HEAD", "v*"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    for tag in tags:
        sha = _rev(tag)
        if sha and sha != head:
            return sha
    return None


def _is_ancestor(older: str, newer: str) -> bool:
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", older, newer],
            cwd=REPO_ROOT,
            check=False,
        ).returncode
        == 0
    )


@pytest.mark.parametrize(("source", "line", "repo_path", "sha"), PINS, ids=PIN_IDS)
def test_self_pin_is_current_and_immutable(
    source: str, line: int, repo_path: str, sha: str
) -> None:
    """The pin is recent, reachable, and byte-equivalent to its local target."""
    newest = _newest_release_commit()
    if newest is None:
        pytest.skip("no release tag reachable from HEAD — nothing to compare against")

    head = _rev("HEAD")
    assert _is_ancestor(newest, sha), (
        f"{source}:{line} pins `{repo_path}` at {sha[:12]}, older than newest "
        f"release {newest[:12]}. Repin it to the reviewed commit containing "
        "the current target."
    )
    assert _is_ancestor(sha, head), (
        f"{source}:{line} pins `{repo_path}` at {sha[:12]}, which is not an "
        "ancestor of HEAD. Self-pins must name reviewed repository history."
    )

    target = _resolve(repo_path)
    pinned = _blob_at(sha, target)
    assert pinned is not None, (
        f"{source}:{line} pins `{target}` at {sha[:12]}, but that target does "
        "not exist in the pinned commit."
    )
    current = (REPO_ROOT / target).read_text(encoding="utf-8")
    assert _without_pin_shas(pinned) == _without_pin_shas(current), (
        f"{source}:{line} executes stale `{target}` content from {sha[:12]}. "
        "Commit the target, then repin this caller to that immutable commit."
    )
