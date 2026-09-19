"""Contract for the trusted fixed preparation phase of the Python gate.

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


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _workflow_inputs(document: dict) -> dict:
    trigger = document.get(True) or document.get("on") or {}
    return (trigger.get("workflow_call") or {}).get("inputs") or {}


def test_arbitrary_normalization_is_not_a_public_entrypoint() -> None:
    for path in (GATE, REFRESH):
        assert "pre-evaluation-normalize" not in _workflow_inputs(_load(path))
    assert "pre-evaluation-normalize" not in _load(BODY)["inputs"]


def test_gate_body_cannot_run_candidate_owned_normalization() -> None:
    body = _load(BODY)
    names = [step.get("name") for step in body["runs"]["steps"]]
    assert "Pre-evaluation normalization" not in names
    assert "Bind evaluation to the committed tree" not in names
    assert "Re-sync normalized project" not in names


def test_changed_file_capture_includes_normalizer_worktree_changes() -> None:
    body_text = BODY.read_text(encoding="utf-8")

    assert 'git diff --name-only "$base...$head"' in body_text
    assert "git diff --name-only\n" in body_text
    assert "git diff --name-only --cached" in body_text
    assert "git ls-files --others --exclude-standard" in body_text
    assert 'LC_ALL=C sort -u > "$CHANGED_FILES_PATH"' in body_text


def test_reusable_prepares_once_and_proves_a_fixed_point_before_evaluation() -> None:
    gate = _load(GATE)
    steps = gate["jobs"]["preparation"]["steps"]
    names = [step.get("name") for step in steps]

    first = next(step for step in steps if step.get("name") == "Prepare candidate")
    second = next(step for step in steps if step.get("name") == "Prove preparation is a fixed point")
    assert first["run"] == second["run"]
    assert "[[ ! -f pyproject.toml ]] || uvx --from uv==0.12.5 uv lock" in first["run"]
    assert "ruff check --force-exclude" in first["run"]
    assert "--no-unsafe-fixes --exit-zero" in first["run"]
    assert "ruff format --force-exclude --line-length 110 --target-version py312" in first["run"]
    assert names.index("Install trusted uv for formatter preparation") < names.index("Prepare candidate")
    assert names.index("Capture committed candidate state") < names.index("Prepare candidate")
    assert names.index("Prepare candidate") < names.index("Capture first prepared state")
    assert names.index("Capture first prepared state") < names.index("Produce bounded preparation evidence")
    assert names.index("Produce bounded preparation evidence") < names.index(
        "Prove preparation is a fixed point"
    )
    assert names.index("Prove preparation is a fixed point") < names.index("Capture second prepared state")
    assert names.index("Capture second prepared state") < names.index(
        "Admit clean candidate or request exact writeback"
    )


def test_quality_lanes_consume_prepared_bytes_without_repeating_normalization() -> None:
    gate = _load(GATE)
    lanes = []
    for job in gate["jobs"].values():
        for step in job.get("steps") or []:
            if "python-gate-body" in str(step.get("uses", "")):
                lanes.append(step["with"])

    assert len(lanes) == 3
    assert all("pre-evaluation-normalize" not in lane for lane in lanes)
    assert all("candidate-head-sha" in lane for lane in lanes)

    refresh = _load(REFRESH)
    step = next(
        step
        for step in refresh["jobs"]["refresh"]["steps"]
        if "python-gate-body" in str(step.get("uses", ""))
    )
    assert "pre-evaluation-normalize" not in step["with"]
