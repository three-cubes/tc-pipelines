"""A reusable workflow nothing calls has a contract nothing type-checks.

Neither actionlint nor GitHub's reusable-workflow resolver reads a
`workflow_call:` block on its own. Both resolve it only where some caller's
`uses:` names it, so `meta-quality-gate.yml`'s actionlint leg proves nothing
about a reusable no file in this tree calls. Renaming an input, promoting an
optional input to required, or renaming a secret leaves every file individually
valid and every gate green.

The break then lands in a consumer, as `startup_failure` — GitHub rejects the
run before any job starts, so there is no step, no log and no annotation, only a
red workflow with an empty run page. Consumers SHA-pin, so the break is deferred
to whichever repin first picks the changed contract up, by which point the
change that caused it is many commits back.

The convention that closes this is one `example-<reusable>.yml` per reusable,
every job gated on a `run-for-real` input defaulting false, so the call shape is
resolved at parse time while the body never executes.

A reusable deliberately left without a caller is declared in NO_EXAMPLE_CALLER
with its reason, so intent stays distinguishable from drift.

Whether the dispatcher also fans a given example out is deliberately NOT asserted
here: `example-callers.yml` documents that fan-out job as optional, because the
per-file static check does not depend on it and a mandatory edit to one shared
file re-serialises parallel work. Only a fan-out job pointing at a file that is
not on disk is checked, since that fails the whole dispatch rather than one job.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

DISPATCHER = "example-callers.yml"
EXAMPLE_PREFIX = "example-"

# Only a `./`-rooted path resolves against the file in THIS tree. A
# `three-cubes/tc-pipelines/...@<sha>` self-reference resolves against the
# contract at that pinned sha, not the working tree, so it validates nothing
# about the current file and is deliberately not counted as a caller.
LOCAL_REUSABLE = re.compile(r"^\./\.github/workflows/(.+\.yml)$")

# reusable filename -> why it deliberately carries no in-repo caller.
# A reusable already called by a real workflow in this tree needs no entry:
# that call resolves its contract and the coverage assertion sees it. An entry
# belongs here only when even a `run-for-real`-gated example would misrepresent
# the reusable — not to park a reusable whose example has yet to be written.
NO_EXAMPLE_CALLER: dict[str, str] = {}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _trigger_names(document: dict) -> set[str]:
    # `on:` parses as the boolean True under YAML 1.1, and accepts a mapping, a
    # list or a bare string.
    triggers = document.get(True)
    if triggers is None:
        triggers = document.get("on")
    if isinstance(triggers, dict):
        return set(triggers)
    if isinstance(triggers, list):
        return {str(name) for name in triggers}
    return {str(triggers)} if triggers else set()


def _reusables() -> list[str]:
    """Shipped reusables: `workflow_call` workflows that are not themselves examples."""
    return sorted(
        path.name
        for path in WORKFLOW_DIR.glob("*.yml")
        if not path.name.startswith(EXAMPLE_PREFIX)
        and "workflow_call" in _trigger_names(_load(path))
    )


def _examples() -> list[str]:
    return sorted(
        path.name
        for path in WORKFLOW_DIR.glob(f"{EXAMPLE_PREFIX}*.yml")
        if path.name != DISPATCHER
    )


def _local_calls() -> list[tuple[str, str, str]]:
    """(source workflow, job name, called workflow filename)."""
    found = []
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        for job_name, job in (_load(path).get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            match = LOCAL_REUSABLE.match(str(job.get("uses", "")))
            if match and match.group(1) != path.name:
                found.append((path.name, job_name, match.group(1)))
    return found


REUSABLES = _reusables()
EXAMPLES = _examples()
CALLS = _local_calls()
FAN_OUT = [(job, target) for source, job, target in CALLS if source == DISPATCHER]


def test_the_scan_found_reusables_examples_and_fan_out() -> None:
    """A scan that silently matches nothing would pass every assertion below."""
    assert len(REUSABLES) >= 15, (
        f"only {len(REUSABLES)} shipped reusables discovered — the `on:` read "
        f"has probably drifted, so coverage is no longer being checked."
    )
    assert len(EXAMPLES) >= 10, (
        f"only {len(EXAMPLES)} example files discovered — the "
        f"`{EXAMPLE_PREFIX}*.yml` glob has probably drifted, so the example "
        f"assertions no longer see anything to check."
    )
    assert len(FAN_OUT) >= 10, (
        f"only {len(FAN_OUT)} fan-out jobs discovered in {DISPATCHER} — the "
        f"`uses:` pattern has probably drifted, so neither the coverage nor the "
        f"dangling-target assertion sees anything to check."
    )


@pytest.mark.parametrize("reusable", REUSABLES, ids=REUSABLES)
def test_every_reusable_is_called_from_inside_this_repo(reusable: str) -> None:
    callers = sorted({source for source, _, target in CALLS if target == reusable})
    stem = reusable.removesuffix(".yml")

    if reusable in NO_EXAMPLE_CALLER:
        assert not callers, (
            f"{reusable} is listed in NO_EXAMPLE_CALLER but is now called from "
            f"{callers}. fix: drop it from NO_EXAMPLE_CALLER so the coverage "
            f"assertion covers it."
        )
        return

    assert callers, (
        f"nothing in this repo `uses:` {reusable}, so neither actionlint nor "
        f"GitHub's reusable-workflow resolver ever parses a call against its "
        f"`workflow_call:` contract. A renamed input, an optional input "
        f"promoted to required, or a renamed secret ships green from here and "
        f"breaks in a consumer as `startup_failure` — no job, no log, no "
        f"annotation. "
        f"fix: add .github/workflows/{EXAMPLE_PREFIX}{stem}.yml passing every "
        f"required input and secret, with every job gated on "
        f"`if: ${{{{ inputs.run-for-real }}}}` so the shape is resolved but the "
        f"body never runs; or declare the omission in NO_EXAMPLE_CALLER with "
        f"the reason an example would misrepresent the reusable."
    )


@pytest.mark.parametrize("example", EXAMPLES, ids=EXAMPLES)
def test_every_example_exercises_a_shipped_reusable(example: str) -> None:
    called = sorted({target for source, _, target in CALLS if source == example})
    exercised = [name for name in called if name in REUSABLES]
    assert exercised, (
        f"{example} calls {called or 'no local reusable'}, none of which is a "
        f"shipped reusable, so the file resolves no `workflow_call:` contract "
        f"and its name claims coverage nothing delivers. fix: point at least "
        f"one job at `uses: ./.github/workflows/<reusable>.yml`, or delete the "
        f"file with the reusable it was written for."
    )

    named_after = example.removeprefix(EXAMPLE_PREFIX)
    # A file whose derived name is not a shipped reusable is a second example
    # for one reusable, free to carry its own name; the assertion above already
    # proved it resolves a real contract.
    if named_after not in REUSABLES:
        return

    assert named_after in called, (
        f"{example} exercises {exercised}, not {named_after}, which its name "
        f"claims. {named_after} is left resting on whatever other caller it "
        f"has, and a reader auditing coverage by filename is misled. "
        f"fix: point at least one job at "
        f"`uses: ./.github/workflows/{named_after}`, or rename the file so it "
        f"no longer derives the name of a shipped reusable."
    )


@pytest.mark.parametrize(
    ("job", "target"),
    FAN_OUT,
    ids=[f"{job} -> {target}" for job, target in FAN_OUT],
)
def test_every_fan_out_target_exists_on_disk(job: str, target: str) -> None:
    assert (WORKFLOW_DIR / target).exists(), (
        f"{DISPATCHER}: job `{job}` targets {target}, which is not on disk. "
        f"GitHub rejects the whole dispatch as `startup_failure` before any job "
        f"starts, so every OTHER example stops running too. "
        f"fix: restore {target}, or delete the `{job}` fan-out job."
    )


def test_every_declared_exception_names_a_real_uncalled_reusable() -> None:
    """A stale exemption would silently drop a reusable from the coverage set."""
    unknown = sorted(set(NO_EXAMPLE_CALLER) - set(REUSABLES))
    assert not unknown, (
        f"NO_EXAMPLE_CALLER names files that are no longer shipped reusables: "
        f"{unknown}. fix: remove them, or the exemption outlives the file it "
        f"explains."
    )

    unexplained = sorted(
        name for name, reason in NO_EXAMPLE_CALLER.items() if not reason.strip()
    )
    assert not unexplained, (
        f"NO_EXAMPLE_CALLER entries {unexplained} carry no reason, so a later "
        f"reader cannot tell a decision from an oversight. fix: state why an "
        f"example caller would misrepresent the reusable."
    )
