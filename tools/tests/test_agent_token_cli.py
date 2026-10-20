"""The `agent-token` command line: which App it mints as, and which repository it scopes to."""

from __future__ import annotations

import os

import pytest
from tc_agent_tools import agent_token as at

pytestmark = pytest.mark.unit


def test_default_agent_is_canonical() -> None:
    agent = at.resolve_agent(None)
    assert agent.key == at.CANONICAL
    assert agent.bot_slug == "three-cubes-agent"
    # The canonical App keeps its legacy secret names and an explicit installation-id secret.
    assert agent.app_id_secret == "github-threecubes-agent-app-id"
    key_name = "github-threecubes-agent-private-key"  # pragma: allowlist secret (a secret name)
    assert agent.private_key_secret == key_name
    assert agent.installation_id_secret == "github-threecubes-agent-installation-id"


@pytest.mark.parametrize(
    ("selector", "slug"),
    [
        ("builder", "tc-agent-builder"),
        ("shape", "tc-agent-shape"),
        ("consultant", "tc-agent-consultant"),
        ("growth", "tc-agent-growth"),
    ],
)
def test_per_agent_secret_name_contract(selector: str, slug: str) -> None:
    agent = at.resolve_agent(selector)
    assert agent.app_id_secret == f"github-app-{selector}-id"
    assert agent.private_key_secret == f"github-app-{selector}-key"
    assert agent.bot_slug == slug
    # A per-agent App discovers its installation for the required repository at run time.
    assert agent.installation_id_secret is None


def test_unknown_agent_is_actionable() -> None:
    with pytest.raises(SystemExit) as exc:
        at.resolve_agent("nope")
    message = str(exc.value)
    assert "unknown --agent 'nope'" in message
    assert "builder" in message and "growth" in message


def test_jwt_claims_window() -> None:
    claims = at.jwt_claims("12345", now=1_000_000)
    assert claims == {"iat": 999_940, "exp": 1_000_540, "iss": "12345"}
    # GitHub caps an App JWT at ten minutes.
    assert int(claims["exp"]) - int(claims["iat"]) <= 600


def test_parse_args_defaults_and_choices() -> None:
    args = at.parse_args(["--repo", "three-cubes/tc-pipelines"])
    assert args.agent is None and args.git_config is False
    assert args.repo == "three-cubes/tc-pipelines"

    args = at.parse_args(["--agent", "shape", "--git-config", "--repo", "three-cubes/kairix"])
    assert args.agent == "shape" and args.git_config is True
    assert args.repo == "three-cubes/kairix"

    # The canonical App is the default, never a --agent choice.
    with pytest.raises(SystemExit):
        at.parse_args(["--agent", at.CANONICAL, "--repo", "three-cubes/tc-pipelines"])


def test_parse_args_requires_repository_scope() -> None:
    with pytest.raises(SystemExit):
        at.parse_args([])


@pytest.mark.parametrize(
    "repo",
    ["tc-pipelines", "other-org/tc-pipelines", "three-cubes/too/many", "three-cubes/", "three-cubes/.."],
)
def test_parse_args_rejects_repo_outside_trusted_org(repo: str) -> None:
    with pytest.raises(SystemExit):
        at.parse_args(["--repo", repo])


def test_unguarded_az_is_resolved_only_from_the_fixed_search_path(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # agent-token's path: an agent-writable directory ahead of the real CLI on PATH must not be able to proxy az.
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "az").write_text("#!/bin/sh\nexit 99\n")
    (shadow / "az").chmod(0o755)
    monkeypatch.setenv("PATH", f"{shadow}:/usr/bin")
    monkeypatch.setattr(at, "AZ_SEARCH_PATH", str(tmp_path / "nowhere"))
    with pytest.raises(FileNotFoundError, match="az not found"):
        at.az_executable(guarded=False)
    real = tmp_path / "real"
    real.mkdir()
    (real / "az").write_text("#!/bin/sh\nexit 0\n")
    (real / "az").chmod(0o755)
    monkeypatch.setattr(at, "AZ_SEARCH_PATH", str(real))
    assert at.az_executable(guarded=False) == str(real / "az")


def _pin(tmp_path, az: str) -> str:
    etc = tmp_path / "etc" / "tc-agent-tools"
    etc.mkdir(parents=True)
    pin = etc / "az"
    pin.write_text(az + "\n")
    return str(pin)


