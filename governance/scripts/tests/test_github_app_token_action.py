"""The github-app-token composite's vault step, run as the runner runs it.

The step's own bash body executes against a stand-in `az` that serves a vault, and
its $GITHUB_OUTPUT is read back: the token is minted with the App's client ID when
the vault holds one, and with the App ID otherwise, since
actions/create-github-app-token deprecates `app-id`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTION = REPO_ROOT / ".github" / "actions" / "github-app-token" / "action.yml"
# The step masks and passes the key through, so any multi-line value serves.
PEM = "fake-private-key-line-1\nfake-private-key-line-2"


def action() -> dict:
    return yaml.safe_load(ACTION.read_text(encoding="utf-8"))


def vault_step() -> dict:
    return next(step for step in action()["runs"]["steps"] if step.get("id") == "kv")


def run_vault_step(tmp_path: Path, secrets: dict[str, str], agent: str = "") -> dict[str, str]:
    store = tmp_path / "vault.json"
    store.write_text(json.dumps(secrets), encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    az = bin_dir / "az"
    az.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "args = sys.argv[1:]\n"
        f"secrets = json.load(open({str(store)!r}))\n"
        "name = args[args.index('--name') + 1]\n"
        "if name not in secrets: sys.exit(3)\n"
        "print(secrets[name])\n",
        encoding="utf-8",
    )
    az.chmod(0o755)
    output = tmp_path / "github_output"
    output.touch()
    inputs = {i: str(v.get("default", "")) for i, v in action()["inputs"].items()}
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(output),
        "KV": "kv-test",
        "AGENT": agent,
        "APP_ID_SECRET": inputs["app-id-secret"],
        "CLIENT_ID_SECRET": inputs["client-id-secret"],
        "PK_SECRET": inputs["private-key-secret"],
    }
    result = subprocess.run(
        ["bash", "-c", vault_step()["run"]], capture_output=True, text=True, env=env, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    values: dict[str, str] = {}
    lines = output.read_text(encoding="utf-8").splitlines()
    for line in lines:
        if "=" in line and "<<" not in line:
            key, _, value = line.partition("=")
            values[key] = value
    return values


def test_the_token_is_minted_with_the_client_id_when_the_vault_holds_one(tmp_path: Path) -> None:
    out = run_vault_step(
        tmp_path,
        {
            "github-threecubes-agent-client-id": "Iv23liExample",
            "github-threecubes-agent-app-id": "1234567",
            "github-threecubes-agent-private-key": PEM,
        },
    )
    assert out.get("client-id") == "Iv23liExample"
    assert "app-id" not in out


def test_a_vault_without_a_client_id_falls_back_to_the_app_id(tmp_path: Path) -> None:
    out = run_vault_step(
        tmp_path,
        {"github-threecubes-agent-app-id": "1234567", "github-threecubes-agent-private-key": PEM},
    )
    assert out.get("app-id") == "1234567"
    assert "client-id" not in out


def test_a_per_agent_app_reads_its_own_client_id(tmp_path: Path) -> None:
    out = run_vault_step(
        tmp_path,
        {
            "github-app-builder-client-id": "Iv23liBuilder",
            "github-app-builder-id": "7654321",
            "github-app-builder-key": PEM,
        },
        agent="builder",
    )
    assert out.get("client-id") == "Iv23liBuilder"


def test_exactly_one_mint_step_runs_and_only_the_fallback_names_app_id() -> None:
    """Naming `app-id` warns even when empty, so the client-ID mint must not name it."""
    steps = {step.get("id"): step for step in action()["runs"]["steps"]}
    by_client_id, by_app_id = steps["app-token"], steps["app-token-by-app-id"]
    assert by_client_id["if"] == "steps.kv.outputs.client-id != ''"
    assert by_app_id["if"] == "steps.kv.outputs.client-id == ''"
    assert "app-id" not in by_client_id["with"] and by_client_id["with"]["client-id"]
    assert "client-id" not in by_app_id["with"] and by_app_id["with"]["app-id"]
    for name, output in action()["outputs"].items():
        assert output["value"] == (
            f"${{{{ steps.app-token.outputs.{name} || steps.app-token-by-app-id.outputs.{name} }}}}"
        ), name
