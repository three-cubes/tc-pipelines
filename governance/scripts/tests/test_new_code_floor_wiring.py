"""The new-code coverage floor must run with resolvable trunk evidence.

The floor scores the lines a branch added against its merge base with trunk. The
workflow therefore provides full history and the trunk remote-tracking ref. The
engine also fails closed when that ref cannot be resolved, so missing comparison
evidence cannot look like successfully covered code.

Neither actionlint nor yamllint can see any of this: each judges one file alone,
and every shape here is individually valid YAML.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
GATE = WORKFLOW_DIR / "python-quality-gate.yml"

#: The configured engine invocation that IS the floor. Finding it locates the
#: lane and proves the consumer's check configuration is loaded.
FLOOR_INVOCATION = "uv run python -m tc_fitness.core_checks.new_code_coverage"
FLOOR_PREFLIGHT = """from pathlib import Path
from tc_fitness.gate_config import load_core_check_configs

floor = load_core_check_configs(Path.cwd()).get("new_code_coverage", {}).get("floor_pct")
if isinstance(floor, bool) or floor != 100:
    raise SystemExit(f"new_code_coverage.floor_pct must be 100 for the reusable CI backstop (found {floor!r})")
print("new_code_coverage.floor_pct is 100")"""

#: The reusable's `coverage-artifact-name` default — what every caller that names
#: none silently takes.
DEFAULT_COVERAGE_ARTIFACT = "coverage-data"

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


def test_the_floor_uses_the_backwards_compatible_public_entrypoint() -> None:
    """The floor must work across supported consumer engine versions."""
    floor = next(step for step in STEPS if FLOOR_INVOCATION in str(step.get("run", "")))
    body = str(floor.get("run", ""))
    assert "tc-fitness run --gate new_code_coverage" not in body


def test_the_floor_lane_checks_out_full_history() -> None:
    checkouts = [step for step in STEPS if str(step.get("uses", "")).startswith("actions/checkout@")]
    assert checkouts, (
        f"{GATE.name}: the lane running the floor has no `actions/checkout` "
        f"step, so the diff it scores has no repository to resolve against. "
        f"fix: check the repository out in that lane."
    )
    shallow = [step for step in checkouts if str((step.get("with") or {}).get("fetch-depth")) != "0"]
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
        lambda s: "git fetch" in str(s.get("run", "")) and "new-code-base-ref" in str(s.get("env", "")),
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


def test_the_trunk_fetch_is_fail_closed() -> None:
    """A missing base ref must fail the lane, never turn into a soft pass."""
    fetch = next(
        step
        for step in STEPS
        if "git fetch" in str(step.get("run", "")) and "new-code-base-ref" in str(step.get("env", ""))
    )
    body = str(fetch.get("run", ""))
    assert "||" not in body, (
        f"{GATE.name}: base-ref fetch failure is still tolerated with `||`; "
        "an unresolved merge-base makes the engine see no changed lines and "
        "therefore cannot be allowed to continue."
    )
    assert "set -e" in body or "exit 1" in body, f"{GATE.name}: base-ref fetch step has no failing exit path."


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


def test_coverage_artifact_download_is_fail_closed() -> None:
    """A missing report must fail the job instead of being swallowed."""
    downloads = [step for step in STEPS if str(step.get("uses", "")).startswith("actions/download-artifact@")]
    assert downloads, f"{GATE.name}: floor lane has no coverage artifact download."
    assert all(not step.get("continue-on-error") for step in downloads), (
        f"{GATE.name}: coverage artifact download uses continue-on-error; a missing report must fail closed."
    )


def test_coverage_assembly_does_not_warn_and_continue() -> None:
    """Missing or unmergeable coverage data must be a hard failure."""
    combine = next(step for step in STEPS if "coverage combine" in str(step.get("run", "")))
    body = str(combine.get("run", ""))
    assert "set -euo pipefail" in body
    assert "::warning::" not in body
    assert "|| echo" not in body


def test_failed_quality_lane_cannot_skip_the_floor() -> None:
    """A failed producer lane must fail the floor job, not exit successfully."""
    floor = next(step for step in STEPS if "Enforce the new-code coverage floor" == step.get("name"))
    body = str(floor.get("run", ""))
    assert "::warning::new-code coverage floor not run" not in body
    assert "exit 1" in body


def test_new_code_floor_contract_is_one_hundred_percent() -> None:
    """The org policy and reusable must require 100% before scoring coverage."""
    document = yaml.safe_load(GATE.read_text(encoding="utf-8")) or {}
    triggers = document.get("on", document.get(True)) or {}
    floor = (triggers.get("workflow_call") or {}).get("inputs", {}).get("enforce-new-code-coverage") or {}
    description = str(floor.get("description", ""))
    assert "100%" in description
    assert "80%" not in description
    ruleset = (REPO_ROOT / "governance" / "CANONICAL-ORG-RULESET.md").read_text(encoding="utf-8")
    assert "| 100% coverage floor on changed lines |" in ruleset
    assert "| 80% coverage floor on changed lines |" not in ruleset
    floor_step = next(step for step in STEPS if FLOOR_INVOCATION in str(step.get("run", "")))
    body = str(floor_step.get("run", ""))
    assert "tc_fitness.gate_config import load_core_check_configs" in body
    assert "governance/scripts/" not in body
    assert "python -c" in body
    assert FLOOR_PREFLIGHT in body
    assert body.index("python -c") < body.index(FLOOR_INVOCATION)


def test_routed_floor_fixture_configures_the_required_floor() -> None:
    """The routed floor self-test must supply the same contract as the org policy."""
    fixture = REPO_ROOT / ".github" / "selftest-fixture" / "floor.tc-fitness.toml"
    document = tomllib.loads(fixture.read_text(encoding="utf-8"))
    floor = document["core_checks"]["new_code_coverage"]
    assert floor["floor_pct"] == 100
    assert floor["coverage_report"] == "coverage.xml"

    routing = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "test-shard-routing.yml").read_text(encoding="utf-8")
    )
    floor_caller = routing["jobs"]["floor"]["with"]
    assert "floor.tc-fitness.toml .tc-fitness.toml" in floor_caller["coverage-combine-post"]


def test_shard_fixture_records_real_coverage_data() -> None:
    """The combine self-test must upload measured data, not empty marker files."""
    fixture = REPO_ROOT / ".github" / "selftest-fixture" / ".tc-fitness.toml"
    document = tomllib.loads(fixture.read_text(encoding="utf-8"))
    assert document["steps"][0]["run"][:4] == ["python3", "-m", "coverage", "run"]


def test_floor_lane_rejects_a_consumer_configured_below_one_hundred_percent(
    tmp_path: Path,
) -> None:
    """The hosted backstop must reject 80% before the configured gate can pass."""
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "pyproject.toml").write_text(
        '[tool.tc_fitness.core_checks.new_code_coverage]\nroots = ["src"]\nfloor_pct = 80\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-c", FLOOR_PREFLIGHT],
        cwd=consumer,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1 and "floor_pct must be 100" in result.stderr, (
        "the CI preflight accepted a consumer floor_pct=80, so the advertised "
        "100% changed-line backstop can pass at 80%"
    )


def test_floor_lane_accepts_a_consumer_configured_at_one_hundred_percent(
    tmp_path: Path,
) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "pyproject.toml").write_text(
        '[tool.tc_fitness.core_checks.new_code_coverage]\nroots = ["src"]\nfloor_pct = 100\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-c", FLOOR_PREFLIGHT],
        cwd=consumer,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_standalone_fitness_config_overrides_pyproject_floor(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "pyproject.toml").write_text(
        '[tool.tc_fitness.core_checks.new_code_coverage]\nroots = ["src"]\nfloor_pct = 100\n',
        encoding="utf-8",
    )
    (consumer / ".tc-fitness.toml").write_text(
        '[core_checks.new_code_coverage]\nroots = ["src"]\nfloor_pct = 80\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-c", FLOOR_PREFLIGHT],
        cwd=consumer,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "found 80" in result.stderr


def test_coverage_combine_post_hook_is_blocking() -> None:
    """A failed report transform must fail the coverage lane that scores it."""
    job_steps = [
        step
        for job in ((yaml.safe_load(GATE.read_text(encoding="utf-8")) or {}).get("jobs") or {}).values()
        if isinstance(job, dict)
        for step in (job.get("steps") or [])
        if isinstance(step, dict) and "coverage-combine-post" in str(step.get("if", ""))
    ]
    assert job_steps, "the workflow no longer exposes its coverage-combine-post hook"
    assert all(not step.get("continue-on-error") for step in job_steps)
    assert all("|| true" not in str(step.get("run", "")) for step in job_steps)
    assert all("set -euo pipefail" in str(step.get("run", "")) for step in job_steps)
    assert all("pytest-shards > 1" not in str(step.get("if", "")) for step in job_steps)


def _uploading_gate_callers(path: Path) -> list[tuple[str, dict, str]]:
    """(job id, job, artifact name) for each gate caller in `path` that uploads.

    Both defaults are load-bearing and both point the same way — toward a caller
    that says nothing still uploading, under the one name every other silent
    caller also takes. Reading an omitted input as "off" would make this scan
    skip exactly the callers most likely to collide.
    """
    jobs = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("jobs") or {}
    found = []
    for job_id, job in jobs.items():
        if not isinstance(job, dict) or "python-quality-gate.yml" not in str(job.get("uses", "")):
            continue
        params = job.get("with") or {}
        # `upload-coverage-artifact` defaults to true, so only an explicit false
        # opts out. Compared as text because YAML yields a bool and a caller may
        # quote it.
        if str(params.get("upload-coverage-artifact", True)).strip().lower() == "false":
            continue
        found.append(
            (
                job_id,
                job,
                str(params.get("coverage-artifact-name", DEFAULT_COVERAGE_ARTIFACT)),
            )
        )
    return found


def test_the_assumed_input_defaults_match_the_reusable() -> None:
    """The scan above reads an omitted input as the reusable's default.

    Both defaults live in another file. Flip `upload-coverage-artifact` to false
    there and every silent caller stops being scanned; change the artifact name
    and colliding callers start reading as distinct. Either way the guard goes
    quiet rather than wrong, which is the failure it cannot report on itself.
    """
    document = yaml.safe_load(GATE.read_text(encoding="utf-8")) or {}
    # `on:` is YAML 1.1 truthy, so safe_load keys it as the boolean True.
    triggers = document.get("on", document.get(True)) or {}
    inputs = (triggers.get("workflow_call") or {}).get("inputs") or {}
    assert inputs.get("upload-coverage-artifact", {}).get("default") is True, (
        f"{GATE.name}: `upload-coverage-artifact` no longer defaults to true, so "
        f"a caller that omits it no longer uploads — and the collision scan, "
        f"which treats omission as uploading, now flags callers that cannot "
        f"collide. fix: reconcile _uploading_gate_callers with the new default."
    )
    assert inputs.get("coverage-artifact-name", {}).get("default") == DEFAULT_COVERAGE_ARTIFACT, (
        f"{GATE.name}: `coverage-artifact-name` defaults to "
        f"{inputs.get('coverage-artifact-name', {}).get('default')!r}, not "
        f"{DEFAULT_COVERAGE_ARTIFACT!r}. Callers that name none take the real "
        f"default, so the scan would compare them under a name nothing uses and "
        f"read a live collision as two distinct names. "
        f"fix: update DEFAULT_COVERAGE_ARTIFACT."
    )


def test_concurrent_gate_callers_do_not_share_a_coverage_artifact_name() -> None:
    """The floor fetches its report BY NAME, and names are scoped to the run.

    Two callers of the gate in one workflow both uploading coverage take the same
    name. The second upload is a non-retryable 409, and — worse, because it is
    quiet — a download by that name can resolve to the other caller's report, so
    the floor scores a change set that is not the one it is gating.
    """
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        uploaders: dict[str, list[str]] = {}
        for job_id, _job, name in _uploading_gate_callers(path):
            uploaders.setdefault(name, []).append(job_id)
        shared = {name: ids for name, ids in uploaders.items() if len(ids) > 1}
        assert not shared, (
            f"{path.name}: callers {shared} run in one workflow and upload coverage "
            f"under the same artifact name. The second upload 409s, and a download "
            f"by that name can return the other caller's report. "
            f"fix: give each uploading caller its own `coverage-artifact-name`."
        )


def test_a_matrix_gate_caller_varies_its_coverage_artifact_name() -> None:
    """One matrix caller is many jobs in one run, all uploading the same name.

    A `strategy.matrix` on a `uses:` job fans it into a cell per combination, and
    every cell runs in the SAME workflow — so a fixed artifact name collides with
    itself. Counting job ids cannot see it: the caller is declared once, so the
    scan above reads one uploader and passes while the run 409s.
    """
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        fixed = [
            job_id
            for job_id, job, name in _uploading_gate_callers(path)
            if (job.get("strategy") or {}).get("matrix") and "matrix." not in name
        ]
        assert not fixed, (
            f"{path.name}: matrix caller(s) {fixed} upload coverage under a name "
            f"that does not vary per cell, so every cell of one run takes the same "
            f"artifact name and all but the first 409. "
            f"fix: interpolate a matrix value into `coverage-artifact-name`, or "
            f"drop the matrix from the uploading caller."
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

    lines = "\n".join(f'            <line number="{n}" hits="0"/>' for n in range(1, added.count("\n") + 1))
    (repo / "coverage.xml").write_text(COVERAGE_XML_TEMPLATE.format(lines=lines), encoding="utf-8")
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


def test_the_floor_fails_on_uncovered_new_code(
    repo_with_uncovered_new_code: Path,
) -> None:
    """The control, working: every added line reports zero hits, so the floor bites."""
    assert _floor_verdict(repo_with_uncovered_new_code) == 1, (
        "the engine's new_code_coverage check PASSED a file whose every added "
        "line is recorded with hits=0. Either the check no longer enforces the "
        "floor or this fixture no longer presents new code to it, and the "
        "assertions above are pinning wiring around a check that does nothing. "
        "fix: reconcile the fixture with the engine's coverage-report and "
        "changed-line handling."
    )


def test_the_floor_fails_closed_without_the_trunk_ref(
    repo_with_uncovered_new_code: Path,
) -> None:
    """Missing comparison evidence must not produce a false green result."""
    _git(repo_with_uncovered_new_code, "update-ref", "-d", "refs/remotes/origin/main")
    assert _floor_verdict(repo_with_uncovered_new_code) == 1, (
        "the engine passed without a resolvable trunk ref; missing comparison "
        "evidence must fail closed rather than masquerade as fully covered code"
    )
