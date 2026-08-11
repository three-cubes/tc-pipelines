"""Contract tests for `python-quality-gate.yml`'s `shard-tier` input.

Only steps declaring `shard_args` split across shards. Every other step — for a
consumer with a fitness catalogue, that is the entire catalogue — otherwise runs
in full inside every shard: N times the compute, with its duration sitting on
each shard's critical path rather than once. Measured on tc-agent-zone, the
catalogue took 280s of a 915s shard, four times over.

`shard-tier` lets the caller point the shard jobs at a tier containing only the
sharded step. It must stay optional: an empty value has to preserve the previous
behaviour exactly, or every existing consumer changes shape on upgrade.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "python-quality-gate.yml"

pytestmark = pytest.mark.contract


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _inputs(wf: dict) -> dict:
    # `on:` parses as the boolean True in YAML 1.1.
    trigger = wf.get("on") or wf[True]
    return trigger["workflow_call"]["inputs"]


def test_shard_tier_is_optional_and_defaults_to_empty() -> None:
    """A consumer that never sets it must see no behaviour change."""
    spec = _inputs(_workflow())["shard-tier"]

    assert spec.get("required", False) is False
    assert spec["default"] == ""
    assert spec["type"] == "string"


def test_shard_jobs_prefer_shard_tier_and_fall_back_to_tier() -> None:
    """Set → the shard jobs use it; empty → they use `tier`, as before."""
    expr = str(_workflow()["jobs"]["quality-shard"]["steps"][0]["with"]["tier"])

    assert "inputs.shard-tier" in expr, "the shard jobs must consult shard-tier"
    assert "inputs.tier" in expr, "an empty shard-tier must fall back to tier"
    # Guarded on != '' with a non-empty true branch: a GitHub `A && '' || B`
    # ternary returns B even when A is true, because '' is falsy.
    assert "inputs.shard-tier != ''" in expr, "the fallback must test for empty, not truthiness"


def test_the_unsharded_job_is_untouched() -> None:
    """The single-job path keeps taking `tier` — shard-tier is shard-only."""
    expr = str(_workflow()["jobs"]["quality"]["steps"][0]["with"]["tier"])

    assert expr.strip() == "${{ inputs.tier }}"


def test_the_non_shard_lane_is_gated_by_the_fan_in() -> None:
    """The complement must sit inside the required context, not beside it.

    With `shard-tier` set the shard lanes cover only the sharded step. If the
    remaining steps ran in a lane the fan-in ignores — or in a lane each consumer
    had to build for itself — they would drop out of `Python quality gate result`
    while it still reported green. That is a silently-skipped gate, which is the
    failure this whole input exists to remove, not to introduce.
    """
    wf = _workflow()

    assert "quality-non-shard" in wf["jobs"], "the workflow must own the complement lane"
    assert "quality-non-shard" in wf["jobs"]["gate"]["needs"], "the fan-in must require it"

    step = wf["jobs"]["gate"]["steps"][0]
    assert "R_NONSHARD" in step["env"], "its result must be read"
    assert "$R_NONSHARD" in step["run"], "its result must be checked, not merely read"


def test_the_complement_lane_runs_only_when_sharding_with_a_shard_tier() -> None:
    """It is inert for every consumer that has not opted in."""
    cond = " ".join(str(_workflow()["jobs"]["quality-non-shard"]["if"]).split())

    assert "inputs.pytest-shards > 1" in cond
    assert "inputs.shard-tier != ''" in cond


def test_a_shard_tier_without_its_complement_fails_fast() -> None:
    """Half-configured is the dangerous state, so refuse it loudly.

    Setting `shard-tier` and forgetting `non-shard-tier` would otherwise run the
    shards alone and report a green gate over a fraction of the checks.
    """
    steps = _workflow()["jobs"]["quality-non-shard"]["steps"]
    guard = steps[0]

    assert "inputs.non-shard-tier == ''" in str(guard["if"])
    assert "exit 1" in guard["run"]
    assert "::error::" in guard["run"], "the failure must be actionable, not silent"


def test_the_complement_lane_runs_the_non_shard_tier() -> None:
    """It must select the complement, not repeat the shard tier or the whole gate."""
    body = _workflow()["jobs"]["quality-non-shard"]["steps"][1]

    assert str(body["with"]["tier"]).strip() == "${{ inputs.non-shard-tier }}"
    assert "shard-index" not in body["with"], "the complement lane must not shard"
