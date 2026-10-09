"""verify-and-close distils a long pull request body without failing the step.

The harvest step caps the change summary at 3500 characters and the key
decisions at 1500. GitHub runs the step under `bash -e -o pipefail`, so a cap
taken with `| head -c` let head exit early, the upstream writers took SIGPIPE
(exit 141), and any merged pull request with a long description failed
verify-and-close after a passing verify. These tests run the step's own script
against a stand-in `gh`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "verify-and-close.yml"

SUMMARY_CAP, DECISIONS_CAP = 3500, 1500
SHA = "a1" * 20


def harvest_script() -> str:
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["verify-and-close"]["steps"]
    return next(step for step in steps if step.get("id") == "harvest")["run"]


#: Above a 64 KiB pipe buffer, so a writer is still blocked when a capping head
#: exits and always takes SIGPIPE; below Linux's 128 KiB limit on one
#: environment string, so the body can reach the step as PR_BODY_INPUT.
PIPE_BUFFER, ENV_STRING_LIMIT = 64 * 1024, 128 * 1024


def long_body() -> str:
    """A body far over both caps, so the writers are still writing when a head would exit."""
    summary = "\n".join(f"Change line {n}: the merged work explained at length." for n in range(1000))
    decisions = "\n".join(f"Decision {n}: chose the simpler path for a stated reason." for n in range(1000))
    body = f"## Summary\n\n{summary}\n\n## Decisions\n\n{decisions}\n\n## Test plan\n\n- ran it\n"
    assert PIPE_BUFFER + SUMMARY_CAP < len(body.encode()) < ENV_STRING_LIMIT
    return body


def run_harvest(tmp_path: Path, pr_body: str) -> subprocess.CompletedProcess[str]:
    stub = tmp_path / "bin"
    stub.mkdir()
    gh = stub / "gh"
    # The pull request lookup finds nothing, so the body comes from the caller input.
    gh.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    gh.chmod(0o755)
    environment = {
        "PATH": f"{stub}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(tmp_path / "github_output"),
        "RUNNER_TEMP": str(tmp_path),
        "GH_REPO": "three-cubes/demo",
        "ISSUE_ID": "PLA-1",
        "SHA": SHA,
        "PR_BODY_INPUT": pr_body,
        "VERIFY_OUTCOME": "success",
        "VERIFIER_VERDICT": "pass",
        "RUN_URL": "https://github.com/three-cubes/demo/actions/runs/1",
    }
    bash = shutil.which("bash") or "bash"
    return subprocess.run(
        [bash, "-e", "-o", "pipefail", "-c", harvest_script()],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def section(harvest: str, start: str, end: str) -> str:
    return harvest.split(start, 1)[1].split(end, 1)[0]


def test_a_long_pull_request_body_is_capped_without_failing_the_step(tmp_path: Path) -> None:
    result = run_harvest(tmp_path, long_body())
    assert result.returncode == 0, f"harvest exited {result.returncode}: {result.stderr}"
    harvest = (tmp_path / "harvest.md").read_text(encoding="utf-8")
    summary = section(harvest, "**Change summary**\n\n", "\n\n**Verification:**")
    decisions = section(harvest, "**Key decisions**\n\n", "\n\n---\n").lstrip("\n")
    assert summary.startswith("## Summary") and len(summary) <= SUMMARY_CAP
    assert len(summary) > SUMMARY_CAP - 100, "the summary carries the body up to the cap"
    assert decisions.startswith("Decision 0:") and len(decisions) <= DECISIONS_CAP
    assert len(decisions) > DECISIONS_CAP - 100, "the decisions carry the section up to the cap"


def test_a_short_pull_request_body_is_kept_whole(tmp_path: Path) -> None:
    body = "Fixes the thing.\n\n## Decisions\n\nKept the old flag.\n"
    result = run_harvest(tmp_path, body)
    assert result.returncode == 0, result.stderr
    harvest = (tmp_path / "harvest.md").read_text(encoding="utf-8")
    assert section(harvest, "**Change summary**\n\n", "\n\n**Verification:**") == body.rstrip("\n")
    assert section(harvest, "**Key decisions**\n\n", "\n\n---\n").strip() == "Kept the old flag."


def test_no_step_caps_a_pipeline_with_head() -> None:
    """Any `| head` inside a pipefail run block can SIGPIPE its writers; cap in bash instead."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "| head -c" not in text, "fix: capture the full text, then cap with ${var:0:N}"
