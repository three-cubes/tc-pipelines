"""Every internal caller must satisfy the contract of what it calls.

Actions resolves these contracts at run time, and the two failure modes are
asymmetric. A reusable workflow called with a bad input shape fails the whole
run as `startup_failure`, with no log to read. A composite action called without
a `required` input only logs a warning and hands the step an empty string, so
the step runs, behaves differently, and reports success.

Neither is visible to actionlint or yamllint, which judge each file alone, and
neither is reachable by the script-level tests, which execute shell lifted out
of the workflows rather than the workflows themselves. That gap has produced
real defects: a `quality-non-shard` lane that silently dropped a consumer's
`pre-steps`, so its checks ran against an unprepared environment while the shard
lanes ran against a prepared one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
ACTION_DIR = REPO_ROOT / "actions"

LOCAL_REUSABLE = re.compile(r"^\./\.github/workflows/(.+\.yml)$")
LOCAL_ACTION = re.compile(r"^(?:\./actions/|three-cubes/tc-pipelines/actions/)([^@/]+)")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _triggers(document: dict) -> dict:
    # `on:` parses as the boolean True under YAML 1.1.
    return document.get(True) or document.get("on") or {}


def _reusable_contracts() -> dict[str, dict]:
    contracts = {}
    for path in WORKFLOW_DIR.glob("*.yml"):
        call = _triggers(_load(path)).get("workflow_call")
        if isinstance(call, dict):
            contracts[path.name] = call.get("inputs") or {}
    return contracts


def _action_contracts() -> dict[str, dict]:
    return {
        path.parent.name: (_load(path).get("inputs") or {})
        for path in ACTION_DIR.glob("*/action.yml")
    }


def _calls() -> list[tuple[str, str, dict, dict]]:
    """(source workflow, label, declared inputs of the target, inputs passed)."""
    reusables, actions = _reusable_contracts(), _action_contracts()
    found = []
    for path in WORKFLOW_DIR.glob("*.yml"):
        for job_name, job in (_load(path).get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            match = LOCAL_REUSABLE.match(str(job.get("uses", "")))
            if match and match.group(1) in reusables:
                found.append(
                    (
                        path.name,
                        f"{job_name} -> {match.group(1)}",
                        reusables[match.group(1)],
                        job.get("with") or {},
                    )
                )
            for step in job.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                match = LOCAL_ACTION.match(str(step.get("uses", "")))
                if match and match.group(1) in actions:
                    found.append(
                        (
                            path.name,
                            f"{job_name} -> actions/{match.group(1)}",
                            actions[match.group(1)],
                            step.get("with") or {},
                        )
                    )
    return found


CALLS = _calls()


def test_the_scan_found_calls_to_check() -> None:
    """A scan that silently matches nothing would pass every assertion below."""
    assert len(CALLS) >= 10, (
        f"only {len(CALLS)} internal calls discovered — the `uses:` patterns "
        f"have probably drifted, so these contracts are no longer being checked."
    )


@pytest.mark.parametrize(
    ("source", "label", "declared", "passed"),
    CALLS,
    ids=[f"{source}:{label}" for source, label, _, _ in CALLS],
)
def test_call_passes_every_required_input(
    source: str, label: str, declared: dict, passed: dict
) -> None:
    required = {
        name
        for name, spec in declared.items()
        if spec.get("required") and "default" not in spec
    }
    missing = sorted(required - set(passed))
    assert not missing, (
        f"{source}: `{label}` omits required input(s) {missing}. A reusable "
        f"fails the run as startup_failure; a composite action only warns and "
        f"substitutes an empty string, so the step runs with different "
        f"behaviour and still reports success. "
        f"fix: pass the input, or give it a default in the target."
    )


@pytest.mark.parametrize(
    ("source", "label", "declared", "passed"),
    CALLS,
    ids=[f"{source}:{label}" for source, label, _, _ in CALLS],
)
def test_call_passes_no_unknown_input(
    source: str, label: str, declared: dict, passed: dict
) -> None:
    unknown = sorted(set(passed) - set(declared))
    assert not unknown, (
        f"{source}: `{label}` passes input(s) {unknown} the target does not "
        f"declare. fix: correct the name, or declare it on the target."
    )


def _gate_body_calls() -> dict[str, dict]:
    document = _load(WORKFLOW_DIR / "python-quality-gate.yml")
    calls = {}
    for job_name, job in (document.get("jobs") or {}).items():
        for step in (job.get("steps") or []) if isinstance(job, dict) else []:
            if isinstance(step, dict) and "python-gate-body" in str(
                step.get("uses", "")
            ):
                calls[job_name] = step.get("with") or {}
    return calls


# Inputs that carry a consumer's own configuration. A lane that drops one runs a
# differently configured gate than its siblings while still reporting on the
# same fan-in context. Inputs a lane sets deliberately per-lane (tier, sharding,
# coverage upload, the attribution scan) are excluded.
CONSUMER_FORWARDED = (
    "pre-evaluation-normalize",
    "pre-steps",
    "post-steps",
    "python-version",
    "uv-version",
    "sync-args",
    "run-node",
    "pnpm-version",
    "pnpm-install-args",
)


@pytest.mark.parametrize("name", CONSUMER_FORWARDED)
def test_every_gate_lane_forwards_the_same_consumer_input(name: str) -> None:
    calls = _gate_body_calls()
    assert calls, "no python-gate-body calls found in python-quality-gate.yml"
    dropped = sorted(job for job, passed in calls.items() if name not in passed)
    assert not dropped, (
        f"lane(s) {dropped} do not forward `{name}` while their siblings do. "
        f"The lanes then run differently configured gates behind one required "
        f"status context. fix: forward `${{{{ inputs.{name} }}}}` in every lane."
    )
