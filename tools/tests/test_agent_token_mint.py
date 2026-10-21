"""`agent-token` mints a repository-scoped token through its real boundaries.

Key Vault is a stand-in `az` on the fixed az search path that serves secrets from a file, GitHub is a
local HTTP server reached through `main`'s `api` seam, and git is real. The App's
private key is generated per run, so the server verifies the App JWT exactly as
GitHub would. Nothing in the module under test is patched.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from tc_agent_tools import agent_token as at

pytestmark = pytest.mark.integration

TOKEN = "scoped-installation-token"  # pragma: allowlist secret (a fake token the server issues)


@dataclass
class GitHub:
    """A local GitHub API that checks each App JWT and records every request."""

    public_key: object
    app_ids: set[str]
    url: str = ""
    token_reply: dict = field(default_factory=lambda: {"token": TOKEN})
    requests: list[dict] = field(default_factory=list)


@pytest.fixture
def private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def github(private_key: rsa.RSAPrivateKey) -> Iterator[GitHub]:
    state = GitHub(public_key=private_key.public_key(), app_ids={"4242", "5151", "6161"})

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(201 if self.command == "POST" else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _record(self) -> dict:
            scheme, _, assertion = self.headers["Authorization"].partition(" ")
            claims = jwt.decode(assertion, state.public_key, algorithms=["RS256"])
            assert claims["iss"] in state.app_ids
            length = int(self.headers.get("Content-Length") or 0)
            request = {
                "method": self.command,
                "path": self.path,
                "scheme": scheme,
                "iss": claims["iss"],
                "content_type": self.headers.get("Content-Type"),
                "body": json.loads(self.rfile.read(length)) if length else None,
            }
            state.requests.append(request)
            return request

        def do_GET(self) -> None:
            self._record()
            self._reply({"id": 9876})

        def do_POST(self) -> None:
            self._record()
            self._reply(state.token_reply)

        def log_message(self, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield state
    server.shutdown()
    server.server_close()


@pytest.fixture
def vault(tmp_path: Path, private_key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An `az` on the fixed search path that answers `keyvault secret show` from a JSON file, and logs each read."""
    pem = private_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    secrets = {
        "github-threecubes-agent-app-id": "4242",
        "github-threecubes-agent-private-key": pem,
        "github-threecubes-agent-installation-id": "4242",
        "github-app-builder-id": "5151",
        "github-app-builder-key": pem,
        "github-app-shape-id": "6161",
        "github-app-shape-key": pem,
    }
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "secrets.json").write_text(json.dumps(secrets))
    az = bin_dir / "az"
    az.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        f"secrets = json.load(open({str(tmp_path / 'secrets.json')!r}))\n"
        f"with open({str(tmp_path / 'az.log')!r}, 'a') as log:\n"
        "    log.write(json.dumps({'args': args, 'env': dict(os.environ)}) + '\\n')\n"
        "print(secrets[args[args.index('--name') + 1]])\n"
    )
    az.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    # kv() resolves az only from the fixed search path, never from PATH; point it at the stand-in.
    monkeypatch.setattr(at, "AZ_SEARCH_PATH", str(bin_dir))
    # The stand-in lives in a tmp dir this test owns. `agent-token` (main) serves from it as from any
    # operator-owned az; `mint_token`'s default guard would refuse it, so the direct calls below pass
    # `guarded=False` where they mean the operator path.
    return tmp_path / "az.log"


def reads(log: Path) -> list[str]:
    calls = [json.loads(line)["args"] for line in log.read_text().splitlines()]
    assert all(call[:3] == ["keyvault", "secret", "show"] and call[4] == at.VAULT for call in calls)
    return [call[call.index("--name") + 1] for call in calls]


def az_environments(log: Path) -> list[dict[str, str]]:
    return [json.loads(line)["env"] for line in log.read_text().splitlines()]


