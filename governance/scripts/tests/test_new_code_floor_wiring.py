"""The new-code coverage floor must run somewhere it can still see the trunk.

The floor scores the lines a branch ADDED, which it resolves as the right side of
`git diff $(git merge-base <trunk> HEAD)...HEAD`. When that merge-base cannot be
computed the engine treats the change set as EMPTY and the check PASSES — the one
outcome that looks identical to well-covered code. So the two steps that make the
diff resolvable are the control: a full-history checkout, and a fetch that creates
the trunk's remote-tracking ref, which `fetch-depth: 0` alone does not.

That makes the floor's lane different in kind from the lane it used to be. As its
own job, a shallow checkout was at least a visible line in the job's own log; run
alongside the coverage combine, the same mistake reads as a green job that merged
some XML. Nothing downstream distinguishes "the changed lines cleared the floor"
from "no changed lines were found", so nothing downstream can be the check.

`test_the_floor_soft_passes_without_the_trunk_ref` is why the assertions below are
not arbitrary: it runs the real engine check over a real repository whose new lines
are entirely uncovered, and shows it reporting PASS once the trunk ref is removed.
Deleting that ref is what a shallow clone leaves behind, so the demonstration and
the wiring assertions describe one failure.

Neither actionlint nor yamllint can see any of this: each judges one file alone,
and every shape here is individually valid YAML.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
GATE = REPO_ROOT / ".github" / "workflows" / "python-quality-gate.yml"

#: The module invocation that IS the floor. Finding it locates the lane. The
#: `-m` is load-bearing: the same dotted path appears in that step's own comment
#: naming the config table, so matching the bare path would keep finding the lane
#: after the line that runs the check was deleted.
FLOOR_INVOCATION = "-m tc_fitness.core_checks.new_code_coverage"

#: Cobertura with no <sources> root, so a class filename reads as a repo-relative
#: path — the shape the changed-line paths are matched against.
COVERAGE_XML_TEMPLATE = """<?xml version="1.0" ?>
<coverage version="7.0">
  <packages>
    <package name="pkg">
      <classes>
        <class filename="pkg/added.py" name="added">
          <lines>
{lines}
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""


def _steps_of_floor_job() -> list[dict]:
    """The steps of the job that invokes the floor, in declaration order."""
    jobs = (yaml.safe_load(GATE.read_text(encoding="utf-8")) or {}).get("jobs") or {}
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        steps = [s for s in (job.get("steps") or []) if isinstance(s, dict)]
        if any(FLOOR_INVOCATION in str(s.get("run", "")) for s in steps):
            return steps
    return []


def _index_of(steps: list[dict], predicate) -> int:
    for i, step in enumerate(steps):
        if predicate(step):
            return i
    return -1


STEPS = _steps_of_floor_job()


def test_the_scan_found_the_lane_that_runs_the_floor() -> None:
    """A scan matching nothing would pass every assertion below vacuously."""
    assert STEPS, (
        f"no job in {GATE.name} runs `{FLOOR_INVOCATION}`, so the assertions "
        f"about how it is wired check nothing. Either the floor was removed — "
        f"in which case the changed-line control is gone — or the invocation "
        f"was renamed and this scan no longer finds it. "
        f"fix: reconcile FLOOR_INVOCATION with the step that runs the check."
    )


def test_the_floor_lane_checks_out_full_history() -> None:
    checkouts = [
        step
        for step in STEPS
        if str(step.get("uses", "")).startswith("actions/checkout@")
    ]
    assert checkouts, (
        f"{GATE.name}: the lane running the floor has no `actions/checkout` "
        f"step, so the diff it scores has no repository to resolve against. "
        f"fix: check the repository out in that lane."
    )
    shallow = [
        step for step in checkouts if str((step.get("with") or {}).get("fetch-depth")) != "0"
    ]
    assert not shallow, (
        f"{GATE.name}: the lane running the floor checks out at "
        f"fetch-depth={[(s.get('with') or {}).get('fetch-depth') for s in shallow]}. "
        f"A shallow clone has no merge-base with the trunk, the engine reads "
        f"that as an empty set of changed lines, and the check PASSES — so the "
        f"floor reports enforced while an uncovered new line merges. "
        f"fix: set `fetch-depth: 0` on that lane's checkout."
    )


