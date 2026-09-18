"""Behavioural tests for repository-scoped `agent-token` minting.

External network, Key Vault, and Git subprocess boundaries are replaced with
specific fakes; argument validation, installation selection, token-exchange
payloads, and local Git metadata remain real code under test.
"""

from __future__ import annotations

import io

import pytest

from tc_agent_tools import agent_token as at


def test_default_agent_is_canonical():
    agent = at.resolve_agent(None)
    assert agent.key == at.CANONICAL
    assert agent.bot_slug == "three-cubes-agent"
    # canonical keeps its legacy secret names + explicit installation-id secret
    assert agent.app_id_secret == "github-threecubes-agent-app-id"
    assert agent.private_key_secret == "github-threecubes-agent-private-key"
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
def test_per_agent_secret_name_contract(selector, slug):
    agent = at.resolve_agent(selector)
    assert agent.app_id_secret == f"github-app-{selector}-id"
    assert agent.private_key_secret == f"github-app-{selector}-key"
    assert agent.bot_slug == slug
    # per-agent Apps discover the installation for the required repository at runtime
    assert agent.installation_id_secret is None


def test_unknown_agent_is_actionable():
    with pytest.raises(SystemExit) as exc:
        at.resolve_agent("nope")
    msg = str(exc.value)
    assert "unknown --agent 'nope'" in msg
    assert "builder" in msg and "growth" in msg


def test_jwt_claims_window():
    claims = at.jwt_claims("12345", now=1_000_000)
    assert claims == {"iat": 999_940, "exp": 1_000_540, "iss": "12345"}
    # never exceeds GitHub's 10-minute ceiling
    assert claims["exp"] - claims["iat"] <= 600


def test_git_config_always_uses_canonical_metadata(monkeypatch):
    commands: list[list[str]] = []
    monkeypatch.setattr(
        at.subprocess, "run", lambda command, **_: commands.append(command)
    )

    at.apply_git_config()

    assert commands == [
        ["git", "config", "--local", "user.name", "three-cubes-agent[bot]"],
        [
            "git",
            "config",
            "--local",
            "user.email",
            "295831460+three-cubes-agent[bot]@users.noreply.github.com",
        ],
    ]


def test_parse_args_defaults_and_choices():
    args = at.parse_args(["--repo", "three-cubes/tc-pipelines"])
    assert args.agent is None and args.git_config is False
    assert args.repo == "three-cubes/tc-pipelines"

    args = at.parse_args(
        ["--agent", "shape", "--git-config", "--repo", "three-cubes/kairix"]
    )
    assert args.agent == "shape" and args.git_config is True
    assert args.repo == "three-cubes/kairix"

    # the canonical key is not a --agent choice (it's the default, selector-free)
    with pytest.raises(SystemExit):
        at.parse_args(
            ["--agent", at.CANONICAL, "--repo", "three-cubes/tc-pipelines"]
        )


def test_parse_args_requires_repository_scope():
    with pytest.raises(SystemExit):
        at.parse_args([])


@pytest.mark.parametrize(
    "repo",
    [
        "tc-pipelines",
        "other-org/tc-pipelines",
        "three-cubes/too/many",
        "three-cubes/",
        "three-cubes/..",
    ],
)
def test_parse_args_rejects_repo_outside_trusted_org(repo):
    with pytest.raises(SystemExit):
        at.parse_args(["--repo", repo])


@pytest.mark.parametrize("selector", [None, "builder"])
def test_main_scopes_token_exchange_to_requested_repository(
    monkeypatch, capsys, selector
):
    posts: list[tuple[str, str, dict[str, list[str]]]] = []
    api_calls: list[str] = []

    monkeypatch.setattr(
        at, "kv", lambda name: "4242" if name.endswith("id") else "pem"
    )
    monkeypatch.setattr(at.jwt, "encode", lambda *_args, **_kwargs: "assertion")

    def fake_api(path, _token, *, bearer=False):
        api_calls.append(path)
        assert bearer is True
        return {"id": 9876}

    monkeypatch.setattr(at, "_api", fake_api)

    def fake_post(path, assertion, payload):
        posts.append((path, assertion, payload))
        return {"token": "scoped-token"}

    monkeypatch.setattr(at, "_post", fake_post)

    argv = ["--repo", "three-cubes/tc-pipelines"]
    if selector:
        argv.extend(["--agent", selector])

    assert at.main(argv) == 0
    assert capsys.readouterr().out == "scoped-token\n"
    assert posts == [
        (
            "/app/installations/9876/access_tokens"
            if selector
            else "/app/installations/4242/access_tokens",
            "assertion",
            {"repositories": ["tc-pipelines"]},
        )
    ]
    assert api_calls == (
        ["/repos/three-cubes/tc-pipelines/installation"] if selector else []
    )


def test_post_serializes_repository_scope_in_token_exchange(monkeypatch):
    requests = []

    def fake_urlopen(request):
        requests.append(request)
        return io.BytesIO(b'{"token":"scoped-token"}')

    monkeypatch.setattr(at.urllib.request, "urlopen", fake_urlopen)

    result = at._post(
        "/app/installations/4242/access_tokens",
        "assertion",
        {"repositories": ["tc-pipelines"]},
    )

    assert result == {"token": "scoped-token"}
    assert len(requests) == 1
    assert requests[0].get_method() == "POST"
    assert requests[0].data == b'{"repositories": ["tc-pipelines"]}'
    assert requests[0].get_header("Content-type") == "application/json"
