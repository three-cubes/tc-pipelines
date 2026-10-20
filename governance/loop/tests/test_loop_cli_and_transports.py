"""The loop's command lines, ledger file and dispatch transport at their real boundaries.

Each CLI runs through its ``main`` with the harness proof or the Linear tree
transport handed in through the seam ``main`` exposes; the ledger is a real file;
the GitHub dispatch goes over HTTP to a local server. Nothing in the loop is patched.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import loop_dispatcher as disp
import loop_runner as runner_mod
import tree_reconciler as rec
from loop_governor import GovernorState, JsonFileStateStore, StateStoreError

pytestmark = pytest.mark.integration

ISSUE = {
    "id": "SGO-198",
    "title": "wave zero",
    "statusType": "backlog",
    "priority": {"value": 2},
    "createdAt": "2026-07-01T21:44:39.154Z",
    "labels": ["adp-wave-0"],
    "description": "**Repos:** tc-fitness",
    "gitBranchName": "dan/sgo-198-wave-zero",
    "url": "https://linear.app/x/SGO-198",
}


@pytest.fixture
def snapshot(tmp_path: Path) -> str:
    path = tmp_path / "issues.json"
    path.write_text(json.dumps({"issues": [ISSUE]}), encoding="utf-8")
    return str(path)


@pytest.fixture
def no_linear(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "LINEAR_API_KEY",
        "LOOP_DISPATCH_TOKEN",
        "LOOP_DISPATCH_REPO",
        "LOOP_STATE_FILE",
        "LOOP_SINK",
    ):
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------------- #
# The governor's ledger file
# --------------------------------------------------------------------------- #
def test_a_ledger_that_is_not_a_json_object_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "loop-state.json"
    path.write_text("[1, 2]", encoding="utf-8")

    with pytest.raises(StateStoreError, match="not a JSON object"):
        JsonFileStateStore(path).load()


def test_a_failed_save_leaves_no_temporary_file(tmp_path: Path) -> None:
    target = tmp_path / "loop-state.json"
    target.mkdir()  # the final rename cannot replace a directory

    with pytest.raises(OSError):
        JsonFileStateStore(target).save(GovernorState())

    assert sorted(p.name for p in tmp_path.iterdir()) == ["loop-state.json"]


# --------------------------------------------------------------------------- #
# The dispatcher CLI
# --------------------------------------------------------------------------- #
def test_the_dispatcher_exits_3_when_a_dispatch_is_refused(
    snapshot: str, no_linear: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert disp.main(["--issues-file", snapshot], guardrails_validator=lambda: False) == 3
    assert "auto-dispatch REFUSED" in capsys.readouterr().out


def test_a_linear_key_selects_the_live_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    key = "lin_fixture"  # pragma: allowlist secret (a fixture)
    monkeypatch.setenv("LINEAR_API_KEY", key)

    dispatcher_source = disp._source_from_args(argparse.Namespace(issues_file=None))
    runner_source = runner_mod._source_from(None)

    assert isinstance(dispatcher_source, disp.HttpLinearSource)
    assert isinstance(runner_source, disp.HttpLinearSource)
    assert dispatcher_source.api_key == runner_source.api_key == key


# --------------------------------------------------------------------------- #
# The runner CLI
# --------------------------------------------------------------------------- #
def test_a_tick_with_no_source_reports_idle_as_json(
    no_linear: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert runner_mod.main(["--json"], guardrails_validator=lambda: True) == 0

    doc = json.loads(capsys.readouterr().out)
    assert doc["decision"] == "idle" and doc["armed"] is False


def test_the_real_sink_refuses_to_build_without_its_token(snapshot: str, no_linear: None) -> None:
    with pytest.raises(SystemExit, match="requires LOOP_DISPATCH_TOKEN"):
        runner_mod.main(
            ["--issues-file", snapshot, "--sink", "github-actions"], guardrails_validator=lambda: True
        )


def test_the_real_sink_refuses_to_build_without_its_repository(
    snapshot: str, no_linear: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOOP_DISPATCH_TOKEN", "ghs_fixture")  # pragma: allowlist secret (a fixture)

    with pytest.raises(SystemExit, match="requires --dispatch-repo"):
        runner_mod.main(
            ["--issues-file", snapshot, "--sink", "github-actions"], guardrails_validator=lambda: True
        )


@pytest.fixture
def github() -> Iterator[tuple[str, list[dict]]]:
    """A local GitHub REST API that accepts a workflow dispatch with 204."""
    requests: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers["Content-Length"])
            requests.append(
                {
                    "path": self.path,
                    "authorization": self.headers["Authorization"],
                    "body": json.loads(self.rfile.read(length)),
                }
            )
            self.send_response(204)
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", requests
    server.shutdown()
    server.server_close()


def test_the_real_sink_dispatches_the_executor_workflow_over_http(github: tuple[str, list[dict]]) -> None:
    url, requests = github
    contract = disp.DispatchContract(
        issue_id="PLA-5",
        title="work",
        repo="kairix",
        branch="dan/pla-5-work",
        acceptance_criteria="linear:PLA-5",
        wave=1,
        priority=2,
        url="",
    )
    sink = runner_mod.GitHubActionsDispatchSink(
        token="ghs_fixture",  # pragma: allowlist secret (a fixture)
        repo="three-cubes/agent-platform",
        api_url=url,
    )

    result = sink.dispatch(contract)

    assert result.spawned
    [request] = requests
    assert (
        request["path"] == "/repos/three-cubes/agent-platform/actions/workflows/loop-implement.yml/dispatches"
    )
    assert request["body"]["ref"] == "main"
    assert request["body"]["inputs"]["issue-id"] == "PLA-5"
    assert request["authorization"].endswith("ghs_fixture")


# --------------------------------------------------------------------------- #
# The reconciler CLI
# --------------------------------------------------------------------------- #
class StaticTree:
    """A tree transport the CLI builds from the API key, serving a fixed tree."""

    built_with: ClassVar[list[str]] = []

    def __init__(self, api_key: str) -> None:
        StaticTree.built_with.append(api_key)

    def fetch(self, initiative_id: str) -> list[rec.TreeIssue]:
        return [rec.TreeIssue(id="PLA-1", state_type="started", status_name="In Progress")]


def test_a_live_read_needs_the_delegation_export(no_linear: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINEAR_API_KEY", "lin_fixture")  # pragma: allowlist secret (a fixture)

    with pytest.raises(SystemExit, match="needs --delegations-file"):
        rec.main(["--json"], tree_source=StaticTree)


@pytest.mark.parametrize(
    ("delegations", "branches"),
    [
        (
            {"delegations": [{"id": "d1", "issue_id": "PLA-1", "branch": "dan/pla-1-x"}]},
            [{"name": "dan/pla-1-x"}],
        ),
        ([{"id": "d1", "issue_id": "PLA-1", "branch": "dan/pla-1-x"}], {"other": {"name": "dan/pla-1-x"}}),
    ],
    ids=["wrapped-delegations", "keyed-branches"],
)
def test_a_live_read_reconciles_the_tree_against_the_exports(
    delegations: object,
    branches: object,
    tmp_path: Path,
    no_linear: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY", "lin_fixture")  # pragma: allowlist secret (a fixture)
    (tmp_path / "delegations.json").write_text(json.dumps(delegations), encoding="utf-8")
    (tmp_path / "branches.json").write_text(json.dumps(branches), encoding="utf-8")
    StaticTree.built_with = []

    rc = rec.main(
        [
            "--json",
            "--delegations-file",
            str(tmp_path / "delegations.json"),
            "--branches-file",
            str(tmp_path / "branches.json"),
        ],
        tree_source=StaticTree,
    )

    assert rc == 0
    assert StaticTree.built_with == ["lin_fixture"]
    report = json.loads(capsys.readouterr().out)
    counts = report["counts"]
    assert (counts["issues"], counts["delegations"], counts["branches"]) == (1, 1, 1)
