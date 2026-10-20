"""Contract tests for the canonical GitHub merge-queue ruleset payload."""

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

RULESET = Path(__file__).parents[2] / "rulesets" / "merge-queue.json"
GOVERNANCE = RULESET.parents[1]
NEXT = "next: uv run --frozen pytest -q assurance/governance/scripts/tests/test_merge_queue_ruleset.py"
FIX_RULESET = f"fix: restore the canonical payload in rulesets/{RULESET.name}; {NEXT}"


def _payload() -> dict:
    return json.loads(RULESET.read_text(encoding="utf-8"))


def _merge_queue_rule(payload: dict) -> dict:
    return next(rule for rule in payload["rules"] if rule["type"] == "merge_queue")


def test_merge_queue_payload_is_rest_importable_and_fast_path() -> None:
    payload = _payload()
    parameters = _merge_queue_rule(payload)["parameters"]

    assert payload["name"] == "main-merge-queue", f"the ruleset is renamed. {FIX_RULESET}"
    assert set(payload) == {
        "name",
        "target",
        "enforcement",
        "bypass_actors",
        "conditions",
        "rules",
    }, f"the payload has keys the rulesets REST API does not import. {FIX_RULESET}"
    assert payload["target"] == "branch", f"the queue must target a branch. {FIX_RULESET}"
    assert payload["enforcement"] == "active", f"the queue is not enforced. {FIX_RULESET}"
    assert payload["conditions"] == {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}}, (
        f"the queue no longer guards exactly the default branch. {FIX_RULESET}"
    )
    assert parameters == {
        "grouping_strategy": "ALLGREEN",
        "min_entries_to_merge": 1,
        "max_entries_to_merge": 5,
        "min_entries_to_merge_wait_minutes": 0,
        "max_entries_to_build": 3,
        "merge_method": "MERGE",
        "check_response_timeout_minutes": 45,
    }, f"the queue parameters left the canonical all-green, merge-commit profile. {FIX_RULESET}"


def test_merge_queue_bypass_is_human_pull_request_only() -> None:
    payload = _payload()

    assert payload["bypass_actors"] == [
        {
            "actor_id": 18141275,
            "actor_type": "Team",
            "bypass_mode": "pull_request",
        }
    ], f"only the maintainers team may bypass the queue, and only through a pull request. {FIX_RULESET}"
    assert all(actor["actor_type"] != "Integration" for actor in payload["bypass_actors"]), (
        f"an App can bypass the queue. {FIX_RULESET}"
    )


def test_template_does_not_claim_the_removed_rest_limitation() -> None:
    source = RULESET.read_text(encoding="utf-8")

    assert "REST 422" not in source and "WEB-UI-ONLY" not in source, (
        f"rulesets/{RULESET.name} claims the queue cannot be created through REST, which the "
        f"rulesets API now supports. fix: remove the claim; {NEXT}"
    )


def test_canonical_docs_use_rest_and_keep_the_queue_less_fallback() -> None:
    architecture = (GOVERNANCE / "standards" / "ci-release-deployment-architecture.md").read_text(
        encoding="utf-8"
    )
    decision = next(
        path
        for path in (
            GOVERNANCE / "decisions" / "ADR-0003-merge-queue-for-product-repos.md",
            # The tc-pipelines export keeps the decision's original identifier.
            GOVERNANCE / "decisions" / "MERGE-QUEUE-D1.md",
        )
        if path.is_file()
    ).read_text(encoding="utf-8")

    assert "merge queue is enabled in the GitHub UI" not in architecture, (
        f"ci-release-deployment-architecture.md says the queue is set in the UI. fix: describe the "
        f"repository rulesets API instead; {NEXT}"
    )
    assert "repository rulesets API" in architecture, (
        f"ci-release-deployment-architecture.md no longer names the repository rulesets API. fix: "
        f"restore it as the way the queue is applied; {NEXT}"
    )
    assert "Team-plan" in decision and "queue-less" in decision, (
        f"the merge-queue decision dropped its Team-plan constraint or the queue-less fallback. fix: "
        f"restore both in the decision; {NEXT}"
    )
