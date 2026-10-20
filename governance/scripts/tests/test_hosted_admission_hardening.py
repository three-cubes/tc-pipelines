"""Hosted-admission hardening: each test fails on the code it replaces."""

import sys

import pytest
import yaml
from test_hosted_assurance import ROOT, git, hosted_module

pytestmark = pytest.mark.contract

VALIDATOR = "e" * 40
SCANNER_WORKFLOW = ".github/workflows/live-scanner-qualification.yml"


def scanner_run(**changes):
    run = {
        "id": 42,
        "run_attempt": 2,
        "status": "completed",
        "conclusion": "success",
        "path": SCANNER_WORKFLOW,
        "event": "workflow_dispatch",
        "head_sha": VALIDATOR,
        "repository": {"full_name": "fixtures/pipelines"},
        "referenced_workflows": [],
    }
    return {**run, **changes}


def scanner_module():
    hosted_module()  # puts assurance/ on sys.path
    import live_scanners

    return live_scanners


def test_scanner_admission_accepts_the_approved_validator_as_a_direct_dispatch():
    scanners = scanner_module()
    scanners.validate_run(scanner_run(), "fixtures/pipelines", "42", 2, VALIDATOR)


def test_scanner_admission_refuses_a_reusable_call_that_only_names_the_validator():
    """A caller lists a workflow it named even when its job never ran, and its artifacts are its own."""
    scanners = scanner_module()
    called = scanner_run(
        path=".github/workflows/ci.yml",
        event="push",
        head_sha="f" * 40,
        referenced_workflows=[
            {"path": "fixtures/pipelines/" + SCANNER_WORKFLOW + "@refs/heads/main", "sha": VALIDATOR}
        ],
    )
    with pytest.raises(ValueError, match="approved validator revision"):
        scanners.validate_run(called, "fixtures/pipelines", "42", 2, VALIDATOR)


@pytest.mark.parametrize(
    "changes",
    [
        {"head_sha": "f" * 40},
        {"event": "push"},
        {
            "path": ".github/workflows/ci.yml",
            "referenced_workflows": [
                {"path": "fixtures/pipelines/" + SCANNER_WORKFLOW + "@refs/heads/branch", "sha": "f" * 40}
            ],
        },
        {"path": ".github/workflows/mimic.yml"},
        {"path": SCANNER_WORKFLOW + "@forged.yml"},
    ],
)
def test_scanner_admission_rejects_a_successful_same_path_run_from_an_unapproved_revision(changes):
    scanners = scanner_module()
    with pytest.raises(ValueError, match="approved validator revision"):
        scanners.validate_run(scanner_run(**changes), "fixtures/pipelines", "42", 2, VALIDATOR)


def test_the_scanner_admission_cli_has_no_cross_repository_mode(tmp_path, capsys):
    """A caller's run is refused, so the option that named the called workflow's repository is gone."""
    scanners = scanner_module()
    sys.argv = [
        "live_scanners.py",
        "admit",
        "--output",
        str(tmp_path),
        "--candidate",
        "a" * 40,
        "--validator",
        VALIDATOR,
        "--validator-repository",
        "fixtures/pipelines",
    ]
    with pytest.raises(SystemExit) as refusal:
        scanners.main()
    assert refusal.value.code == 2
    assert "--validator-repository" in capsys.readouterr().err


def test_scanner_admission_still_rejects_a_wrong_or_unsuccessful_run():
    scanners = scanner_module()
    for changes in ({"id": 7}, {"run_attempt": 1}, {"conclusion": "failure"}, {"status": "queued"}):
        with pytest.raises(ValueError, match="wrong or unsuccessful"):
            scanners.validate_run(scanner_run(**changes), "fixtures/pipelines", "42", 2, VALIDATOR)
    with pytest.raises(ValueError, match="wrong or unsuccessful"):
        scanners.validate_run(
            scanner_run(repository={"full_name": "fixtures/elsewhere"}),
            "fixtures/pipelines",
            "42",
            2,
            VALIDATOR,
        )


def test_scanner_admission_requires_the_operator_to_name_the_validator(tmp_path):
    scanners = scanner_module()
    sys.argv = ["live_scanners.py", "admit", "--output", str(tmp_path), "--candidate", "a" * 40]
    with pytest.raises(SystemExit) as refusal:
        scanners.main()
    assert refusal.value.code == 2


