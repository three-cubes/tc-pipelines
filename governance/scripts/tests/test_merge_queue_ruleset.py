"""Contract tests for the canonical GitHub merge-queue ruleset payload."""

import json
from pathlib import Path

RULESET = Path(__file__).parents[2] / "rulesets" / "merge-queue.json"


def _payload() -> dict:
    return json.loads(RULESET.read_text(encoding="utf-8"))


def _merge_queue_rule(payload: dict) -> dict:
    return next(rule for rule in payload["rules"] if rule["type"] == "merge_queue")


def test_merge_queue_payload_is_rest_importable_and_fast_path() -> None:
    payload = _payload()
    parameters = _merge_queue_rule(payload)["parameters"]

    assert payload["name"] == "main-merge-queue"
    assert payload["target"] == "branch"
    assert payload["enforcement"] == "active"
    assert payload["conditions"] == {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}}
    assert parameters == {
        "grouping_strategy": "ALLGREEN",
        "min_entries_to_merge": 1,
        "max_entries_to_merge": 1,
        "min_entries_to_merge_wait_minutes": 0,
        "max_entries_to_build": 3,
        "merge_method": "MERGE",
        "check_response_timeout_minutes": 30,
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
    assert all(actor["actor_type"] != "Integration" for actor in payload["bypass_actors"])


def test_template_does_not_claim_the_removed_rest_limitation() -> None:
    source = RULESET.read_text(encoding="utf-8")

    assert "REST 422" not in source
    assert "WEB-UI-ONLY" not in source