def test_the_trunk_ref_is_fetched_before_the_floor_runs() -> None:
    """`fetch-depth: 0` fetches the checked-out ref's history, not the trunk's name."""
    floor = _index_of(STEPS, lambda s: FLOOR_INVOCATION in str(s.get("run", "")))
    fetch = _index_of(
        STEPS,
        lambda s: "git fetch" in str(s.get("run", ""))
        and "new-code-base-ref" in str(s.get("env", "")),
    )
    assert fetch != -1, (
        f"{GATE.name}: nothing in the floor's lane fetches `new-code-base-ref`. "
        f"A full-history checkout populates the checked-out ref only, so "
        f"`origin/<trunk>` does not exist and `git merge-base` fails — which "
        f"the check reports as PASS. "
        f"fix: fetch the base ref into refs/remotes/origin/<trunk> in that lane."
    )
    assert fetch < floor, (
        f"{GATE.name}: the base-ref fetch (step {fetch}) runs AFTER the floor "
        f"(step {floor}), so the merge-base is still unresolvable when the "
        f"check reads it and the pass it reports means nothing. "
        f"fix: order the fetch before the floor step."
    )


def test_the_floor_runs_after_the_report_it_scores() -> None:
    """Scoring a report that a later step writes scores the previous run's file, or none."""
    floor = _index_of(STEPS, lambda s: FLOOR_INVOCATION in str(s.get("run", "")))
    writers = [
        i
        for i, step in enumerate(STEPS)
        if str(step.get("uses", "")).startswith("actions/download-artifact@")
        or "coverage combine" in str(step.get("run", ""))
        or "coverage-combine-post" in str(step.get("if", ""))
    ]
    assert writers, (
        f"{GATE.name}: the floor's lane neither downloads nor combines a "
        f"coverage report, so the file it scores arrives from nowhere. "
        f"fix: produce the coverage XML in that lane before the floor step."
    )
    assert max(writers) < floor, (
        f"{GATE.name}: a step that produces or rewrites the coverage report "
        f"(step {max(writers)}) runs AFTER the floor (step {floor}). The floor "
        f"would score a stale or absent report — and an absent one it cannot "
        f"score at all. "
        f"fix: order every report-producing step before the floor step."
    )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture
def repo_with_uncovered_new_code(tmp_path: Path) -> Path:
    """A repo whose branch adds a wholly uncovered file, with a trunk ref present."""
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    _git(repo.parent, "init", "--quiet", repo.name)
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")

    (repo / "pkg" / "kept.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "trunk")
    # The remote-tracking ref a real checkout's fetch creates. Its ABSENCE is
    # what a shallow clone leaves, and what the second test removes.
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    added = "def added():\n    a = 1\n    b = 2\n    return a + b\n"
    (repo / "pkg" / "added.py").write_text(added, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "add uncovered code")

    lines = "\n".join(
        f'            <line number="{n}" hits="0"/>' for n in range(1, added.count("\n") + 1)
    )
    (repo / "coverage.xml").write_text(
        COVERAGE_XML_TEMPLATE.format(lines=lines), encoding="utf-8"
    )
    return repo


def _floor_verdict(repo: Path) -> int:
    from tc_fitness.core_checks.new_code_coverage import build

    return build(
        {
            "name": "new-code-coverage",
            "roots": ["pkg"],
            "extensions": [".py"],
            "floor_pct": 80.0,
            "coverage_report": "coverage.xml",
            "base_ref": "origin/main",
        },
        repo_root=repo,
    ).run()


def test_the_floor_fails_on_uncovered_new_code(repo_with_uncovered_new_code: Path) -> None:
    """The control, working: every added line reports zero hits, so the floor bites."""
    assert _floor_verdict(repo_with_uncovered_new_code) == 1, (
        "the engine's new_code_coverage check PASSED a file whose every added "
        "line is recorded with hits=0. Either the check no longer enforces the "
        "floor or this fixture no longer presents new code to it, and the "
        "assertions above are pinning wiring around a check that does nothing. "
        "fix: reconcile the fixture with the engine's coverage-report and "
        "changed-line handling."
    )


def test_the_floor_soft_passes_without_the_trunk_ref(
    repo_with_uncovered_new_code: Path,
) -> None:
    """The defect the wiring exists to prevent, reproduced.

    Same repository, same uncovered lines, same report — only the trunk ref is
    gone, which is exactly what a shallow checkout leaves behind. The check now
    reports PASS, and no signal anywhere distinguishes that from real coverage.
    """
    _git(repo_with_uncovered_new_code, "update-ref", "-d", "refs/remotes/origin/main")
    assert _floor_verdict(repo_with_uncovered_new_code) == 0, (
        "the engine now FAILS when the trunk ref is missing, so an unresolvable "
        "merge-base is no longer silent. That is a stronger guarantee than the "
        "wiring assertions above assume. "
        "fix: re-read the engine's _changed_lines soft-pass paths and simplify "
        "this file's assertions to match."
    )