def test_protected_policy_must_name_the_approved_producer_commit():
    hosted_module()
    from protected_evidence import validate_provenance

    policy = {
        "repository": "fixtures/runtime",
        "run_id": 42,
        "attempt_id": 2,
        "workflow_path": ".github/workflows/status.yml",
        "actor_id": 123,
    }
    run = {"head_sha": "d" * 40}
    with pytest.raises(ValueError, match="producer commit"):
        validate_provenance(run, {"candidate_head": "d" * 40}, policy)
    with pytest.raises(ValueError, match="producer commit"):
        validate_provenance(run, {}, {**policy, "producer_commit": "not-a-commit"})


def test_the_release_plan_asks_the_operator_for_the_producer_commit():
    module = hosted_module()
    assert "producer_commit" in module.REQUIRED_PROTECTED_POLICY_FIELDS


def test_protected_artifacts_are_read_from_every_page():
    hosted_module()
    from protected_evidence import run_artifacts

    approved = {"id": 150, "name": "protected-status", "expired": False}
    pages = {
        1: {"total_count": 101, "artifacts": [{"id": n, "name": f"other-{n}"} for n in range(100)]},
        2: {"total_count": 101, "artifacts": [approved]},
    }
    requested = []

    def api(root, endpoint):
        requested.append(endpoint)
        return pages[int(endpoint.rsplit("page=", 1)[1])]

    found = run_artifacts(None, "fixtures/runtime", 42, api)
    assert [a for a in found if a["name"] == "protected-status"] == [approved]
    assert len(found) == 101
    assert len(requested) == 2


def test_adapter_verifier_rejects_a_modified_or_untracked_file_left_by_preparation(tmp_path, monkeypatch):
    hosted_module()
    import verify_adapter

    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "fixture")
    git(tmp_path, "config", "user.email", "fixture@example.invalid")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fixture'\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "fixture")
    monkeypatch.chdir(tmp_path)
    assert verify_adapter.verify("action-actions-python-preparation") == {
        "status": "pass",
        "working_tree": "clean",
    }
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'changed'\n")
    with pytest.raises(ValueError, match="preparation changed"):
        verify_adapter.verify("action-actions-python-preparation")
    git(tmp_path, "checkout", "--", "pyproject.toml")
    (tmp_path / "uv.lock").write_text("generated by preparation\n")
    with pytest.raises(ValueError, match=r"preparation changed[\s\S]*uv\.lock"):
        verify_adapter.verify("action-actions-python-preparation")


def test_readme_surface_counts_follow_the_inventory():
    inventory = yaml.safe_load((ROOT / "assurance/surfaces.yaml").read_text())["surfaces"]
    readme = (ROOT / "assurance/README.md").read_text()
    counts = {}
    for row in inventory:
        boundary = row["hosted"]["boundary"]
        counts[boundary] = counts.get(boundary, 0) + 1
    assert f"| {len(inventory)} |" in readme
    for boundary, count in counts.items():
        assert f"| `{boundary}` | {count} |" in readme, boundary


def test_protected_artifacts_belong_to_the_approved_attempt():
    """A re-run leaves attempt 1's artifact beside attempt 2's; only attempt 2's may be authorised."""
    hosted_module()
    from protected_evidence import attempt_artifacts

    stale = {"id": 1, "name": "protected-status", "expired": False, "created_at": "2026-10-01T10:05:00Z"}
    approved = {"id": 150, "name": "protected-status", "expired": False, "created_at": "2026-10-01T11:05:00Z"}
    filler = [{"id": n, "name": f"other-{n}", "created_at": "2026-10-01T11:01:00Z"} for n in range(2, 101)]
    jobs = {
        1: {
            "total_count": 2,
            "jobs": [{"started_at": "2026-10-01T10:00:00Z", "completed_at": "2026-10-01T10:06:00Z"}],
        },
        2: {
            "total_count": 2,
            "jobs": [{"started_at": "2026-10-01T11:00:00Z", "completed_at": "2026-10-01T11:06:00Z"}],
        },
    }
    pages = {
        1: {"total_count": 101, "artifacts": [stale, *filler]},
        2: {"total_count": 101, "artifacts": [approved]},
    }

    def api(root, endpoint):
        if "/jobs" in endpoint:
            return jobs[int(endpoint.split("/attempts/")[1].split("/")[0])]
        return pages[int(endpoint.rsplit("page=", 1)[1])]

    second = attempt_artifacts(None, "fixtures/runtime", 42, 2, api)
    assert [a["id"] for a in second if a["name"] == "protected-status"] == [150]
    first = attempt_artifacts(None, "fixtures/runtime", 42, 1, api)
    assert [a["id"] for a in first if a["name"] == "protected-status"] == [1]