def test_canonical_app_mints_a_token_for_exactly_the_requested_repository(  # 689:US1.3
    github: GitHub, vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert at.main(["--repo", "three-cubes/tc-pipelines"], api=github.url) == 0

    assert capsys.readouterr().out == f"{TOKEN}\n"
    assert reads(vault) == [
        "github-threecubes-agent-app-id",
        "github-threecubes-agent-private-key",
        "github-threecubes-agent-installation-id",
    ]
    assert github.requests == [
        {
            "method": "POST",
            "path": "/app/installations/4242/access_tokens",
            "scheme": "Bearer",
            "iss": "4242",
            "content_type": "application/json",
            "body": {"repositories": ["tc-pipelines"]},
        }
    ]


def test_per_agent_app_discovers_its_installation_from_the_repository(
    github: GitHub, vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert at.main(["--agent", "builder", "--repo", "three-cubes/kairix"], api=github.url) == 0

    assert capsys.readouterr().out == f"{TOKEN}\n"
    assert reads(vault) == ["github-app-builder-id", "github-app-builder-key"]
    assert [(r["method"], r["path"], r["scheme"], r["iss"], r["body"]) for r in github.requests] == [
        ("GET", "/repos/three-cubes/kairix/installation", "Bearer", "5151", None),
        ("POST", "/app/installations/9876/access_tokens", "Bearer", "5151", {"repositories": ["kairix"]}),
    ]


def test_git_config_writes_the_canonical_identity_whichever_app_mints(
    github: GitHub,
    vault: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "checkout"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.chdir(repo)

    assert at.main(["--agent", "shape", "--git-config", "--repo", "three-cubes/kairix"], api=github.url) == 0

    def local(key: str) -> str:
        return subprocess.run(
            ["git", "config", "--local", key], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()

    assert local("user.name") == "three-cubes-agent[bot]"
    assert local("user.email") == "295831460+three-cubes-agent[bot]@users.noreply.github.com"
    captured = capsys.readouterr()
    assert "git metadata set to three-cubes-agent[bot]" in captured.err
    assert captured.out == ""


def test_git_config_outside_a_repository_fails_with_its_remedy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "not-a-checkout"
    outside.mkdir()
    monkeypatch.chdir(outside)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))

    with pytest.raises(SystemExit) as exc:
        at.apply_git_config()

    assert "--git-config failed to set canonical git metadata" in str(exc.value)
    assert "run inside a git repo" in str(exc.value)


def test_the_module_runs_as_the_agent_token_command() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tc_agent_tools.agent_token", "--repo", "other-org/tc-pipelines"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "expected three-cubes/REPO for one repository in the trusted org" in result.stderr


def test_the_key_vault_exchange_never_sees_harness_proxy_or_trust_overrides(
    github: GitHub, vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A TLS-intercepting proxy and CA/verification overrides in the harness environment reach neither az nor GitHub.
    hostile = {
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "https_proxy": "http://127.0.0.1:9",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "ALL_PROXY": "socks5://127.0.0.1:9",
        "REQUESTS_CA_BUNDLE": "/nonexistent/evil.pem",
        "AZURE_CLI_DISABLE_CONNECTION_VERIFICATION": "1",
        "SSLKEYLOGFILE": "/nonexistent/keys.log",
    }
    for name, value in hostile.items():
        monkeypatch.setenv(name, value)
    # A caller-selected Azure configuration root (account cache, command index, extensions) is not honoured either.
    hostile_home = vault.parent / "hostile-home"
    (hostile_home / ".azure" / "cliextensions").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(hostile_home))
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(hostile_home / ".azure"))
    assert at.mint_token(
        at.resolve_agent(at.CANONICAL), "three-cubes/agent-platform", api=github.url, guarded=False
    )
    environments = az_environments(vault)
    assert environments, "az was never invoked"
    for env in environments:
        assert not set(env) & set(hostile), sorted(set(env) & set(hostile))
        assert env["PATH"] == at.AZ_SEARCH_PATH
        assert env["HOME"] == at.account_home() != str(hostile_home)
        assert env["AZURE_CONFIG_DIR"] == os.path.join(at.account_home(), ".azure")


def test_the_guarded_path_runs_only_the_pinned_az_that_agent_token_does_not_need(
    github: GitHub, vault: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # agent-token (main) mints through the stand-in on the fixed search path. queue-pr's guarded path
    # refuses without a root-owned pin, and mints through exactly the az the pin names once there is one.
    assert at.main(["--repo", "three-cubes/agent-platform"], api=github.url) == 0
    pin = tmp_path / "etc" / "tc-agent-tools" / "az"
    monkeypatch.setattr(at, "AZ_PIN", str(pin))
    with pytest.raises(PermissionError, match="no Azure CLI is trusted on this host"):
        at.mint_token(at.resolve_agent(at.CANONICAL), "three-cubes/agent-platform", api=github.url)
    pin.parent.mkdir(parents=True)
    pin.write_text(f"{vault.parent / 'bin' / 'az'}\n")
    monkeypatch.setattr(
        at, "owned_by_root", lambda path: True
    )  # the test cannot chown to root; CI runs as root anyway
    before = len(reads(vault))
    assert at.mint_token(at.resolve_agent(at.CANONICAL), "three-cubes/agent-platform", api=github.url)
    assert len(reads(vault)) > before


def _pem_body(private_key: rsa.RSAPrivateKey) -> str:
    pem = private_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    return "".join(pem.splitlines()[1:-1])


def _assert_no_credential(text: str, private_key: rsa.RSAPrivateKey) -> None:
    body = _pem_body(private_key)
    assert TOKEN not in text
    assert "PRIVATE KEY" not in text
    assert body[:40] not in text and body[-40:] not in text


def _run_cli(argv: list[str], api: str) -> tuple[int | str | None, str]:
    """Run `main` as the command does; return its exit status and everything it wrote, traceback included."""
    import traceback

    try:
        status: int | str | None = at.main(argv, api=api)
        trace = ""
    except SystemExit as exc:
        status, trace = exc.code, str(exc.code)  # the interpreter prints only this message
    except Exception as exc:  # an uncaught error would print this traceback to stderr
        status, trace = "uncaught", "".join(traceback.format_exception(exc))
    return status, trace


def test_git_config_prints_no_credential_even_with_a_live_token_source(  # 689:US1.1
    github: GitHub,
    vault: Path,
    private_key: rsa.RSAPrivateKey,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "checkout"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.chdir(repo)

    assert at.main(["--git-config", "--repo", "three-cubes/kairix"], api=github.url) == 0

    captured = capfd.readouterr()
    _assert_no_credential(captured.out + captured.err, private_key)
    assert github.requests == [] and not vault.exists(), "--git-config touched neither GitHub nor Key Vault"
    configured = subprocess.run(
        ["git", "config", "--local", "--list"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout
    _assert_no_credential(configured, private_key)


@pytest.mark.parametrize("failure", ["github-down", "no-secret", "bad-key", "no-token-in-reply"])
def test_no_error_path_prints_the_token_or_the_private_key(  # 689:US1.2
    failure: str,
    github: GitHub,
    vault: Path,
    private_key: rsa.RSAPrivateKey,
    capfd: pytest.CaptureFixture[str],
) -> None:
    api = github.url
    secrets_file = vault.parent / "secrets.json"
    secrets = json.loads(secrets_file.read_text())
    if failure == "github-down":
        api = "http://127.0.0.1:9"
    elif failure == "no-secret":
        del secrets["github-threecubes-agent-private-key"]
        secrets_file.write_text(json.dumps(secrets))
    elif failure == "bad-key":
        # A damaged key still carries the real key material in its text.
        key = secrets["github-threecubes-agent-private-key"]
        secrets["github-threecubes-agent-private-key"] = key[: len(key) // 2]
        secrets_file.write_text(json.dumps(secrets))
    else:
        assert failure == "no-token-in-reply"
        github.token_reply = {"message": f"unexpected reply mentioning {TOKEN}"}

    status, trace = _run_cli(["--repo", "three-cubes/agent-platform"], api)

    captured = capfd.readouterr()
    everything = captured.out + captured.err + trace
    _assert_no_credential(everything, private_key)
    assert status != 0 and status != "uncaught", "a failure exits non-zero through SystemExit"
    assert captured.out == ""
    assert "Traceback" not in everything, "a failure reports its kind, never a traceback"
    assert str(status).startswith("agent-token: could not mint a token for three-cubes/agent-platform (")


def test_a_missing_az_exits_with_its_remedy_and_no_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(at, "AZ_SEARCH_PATH", str(tmp_path))

    status, trace = _run_cli(["--repo", "three-cubes/agent-platform"], at.API)

    assert status == trace and str(status).startswith("agent-token: az not found in ")
    assert "install the Azure CLI" in trace


def test_an_az_that_cannot_run_exits_with_its_path_and_no_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    not_executable = tmp_path / "az"
    not_executable.write_text("#!/bin/sh\n")
    not_executable.chmod(0o644)
    monkeypatch.setattr(at, "az_executable", lambda *, guarded=True: str(not_executable))

    status, trace = _run_cli(["--repo", "three-cubes/agent-platform"], at.API)

    assert status == trace and str(status).startswith("agent-token: ")
    assert str(not_executable) in trace and "Permission denied" in trace