def test_guarded_az_is_the_root_owned_pin_and_nothing_else(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    # queue-pr's path: the operator vouches for one az, as root; the fixed search path and PATH are not consulted.
    homebrew = tmp_path / "homebrew" / "bin"
    homebrew.mkdir(parents=True)
    (homebrew / "az").write_text("#!/bin/sh\nexit 0\n")
    (homebrew / "az").chmod(0o755)
    monkeypatch.setattr(at, "AZ_SEARCH_PATH", str(tmp_path / "nowhere"))
    pin = _pin(tmp_path, str(homebrew / "az"))
    monkeypatch.setattr(at, "AZ_PIN", pin)
    monkeypatch.setattr(at, "owned_by_root", lambda path: True)
    assert at.az_executable() == str(homebrew / "az")
    assert at.pinned_az(pin) == str(homebrew / "az")


@pytest.mark.parametrize(
    ("layout", "message"),
    [
        ("missing", "is missing, so no Azure CLI is trusted"),
        ("not-root", "not root-owned and root-only writable"),
        ("relative", "not an absolute path to an executable"),
        ("not-executable", "not an absolute path to an executable"),
    ],
)
def test_anything_short_of_a_root_owned_pin_of_an_executable_is_refused(
    layout: str, message: str, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(at, "owned_by_root", lambda path: layout != "not-root")
    if layout == "missing":
        pin = str(tmp_path / "etc" / "tc-agent-tools" / "az")
    elif layout == "relative":
        pin = _pin(tmp_path, "bin/az")
    elif layout == "not-executable":
        plain = tmp_path / "az.txt"
        plain.write_text("not a program\n")
        pin = _pin(tmp_path, str(plain))
    else:
        pin = _pin(tmp_path, "/bin/sh")
    with pytest.raises(PermissionError, match=message) as exc:
        at.pinned_az(pin)
    assert "sudo tee" in str(exc.value)  # the remedy is the one command the operator runs


def test_owned_by_root_reads_the_real_owner_and_mode(tmp_path) -> None:
    mine = tmp_path / "pin"
    mine.write_text("/bin/sh\n")
    mine.chmod(0o644)
    assert at.owned_by_root(str(mine)) == (os.geteuid() == 0)  # the gate's own uid decides
    mine.chmod(0o666)
    assert at.owned_by_root(str(mine)) is False  # group/other-writable is never trusted, whoever owns it


def test_a_path_the_caller_cannot_write_passes_the_writability_check(monkeypatch: pytest.MonkeyPatch) -> None:
    # Independent of who runs the gate (CI is root): a non-root caller, a path and directory it cannot write.
    monkeypatch.setattr(at.os, "geteuid", lambda: 501)
    monkeypatch.setattr(at.os, "access", lambda path, mode: False)
    assert at.not_writable_by_caller("/opt/tc-agent-tools/bin/queue-pr") == "/opt/tc-agent-tools/bin/queue-pr"


def test_root_is_the_operator_so_the_writability_check_is_vacuous(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writable = tmp_path / "queue-pr"
    writable.write_text("#!/bin/sh\n")
    monkeypatch.setattr(at.os, "geteuid", lambda: 0)
    assert at.not_writable_by_caller(str(writable)) == str(writable)
    monkeypatch.setattr(at.os, "geteuid", lambda: 501)
    with pytest.raises(PermissionError):
        at.not_writable_by_caller(str(writable))


def test_the_opener_never_logs_tls_keys_even_when_the_environment_asks(tmp_path, monkeypatch) -> None:
    keylog = tmp_path / "keys.log"
    monkeypatch.setenv("SSLKEYLOGFILE", str(keylog))
    handlers = [h for h in at.opener().handlers if isinstance(h, at.urllib.request.HTTPSHandler)]
    assert len(handlers) == 1
    assert handlers[0]._context.keylog_filename is None
    assert not keylog.exists()
    assert os.environ["SSLKEYLOGFILE"] == str(keylog)  # the caller's environment is left as it was


def test_az_runs_in_a_broker_owned_environment(monkeypatch) -> None:
    hostile = {
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "ALL_PROXY": "socks5://127.0.0.1:9",
        "REQUESTS_CA_BUNDLE": "/tmp/evil.pem",
        "AZURE_CLI_DISABLE_CONNECTION_VERIFICATION": "1",
        "PATH": "/tmp/shadow:/usr/bin",
        "HOME": "/tmp/hostile-home",  # a caller-selected tree holding its own account cache and extensions
        "AZURE_CONFIG_DIR": "/tmp/hostile-home/.azure",
        "TMPDIR": "/tmp/hostile-home/tmp",
        "USER": "operator",
    }
    env = at.az_environment(hostile, home="/Users/operator")
    assert env == {
        "USER": "operator",
        "PATH": at.AZ_SEARCH_PATH,
        "HOME": "/Users/operator",
        "AZURE_CONFIG_DIR": "/Users/operator/.azure",
    }
    # Without an explicit home, the account database decides, not the environment.
    assert at.az_environment(hostile)["HOME"] == at.account_home() != hostile["HOME"]


def test_agent_token_serves_from_the_operators_own_az_but_queue_pr_needs_the_pin(
    tmp_path, monkeypatch
) -> None:
    # A Homebrew-owned az is caller-writable. agent-token prints the token to that caller, so no guard
    # buys anything and it resolves az itself; queue-pr holds the credentials in-process and runs only
    # the az the operator pinned as root.
    own = tmp_path / "homebrew" / "bin"
    own.mkdir(parents=True)
    (own / "az").write_text("#!/bin/sh\nexit 0\n")
    (own / "az").chmod(0o755)
    monkeypatch.setattr(at, "AZ_SEARCH_PATH", str(own))
    monkeypatch.setattr(at, "AZ_PIN", str(tmp_path / "etc" / "tc-agent-tools" / "az"))
    assert at.az_executable(guarded=False) == str(own / "az")
    with pytest.raises(PermissionError, match="no Azure CLI is trusted on this host"):
        at.az_executable()
