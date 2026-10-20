"""verify-and-close closes every pull request a grouped merge-queue push landed.

A merge queue can land several green pull requests as one push to main, each as
its own merge commit on main's first-parent chain. The reusable's `merged-prs`
job lists those merge commits, and its verify-and-close job runs once per commit,
so no merged pull request's Linear issue is left open. These tests run the job's
own script against a stand-in `gh`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
# In agent-platform the reusable workflows live at the repository root, two levels
# above execution/pipelines/; in the public tc-pipelines export REPO_ROOT is that
# root. Resolve whichever layout this file runs in.
PLATFORM_ROOT = REPO_ROOT if (REPO_ROOT / ".github" / "workflows").is_dir() else REPO_ROOT.parents[1]
WORKFLOW = PLATFORM_ROOT / ".github" / "workflows" / "verify-and-close.yml"

BEFORE, M1, M2, M3, BRANCH = "b0" * 20, "a1" * 20, "a2" * 20, "a3" * 20, "c1" * 20


def jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def commit(sha: str, *parents: str) -> dict:
    return {"sha": sha, "parent": parents[0] if parents else ""}


#: A three-entry queue group: each merge commit's first parent is the previous
#: one, and the merged branch's own commit is not on main's first-parent chain.
GROUPED = [commit(BRANCH, BEFORE), commit(M1, BEFORE), commit(M2, M1), commit(M3, M2)]
PULLS = {M1: 11, M2: 12, M3: 13, BRANCH: 11}


def list_merge_commits(
    tmp_path: Path,
    compare: list[dict] | None,
    pulls: dict[str, int] = PULLS,
    failing: tuple[str, ...] = (),
    **env: str,
) -> list[str]:
    """Run the merged-prs step with a stand-in gh: `compare` answers the compare API as
    the step's --jq emits it, one record per line (None: the API fails), and `pulls`
    maps a commit to its pull request."""
    step = next(s for s in jobs()["merged-prs"]["steps"] if s.get("id") == "list")
    stub = tmp_path / "bin"
    stub.mkdir(parents=True)
    answers = tmp_path / "answers"
    answers.mkdir()
    if compare is not None:
        (answers / "compare").write_text("".join(json.dumps(c) + "\n" for c in compare), encoding="utf-8")
    for sha, number in pulls.items():
        (answers / sha).write_text(f"{number}\n", encoding="utf-8")
    for sha in failing:
        (answers / f"{sha}.fail").write_text("", encoding="utf-8")
    gh = stub / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        f'  *compare/*) [ -f "{answers}/compare" ] || exit 1; cat "{answers}/compare" ;;\n'
        f'  *pulls*) args="$*"; sha="${{args#*commits/}}"; sha="${{sha%%/pulls*}}"; [ -f "{answers}/$sha.fail" ] && exit 1; [ -f "{answers}/$sha" ] && cat "{answers}/$sha" ;;\n'
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    output = tmp_path / "github_output"
    defaults = {"GH_REPO": "three-cubes/demo", "HEAD_SHA": M3, "BEFORE_SHA": BEFORE}
    environment = {
        "PATH": f"{stub}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(output),
        **defaults,
        **env,
    }
    subprocess.run([shutil.which("bash") or "bash", "-c", step["run"]], env=environment, check=True)
    line = next(line for line in output.read_text(encoding="utf-8").splitlines() if line.startswith("shas="))
    return json.loads(line.removeprefix("shas="))


def test_a_grouped_push_verifies_and_closes_each_merged_pull_request_in_merge_order(tmp_path: Path) -> None:
    assert list_merge_commits(tmp_path, GROUPED) == [M1, M2, M3]


def test_a_single_merge_is_one_entry(tmp_path: Path) -> None:
    assert list_merge_commits(tmp_path, [commit(BRANCH, BEFORE), commit(M1, BEFORE)], HEAD_SHA=M1) == [M1]


def test_a_rebase_merge_is_verified_once_at_its_final_commit(tmp_path: Path) -> None:
    """A rebase merge puts each of the pull request's commits on main's chain."""
    chain = [commit(M1, BEFORE), commit(M2, M1), commit(M3, M2)]
    assert list_merge_commits(tmp_path, chain, pulls={M1: 7, M2: 7, M3: 8}) == [M2, M3]


def test_a_failed_pull_request_lookup_keeps_the_commit_and_the_head_is_always_verified(
    tmp_path: Path,
) -> None:
    """A transient lookup failure must not drop a commit: the head stays verified."""
    assert list_merge_commits(tmp_path / "head", GROUPED, failing=(M3,)) == [M1, M2, M3]
    assert list_merge_commits(tmp_path / "middle", GROUPED, failing=(M2,)) == [M1, M2, M3]
    unlinked_head = {M1: 11, M2: 12}
    assert list_merge_commits(tmp_path / "unlinked", GROUPED, pulls=unlinked_head) == [M1, M2, M3]


def test_a_comparison_over_one_page_is_read_in_full(tmp_path: Path) -> None:
    """GitHub returns at most 250 commits per comparison page; the step pages through all."""
    step = next(s for s in jobs()["merged-prs"]["steps"] if s.get("id") == "list")
    assert "gh api --paginate " in step["run"] and "per_page=100" in step["run"]
    branch = [commit(f"{n:040x}", BEFORE) for n in range(1, 301)]
    assert list_merge_commits(tmp_path, [*branch, *GROUPED[1:]]) == [M1, M2, M3]


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"MERGED_SHA_INPUT": M2}, [M2]),
        ({"OVERRIDES": "PLA-1"}, [M3]),
        ({"BEFORE_SHA": "0" * 40}, [M3]),
        ({"BEFORE_SHA": ""}, [M3]),
    ],
    ids=["named commit", "named issue or branch", "new branch", "no before"],
)
def test_a_caller_override_or_a_push_without_before_is_one_entry(
    tmp_path: Path, env: dict[str, str], expected: list[str]
) -> None:
    assert list_merge_commits(tmp_path, GROUPED, **env) == expected


def test_an_unreadable_comparison_a_broken_chain_or_no_pull_request_verifies_the_head(tmp_path: Path) -> None:
    assert list_merge_commits(tmp_path / "api", None) == [M3]
    rewritten = [commit(M2, "ff" * 20), commit(M3, M2)]
    assert list_merge_commits(tmp_path / "forced", rewritten) == [M3]
    assert list_merge_commits(tmp_path / "direct", GROUPED, pulls={}) == [M3]


def test_the_verify_and_close_job_runs_once_per_merge_commit() -> None:
    job = jobs()["verify-and-close"]
    assert job["needs"] == ["merged-prs"]
    assert job["strategy"]["matrix"]["merged-sha"] == "${{ fromJSON(needs.merged-prs.outputs.shas) }}"
    assert job["strategy"]["fail-fast"] is False
    assert job["strategy"]["max-parallel"] == 1
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "inputs.merged-sha || github.sha" not in text, "fix: read the commit from matrix.merged-sha"
    checkout = next(step for step in job["steps"] if step.get("name") == "Checkout merged commit")
    assert checkout["with"]["ref"] == "${{ matrix.merged-sha }}"
