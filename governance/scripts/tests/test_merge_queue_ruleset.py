"""Contract tests for the canonical GitHub merge-queue ruleset payload."""

import json
from pathlib import Path

RULESET = Path(__file__).parents[2] / "rulesets" / "merge-queue.json"
GOVERNANCE = RULESET.parents[1]


def _payload() -> dict:
    return json.loads(RULESET.read_text(encoding="utf-8"))


def _merge_queue_rule(payload: dict) -> dict:
    return next(rule for rule in payload["rules"] if rule["type"] == "merge_queue")


def test_merge_queue_payload_is_rest_importable_and_fast_path() -> None:
    payload = _payload()
    parameters = _merge_queue_rule(payload)["parameters"]

    assert payload["name"] == "main-merge-queue"
    assert set(payload) == {
        "name",
        "target",
        "enforcement",
        "bypass_actors",
        "conditions",
        "rules",
    }
    assert payload["target"] == "branch"
    assert payload["enforcement"] == "active"
    assert payload["conditions"] == {
        "ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}
    }
    assert parameters == {
        "grouping_strategy": "ALLGREEN",
        "min_entries_to_merge": 1,
        "max_entries_to_merge": 1,
        "min_entries_to_merge_wait_minutes": 0,
        "max_entries_to_build": 3,
        "merge_method": "MERGE",
        "check_response_timeout_minutes": 45,
    }


def test_merge_queue_bypass_is_human_pull_request_only() -> None:
    payload = _payload()

    assert payload["bypass_actors"] == [
        {
            "actor_id": 18141275,
            "actor_type": "Team",
            "bypass_mode": "pull_request",
        }
    ]
    assert all(
        actor["actor_type"] != "Integration" for actor in payload["bypass_actors"]
    )


def test_template_does_not_claim_the_removed_rest_limitation() -> None:
    source = RULESET.read_text(encoding="utf-8")

    assert "REST 422" not in source
    assert "WEB-UI-ONLY" not in source


def test_canonical_docs_use_rest_and_keep_the_queue_less_fallback() -> None:
    architecture = (
        GOVERNANCE / "standards" / "ci-release-deployment-architecture.md"
    ).read_text(encoding="utf-8")
    decision = (GOVERNANCE / "decisions" / "MERGE-QUEUE-D1.md").read_text(
        encoding="utf-8"
    )

    assert "merge queue is enabled in the GitHub UI" not in architecture
    assert "repository rulesets API" in architecture
    assert "Team-plan" in decision
    assert "queue-less" in decision
