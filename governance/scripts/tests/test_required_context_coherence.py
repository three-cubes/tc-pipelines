"""A required status check must exist, and must not be able to pass unrun.

Branch protection scores a SKIPPED check-run as satisfied. Two relationships
between files decide whether the gates a ruleset names are real, and neither is
visible to actionlint or yamllint, which judge one file alone and know nothing
of the rulesets, nor to the script-level tests, which execute shell lifted out
of the workflows rather than the wiring between jobs.

The first is between `governance/rulesets/*.json` and this repo's own CI. A
ruleset names a BARE context, so the job publishing it has to be a top-level job
of `ci.yml` carrying exactly that name. Delegate it to a reusable and the
check-run arrives as `<caller-job> / <name>` — a different string, which never
satisfies the rule and never appears to fail either.

The second is inside `python-quality-gate.yml`. Its lanes fan into one pinnable
context because neither quality lane's own name is stable across shard counts.
A lane left out of that fan-in, bound but never read, or read without testing
its result, can fail or vanish while the aggregator prints PASS.

Exemptions are declared with the reason a lane's failure already reaches the
fan-in by another route, so intent stays distinguishable from drift.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
RULESET_DIR = REPO_ROOT / "governance" / "rulesets"

SELF_CHECK = WORKFLOW_DIR / "ci.yml"
GATE = WORKFLOW_DIR / "python-quality-gate.yml"
FAN_IN = "gate"

# job -> why the fan-in does not need it. A lane belongs outside the fan-in only
# when its own failure still fails the fan-in through another job.
FAN_IN_EXEMPT: dict[str, str] = {
    "detect-changes": (
        "Every lane needs it and reads its outputs. When it fails, its outputs "
        "are empty and both quality lanes skip, which the fan-in's "
        "both-quality-lanes-skipped assertion turns into a gate failure."
    ),
    "shards": (
        "It only builds the shard matrix. When it fails, quality-shard skips "
        "for want of its needs and the quality fallback lane is skipped by its "
        "own pytest-shards condition, so the same both-skipped assertion fires."
    ),
}

# job -> why a SKIPPED result of it cannot conceal unrun work. Every other job
# the fan-in needs must have its result compared against `skipped`.
SKIP_IS_LEGITIMATE: dict[str, str] = {
    "quality-non-shard": (
        "Its condition is quality-shard's plus shard-tier != '', so it can only "
        "skip when the sharded lane skipped too — already caught by the "
        "both-quality-lanes-skipped assertion."
    ),
    "coverage-combine": (
        "It merges the shard .coverage.* files and enforces the new-code floor "
        "against the result, and skips exactly when it has neither to do: no "
        "code changed, coverage upload off, or unsharded with the floor not "
        "requested. The one combination that would skip it with work "
        "outstanding — enforce-new-code-coverage true, upload-coverage-artifact "
        "false — is rejected in detect-changes before the matrix runs."
    ),
}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _jobs(document: dict) -> dict:
    return document.get("jobs") or {}


def _fan_in_step() -> dict:
    """The aggregation step: the one binding lane results AND running shell."""
    for step in _jobs(_load(GATE)).get(FAN_IN, {}).get("steps") or []:
        if isinstance(step, dict) and step.get("env") and step.get("run"):
            return step
    return {}


def _bindings(job: str) -> dict[str, str]:
    """env var -> expression, for each var the fan-in binds to `needs.<job>.…`."""
    return {
        var: str(expr)
        for var, expr in (_fan_in_step().get("env") or {}).items()
        if f"needs.{job}." in str(expr)
    }


def _reads(var: str, text: str) -> bool:
    return re.search(rf"\$\{{?{re.escape(var)}\b", text) is not None


def _tests_for_skipped(var: str, body: str) -> bool:
    """True when a line of the body branches on `$var` being `skipped`.

    A comment or a diagnostic `echo` naming the literal proves nothing, so
    neither counts.
    """
    return any(
        "skipped" in line
        and _reads(var, line)
        and not line.lstrip().startswith(("#", "echo"))
        for line in body.splitlines()
    )


def _required_contexts() -> set[str]:
    contexts = set()
    for path in sorted(RULESET_DIR.glob("*.json")):
        for rule in json.loads(path.read_text(encoding="utf-8")).get("rules") or []:
            if rule.get("type") != "required_status_checks":
                continue
            parameters = rule.get("parameters") or {}
            for check in parameters.get("required_status_checks") or []:
                if check.get("context"):
                    contexts.add(check["context"])
    return contexts


CONTEXTS = sorted(_required_contexts())
SELF_CHECK_JOBS = _jobs(_load(SELF_CHECK))
NEEDS = list(_jobs(_load(GATE)).get(FAN_IN, {}).get("needs") or [])
LANES = sorted(set(_jobs(_load(GATE))) - {FAN_IN})


def test_the_scan_found_contexts_lanes_and_an_aggregation_step() -> None:
    """A scan that silently matches nothing would pass every assertion below."""
    assert len(CONTEXTS) >= 2, (
        f"only {len(CONTEXTS)} required status context(s) parsed out of "
        f"{RULESET_DIR.name}/. The ruleset JSON shape has drifted, so no "
        f"context is being checked for a publisher. "
        f"fix: reconcile the parse with the rules[].parameters."
        f"required_status_checks[].context shape."
    )
    assert len(SELF_CHECK_JOBS) >= 3, (
        f"only {len(SELF_CHECK_JOBS)} job(s) parsed out of {SELF_CHECK.name}. "
        f"The self-check has drifted and the publisher assertion is vacuous. "
        f"fix: reconcile the parse with the workflow's jobs mapping."
    )
    assert len(NEEDS) >= 3, (
        f"the `{FAN_IN}` fan-in of {GATE.name} requires only {len(NEEDS)} "
        f"job(s). Either FAN_IN no longer names the aggregator or the parse has "
        f"drifted, and the lane assertions no longer cover the gate. "
        f"fix: reconcile FAN_IN with the job aggregating the lanes."
    )
    assert _fan_in_step().get("run"), (
        f"no aggregation step (one carrying both `env` and `run`) found in "
        f"{GATE.name}'s `{FAN_IN}` job, so no lane result is being checked. "
        f"fix: reconcile `_fan_in_step` with the step that reads the results."
    )


@pytest.mark.parametrize("context", CONTEXTS)
def test_a_bare_required_context_has_a_top_level_publisher(context: str) -> None:
    publishers = [
        job_id
        for job_id, job in SELF_CHECK_JOBS.items()
        if isinstance(job, dict) and str(job.get("name") or job_id) == context
    ]
    assert publishers, (
        f"the rulesets require the status context `{context}` but no top-level "
        f"job of {SELF_CHECK.name} carries that name, so nothing on a PR to "
        f"this repo ever publishes it. A required context that is never "
        f"reported blocks every PR until the rule is relaxed, and relaxing it "
        f"removes the control. "
        f"fix: name a top-level job of {SELF_CHECK.name} exactly `{context}`, "
        f"or drop the context from {RULESET_DIR.name}/."
    )
    delegated = sorted(
        job_id for job_id in publishers if SELF_CHECK_JOBS[job_id].get("uses")
    )
    assert not delegated, (
        f"{SELF_CHECK.name}: job(s) {delegated} publish the required context "
        f"`{context}` through a reusable `uses:`. A delegated leg reports as "
        f"`<caller-job> / <leg>`, never the bare `{context}` the rulesets name, "
        f"so the rule is satisfied by nothing and fails on nothing. "
        f"fix: run the check in a top-level job of {SELF_CHECK.name} named "
        f"`{context}`."
    )


@pytest.mark.parametrize("job", NEEDS)
def test_the_fan_in_reads_every_lane_it_requires(job: str) -> None:
    bound = _bindings(job)
    assert bound, (
        f"{GATE.name}: `{FAN_IN}` requires `{job}` but binds nothing from it "
        f"into the aggregation step's `env:`, so its outcome cannot reach the "
        f"required context — the lane can fail and the gate still prints PASS. "
        f"fix: bind `${{{{ needs.{job}.result }}}}` in the step's `env:` and "
        f"check it in the `run:` body."
    )
    # A variable named only in an `echo` is reported, not tested: the lane's
    # outcome still never changes the gate's exit status. Judge the decision
    # lines alone, so dropping a lane from the check while leaving it in the
    # progress line is not mistaken for reading it.
    body = "\n".join(
        line for line in str(_fan_in_step().get("run", "")).splitlines()
        if not line.strip().startswith("echo")
    )
    unread = sorted(var for var in bound if not _reads(var, body))
    assert not unread, (
        f"{GATE.name}: `{FAN_IN}` binds {unread} from `{job}` but never reads "
        f"them in the `run:` body. A bound-but-unread result is the same as no "
        f"binding at all: the lane's outcome never affects the gate. "
        f"fix: test the variable in the aggregation body."
    )


@pytest.mark.parametrize("job", LANES)
def test_every_lane_is_wired_into_the_fan_in(job: str) -> None:
    if job in FAN_IN_EXEMPT:
        assert job not in NEEDS, (
            f"`{job}` is listed in FAN_IN_EXEMPT but is now a `needs:` of "
            f"`{FAN_IN}`. fix: drop it from FAN_IN_EXEMPT so the wiring "
            f"assertion covers it."
        )
        return
    assert job in NEEDS, (
        f"{GATE.name}: `{job}` is not a `needs:` of the `{FAN_IN}` fan-in, so "
        f"its result never reaches the one context a consumer pins. It can fail "
        f"while the required check reports green and the PR merges. "
        f"fix: add `{job}` to `jobs.{FAN_IN}.needs` and check its result, or "
        f"declare it in FAN_IN_EXEMPT naming the route by which its failure "
        f"still fails the fan-in."
    )


@pytest.mark.parametrize("job", NEEDS)
def test_a_skipped_quality_lane_cannot_report_pass(job: str) -> None:
    body = str(_fan_in_step().get("run", ""))
    results = [
        var for var, expr in _bindings(job).items() if f"needs.{job}.result" in expr
    ]
    checked = any(_tests_for_skipped(var, body) for var in results)

    if job in SKIP_IS_LEGITIMATE:
        assert not checked, (
            f"`{job}` is listed in SKIP_IS_LEGITIMATE but the fan-in now tests "
            f"it for `skipped`. fix: drop it from SKIP_IS_LEGITIMATE so the "
            f"assertion covers it."
        )
        return

    assert checked, (
        f"{GATE.name}: `{FAN_IN}` never tests `{job}`'s result against "
        f"`skipped`. The result loop rejects only `failure` and `cancelled`, so "
        f"a lane that was asked for but never ran falls through to PASS — the "
        f"control reports as enforced while it did not execute, and branch "
        f"protection has nothing to fail on. "
        f"fix: test that lane's result against `skipped` in the aggregation "
        f"body, or declare `{job}` in SKIP_IS_LEGITIMATE with the reason it can "
        f"only skip when it has no work to do."
    )


def test_every_declared_exception_names_a_live_job() -> None:
    """A stale exception silently exempts a lane from every assertion above."""
    stale_lanes = sorted(set(FAN_IN_EXEMPT) - set(LANES))
    stale_skips = sorted(set(SKIP_IS_LEGITIMATE) - set(NEEDS))
    assert not (stale_lanes or stale_skips), (
        f"exceptions name jobs that no longer exist — FAN_IN_EXEMPT="
        f"{stale_lanes}, SKIP_IS_LEGITIMATE={stale_skips}. Each outlives the "
        f"job it explains and would exempt a renamed successor. "
        f"fix: remove the entry, or repoint it at the current job."
    )
