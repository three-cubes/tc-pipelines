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

The rule: a self-pin is an immutable ancestor of HEAD and its complete recursive
target graph has the same content as the working tree. Pin SHA differences in a
target file are normalised for that file's comparison, then every nested target
is resolved at the pinned coordinate and checked recursively. This permits an
unchanged older target while rejecting a stale transitive dependency.

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
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
SEARCH_DIRS = (".github/workflows", "actions", ".github/actions")

SELF_PIN = re.compile(
    r"three-cubes/tc-pipelines/(?P<path>[^@\s]+)@(?P<sha>[0-9a-f]{40})"
)

def _source_files() -> list[Path]:
    found: list[Path] = []
    for directory in SEARCH_DIRS:
        base = REPO_ROOT / directory
        if not base.is_dir():
            continue
        found.extend(sorted(base.rglob("*.yml")))
    return found


def _self_pin_nodes(text: str) -> list[tuple[int, str, str]]:
    """Return structural self-pin uses with their source line."""
    root = yaml.compose(text, Loader=yaml.SafeLoader)
    found: list[tuple[int, str, str]] = []

    def walk(node: yaml.Node) -> None:
        if isinstance(node, yaml.SequenceNode):
            for item in node.value:
                walk(item)
            return
        if not isinstance(node, yaml.MappingNode):
            return
        for key, value in node.value:
            if getattr(key, "value", None) == "uses" and isinstance(value, yaml.ScalarNode):
                match = SELF_PIN.fullmatch(value.value)
                if match:
                    found.append(
                        (key.start_mark.line + 1, match.group("path"), match.group("sha"))
                    )
            walk(value)

    if root is not None:
        walk(root)
    return found


def _self_pins() -> list[tuple[str, int, str, str]]:
    """(source file, line, referenced repo path, pinned sha)."""
    pins = []
    for path in _source_files():
        for number, repo_path, sha in _self_pin_nodes(path.read_text(encoding="utf-8")):
            pins.append((str(path.relative_to(REPO_ROOT)), number, repo_path, sha))
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
        r"(three-cubes/tc-pipelines/[^@\s]+@)[0-9a-f]{40}(?:\s*#.*)?",
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


def _is_ancestor(older: str, newer: str) -> bool:
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", older, newer],
            cwd=REPO_ROOT,
            check=False,
        ).returncode
        == 0
    )


def _assert_target_graph_matches_current(
    repo_path: str, sha: str, *, seen: set[tuple[str, str]]
) -> None:
    coordinate = (repo_path, sha)
    if coordinate in seen:
        return
    seen.add(coordinate)

    target = _resolve(repo_path)
    pinned = _blob_at(sha, target)
    assert pinned is not None, f"{target} does not exist at self-pin {sha[:12]}"
    current = (REPO_ROOT / target).read_text(encoding="utf-8")
    assert _without_pin_shas(pinned) == _without_pin_shas(current), (
        f"{target} at {sha[:12]} differs from its reviewed current content"
    )
    for _, nested_path, nested_sha in _self_pin_nodes(pinned):
        _assert_target_graph_matches_current(nested_path, nested_sha, seen=seen)


@pytest.mark.parametrize(("source", "line", "repo_path", "sha"), PINS, ids=PIN_IDS)
def test_self_pin_is_current_and_immutable(
    source: str, line: int, repo_path: str, sha: str
) -> None:
    """The pin is reachable and recursively equivalent to its local target."""
    head = _rev("HEAD")
    assert _is_ancestor(sha, head), (
        f"{source}:{line} pins `{repo_path}` at {sha[:12]}, which is not an "
        "ancestor of HEAD. Self-pins must name reviewed repository history."
    )

    try:
        _assert_target_graph_matches_current(repo_path, sha, seen=set())
    except AssertionError as error:
        raise AssertionError(
            f"{source}:{line} executes a stale target graph from {sha[:12]}: {error}. "
            "Commit each dependency before pinning its caller."
        ) from error
