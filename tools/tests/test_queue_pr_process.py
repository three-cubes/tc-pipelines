"""`queue-pr` as hosts run it: the installed console script, built from this package."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest
from tc_agent_tools import queue_pr as qp

pytestmark = pytest.mark.integration

SHA = "0123456789abcdef0123456789abcdef01234567"  # pragma: allowlist secret (a fixture SHA)
PACKAGE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def installed_queue_pr(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Install tc-agent-tools into an isolated tool directory, as the runbook has an operator do."""
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not on PATH")
    root = tmp_path_factory.mktemp("tools")
    env = {**os.environ, "UV_TOOL_DIR": str(root / "tools"), "UV_TOOL_BIN_DIR": str(root / "bin")}
    subprocess.run(
        [uv, "tool", "install", "--quiet", "--from", str(PACKAGE), "tc-agent-tools"], env=env, check=True
    )
    exe = root / "bin" / "queue-pr"
    assert exe.is_file(), "the packaged queue-pr entry point was not generated"
    return exe


def test_the_installed_command_refuses_an_admin_flag(installed_queue_pr: Path) -> None:
    result = subprocess.run(
        [str(installed_queue_pr), "182", "--head", SHA, "--admin"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unrecognized arguments: --admin" in result.stderr


def test_the_installed_command_refuses_a_repository_outside_the_allowlist(installed_queue_pr: Path) -> None:
    result = subprocess.run(
        [str(installed_queue_pr), "182", "--head", SHA, "--repo", "three-cubes/tc-fitness"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert (
        "expected one of three-cubes/agent-platform, three-cubes/tc-agent-zone, three-cubes/kairix"
        in result.stderr
    )


def test_the_module_entry_point_matches_the_installed_command() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tc_agent_tools.queue_pr", "182", "--head", SHA, "--admin"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unrecognized arguments: --admin" in result.stderr


class _Handler(BaseHTTPRequestHandler):
    """A stand-in GitHub GraphQL endpoint that answers the lookup, then the arm."""

    seen: ClassVar[list[dict[str, Any]]] = []

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Handler.seen.append({"auth": self.headers.get("Authorization"), "body": body})
        if "pullRequest(number" in body["query"]:
            pr = {
                "id": "PR_1",
                "state": "OPEN",
                "headRefOid": SHA,
                "baseRefName": "main",
                "author": {"__typename": "Bot", "login": "three-cubes-agent"},
            }
            data = {"repository": {"defaultBranchRef": {"name": "main"}, "pullRequest": pr}}
        else:
            data = {"enablePullRequestAutoMerge": {"pullRequest": {"autoMergeRequest": {"enabledAt": "now"}}}}
        payload = json.dumps({"data": data}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:  # quiet
        return


@pytest.fixture
def github() -> Iterator[str]:
    _Handler.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()


def test_queue_posts_both_graphql_documents_to_the_api_host_with_the_minted_token(
    github: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(qp, "installation_is_trusted", lambda: None)
    monkeypatch.setattr(
        qp, "mint_token", lambda agent, repo, *, api: "ghs_local_fixture"
    )  # pragma: allowlist secret
    assert qp.main(["182", "--head", SHA], api=github) == 0
    assert [s["auth"] for s in _Handler.seen] == ["Bearer ghs_local_fixture"] * 2
    assert "enablePullRequestAutoMerge" in _Handler.seen[1]["body"]["query"]
    assert _Handler.seen[1]["body"]["variables"] == {"id": "PR_1", "head": SHA}


def test_an_unreachable_api_host_is_an_actionable_failure_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(qp, "installation_is_trusted", lambda: None)
    monkeypatch.setattr(
        qp, "mint_token", lambda agent, repo, *, api: "ghs_local_fixture"
    )  # pragma: allowlist secret
    probe = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = probe.server_port
    probe.server_close()  # nothing listens here now
    assert qp.main(["182", "--head", SHA], api=f"http://127.0.0.1:{port}") == 1
    err = capsys.readouterr().err
    assert "FAIL queue-pr" in err and "next:" in err


def test_credential_requests_ignore_environment_proxies_and_ca_overrides(
    github: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A proxy that would swallow the request, and a CA file that would break TLS trust: neither is honoured.
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    bogus = tmp_path / "ca.pem"
    bogus.write_text("not a certificate\n")
    monkeypatch.setenv("SSL_CERT_FILE", str(bogus))
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path))
    monkeypatch.setattr(qp, "installation_is_trusted", lambda: None)
    monkeypatch.setattr(
        qp, "mint_token", lambda agent, repo, *, api: "ghs_local_fixture"
    )  # pragma: allowlist secret
    assert qp.main(["182", "--head", SHA], api=github) == 0
    assert len(_Handler.seen) == 2
