"""What `agent-token` writes to stdout and stderr: the bare form hands over a token, `--git-config` never does (PLA-570)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from tc_agent_tools import agent_token as at

pytestmark = pytest.mark.contract

TOKEN = "ghs_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"  # pragma: allowlist secret (a fake token)
TOKEN_SHAPE = re.compile(r"gh[pousr]_[A-Za-z0-9]{3,}")


@pytest.fixture
def minted(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The seam where a token would be minted; records each repository it was asked for."""
    asked: list[str] = []

    def mint(agent: at.AgentApp, repo: str, *, api: str = at.API, guarded: bool = True) -> str:
        asked.append(repo)
        return TOKEN

    monkeypatch.setattr(at, "mint_token", mint)
    return asked


@pytest.mark.parametrize("agent", [[], ["--agent", "shape"]])
def test_git_config_sets_the_identity_and_prints_no_token(
    agent: list[str],
    minted: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "checkout"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.chdir(repo)

    assert at.main([*agent, "--git-config", "--repo", "three-cubes/kairix"]) == 0

    captured = capsys.readouterr()
    for stream in (captured.out, captured.err):
        assert TOKEN not in stream
        assert not TOKEN_SHAPE.search(stream)
    assert captured.out == ""
    assert minted == [], "--git-config must not mint a token at all"
    name = subprocess.run(
        ["git", "config", "--local", "user.name"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert name == "three-cubes-agent[bot]"


def test_the_bare_form_writes_only_the_token_to_stdout_for_capture(
    minted: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    # Callers run GH_TOKEN=$(agent-token --repo ...): stdout is exactly the token and a newline.
    assert at.main(["--repo", "three-cubes/kairix"]) == 0

    captured = capsys.readouterr()
    assert captured.out == f"{TOKEN}\n"
    assert captured.err == ""
    assert minted == ["three-cubes/kairix"]
