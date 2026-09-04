"""Contract for the opt-in safe-normalisation phase of the Python gate.

The phase repairs a runner checkout before evaluators run. A missing forwarding
edge is silent: one shard, the non-shard complement, or the duration-map job
would observe a different tree while the fan-in still reports green.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
GATE = WORKFLOWS / "python-quality-gate.yml"
REFRESH = WORKFLOWS / "pytest-durations-refresh.yml"
BODY = REPO_ROOT / "actions" / "python-gate-body" / "action.yml"
INPUT = "pre-evaluation-normalize"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _workflow_inputs(document: dict) -> dict:
    trigger = document.get(True) or document.get("on") or {}
    return (trigger.get("workflow_call") or {}).get("inputs") or {}


def test_normalization_is_opt_in_at_every_public_entrypoint() -> None:
    for path in (GATE, REFRESH):
        spec = _workflow_inputs(_load(path))[INPUT]
        assert spec["default"] == ""
        assert "deterministic" in spec["description"].lower()


def test_gate_body_runs_normalization_before_any_evaluation() -> None:
    body = _load(BODY)
    assert body["inputs"][INPUT]["required"] is True

    steps = body["runs"]["steps"]
    names = [step.get("name") for step in steps]
    normalizer = next(
        step for step in steps if step.get("name") == "Pre-evaluation normalization"
    )

    assert normalizer["if"] == f"inputs.{INPUT} != ''"
    assert normalizer["run"] == f"${{{{ inputs.{INPUT} }}}}"
    assert names.index("pnpm install") < names.index("Pre-evaluation normalization")
    assert names.index("Pre-evaluation normalization") < names.index(
        "Write changed-file list"
    )
    assert names.index("Pre-evaluation normalization") < names.index("Pre-steps")
    assert names.index("Pre-evaluation normalization") < names.index("Fitness gate")
    assert names.index("Pre-evaluation normalization") < names.index(
        "Re-sync normalized project"
    )
    assert names.index("Re-sync normalized project") < names.index(
        "Write changed-file list"
    )


def test_changed_file_capture_includes_normalizer_worktree_changes() -> None:
    body_text = BODY.read_text(encoding="utf-8")

    assert 'git diff --name-only "$base...$head"' in body_text
    assert "git diff --name-only\n" in body_text
    assert "git diff --name-only --cached" in body_text
    assert "git ls-files --others --exclude-standard" in body_text
    assert 'LC_ALL=C sort -u > "$CHANGED_FILES_PATH"' in body_text


def test_coverage_combine_recreates_the_normalized_tree() -> None:
    gate = _load(GATE)
    steps = gate["jobs"]["coverage-combine"]["steps"]
    names = [step.get("name") for step in steps]

    normalizer = next(
        step for step in steps if step.get("name") == "Pre-evaluation normalization"
    )
    assert normalizer["run"] == f"${{{{ inputs.{INPUT} }}}}"
    assert names.index("Locked uv install") < names.index(
        "Pre-evaluation normalization"
    )
    assert names.index("pnpm install") < names.index("Pre-evaluation normalization")
    assert names.index("Pre-evaluation normalization") < names.index(
        "Re-sync normalized project"
    )
    assert names.index("Re-sync normalized project") < names.index(
        "Combine shard coverage → XML"
    )


def test_every_quality_lane_and_duration_refresh_forward_normalization() -> None:
    gate = _load(GATE)
    lanes = []
    for job in gate["jobs"].values():
        for step in job.get("steps") or []:
            if "python-gate-body" in str(step.get("uses", "")):
                lanes.append(step["with"])

    assert len(lanes) >= 3
    assert all(lane[INPUT] == f"${{{{ inputs.{INPUT} }}}}" for lane in lanes)

    refresh = _load(REFRESH)
    step = next(
        step
        for step in refresh["jobs"]["refresh"]["steps"]
        if "python-gate-body" in str(step.get("uses", ""))
    )
    assert step["with"][INPUT] == f"${{{{ inputs.{INPUT} }}}}"
