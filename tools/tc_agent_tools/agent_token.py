#!/usr/bin/env python3
"""Mint a short-lived per-agent GitHub App installation token.

This lower-level command is for a trusted off-CI host broker and restricted
platform-operator diagnosis. It reads App credentials from Azure Key Vault via
``az`` and prints an approximately one-hour installation token, so it is not a
direct agent-harness interface. The broker must capture the token in memory,
bind it to one subprocess, and keep its Azure session outside the harness.

The GitHub Actions complement is the ``github-app-token`` composite, which uses
WIF and confines the token to authorised workflow steps.

Per-agent Apps (SGO-163): pass `--agent builder|shape|consultant|growth` to mint as
that agent's own App identity, resolving the Key Vault secrets
`github-app-<agent>-id` / `github-app-<agent>-key`. ``--repo`` is required and
limits the installation token to exactly one repository in the trusted
``three-cubes`` organisation. With no `--agent`, the canonical org App
(`three-cubes-agent`) is used from its legacy secret names. ``--git-config``
always writes the canonical ``three-cubes-agent[bot]`` metadata, independent of
the selected remote actor.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass

import jwt  # PyJWT

VAULT = "kv-tc-agents"
API = "https://api.github.com"
CANONICAL = "three-cubes-agent"
TRUSTED_OWNER = "three-cubes"
CANONICAL_GIT_NAME = "three-cubes-agent[bot]"
CANONICAL_GIT_EMAIL = "295831460+three-cubes-agent[bot]@users.noreply.github.com"


@dataclass(frozen=True)
class AgentApp:
    """A GitHub App identity + how to source its credentials from Key Vault."""

    key: str  # CLI selector
    app_id_secret: str  # KV secret holding the App ID
    private_key_secret: str  # KV secret holding the App private key (.pem)
    bot_slug: str  # App slug identifying the authenticated remote actor
    installation_id_secret: str | None = None  # explicit id secret; None => discover


def _per_agent(key: str, slug: str) -> AgentApp:
    """Build a per-agent App descriptor from the github-app-<agent>-{id,key} contract."""
    return AgentApp(
        key=key,
        app_id_secret=f"github-app-{key}-id",
        private_key_secret=f"github-app-{key}-key",
        bot_slug=slug,
    )


# The canonical org App keeps its legacy secret names (back-compat); the four
# per-agent Apps follow the github-app-<agent>-{id,key} convention from
# governance/agent-sdlc-access-and-hitl.md.
AGENTS: dict[str, AgentApp] = {
    CANONICAL: AgentApp(
        key=CANONICAL,
        app_id_secret="github-threecubes-agent-app-id",
        private_key_secret="github-threecubes-agent-private-key",
        installation_id_secret="github-threecubes-agent-installation-id",
        bot_slug="three-cubes-agent",
    ),
    "builder": _per_agent("builder", "tc-agent-builder"),
    "shape": _per_agent("shape", "tc-agent-shape"),
    "consultant": _per_agent("consultant", "tc-agent-consultant"),
    "growth": _per_agent("growth", "tc-agent-growth"),
}


def resolve_agent(name: str | None) -> AgentApp:
    """Map a CLI selector to its AgentApp; default = the canonical org App."""
    key = name or CANONICAL
    try:
        return AGENTS[key]
    except KeyError:
        choices = ", ".join(k for k in AGENTS if k != CANONICAL)
        raise SystemExit(
            f"agent-token: unknown --agent '{key}' (expected one of: {choices}; "
            f"omit --agent for the canonical {CANONICAL} App)"
        ) from None


def jwt_claims(app_id: str, now: int) -> dict[str, int | str]:
    """The App-JWT claim set: 1-min backdated iat, 9-min exp (GitHub caps at 10)."""
    return {"iat": now - 60, "exp": now + 540, "iss": app_id}


def repository_scope(value: str) -> str:
    """Validate the one-repository scope accepted by the trusted broker."""
    parts = value.split("/")
    if (
        len(parts) != 2
        or parts[0] != TRUSTED_OWNER
        or parts[1] in {".", ".."}
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", parts[1])
    ):
        raise argparse.ArgumentTypeError(
            f"expected {TRUSTED_OWNER}/REPO for one repository in the trusted org"
        )
    return value


def kv(name: str) -> str:
    """Read a secret value from the agent Key Vault via the local `az` login."""
    return subprocess.check_output(
        [
            "az", "keyvault", "secret", "show",
            "--vault-name", VAULT, "--name", name, "--query", "value", "-o", "tsv",
        ],
        text=True,
    ).strip()


def _api(path: str, token: str, *, bearer: bool = False) -> dict | list:
    """GET a GitHub API resource with an App JWT (bearer) or installation token."""
    scheme = "Bearer" if bearer else "token"
    req = urllib.request.Request(  # noqa: S310 — fixed api.github.com base, not user input
        f"{API}{path}",
        headers={
            "Authorization": f"{scheme} {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req) as r:  # noqa: S310 — fixed api.github.com base
        return json.load(r)


def _post(path: str, assertion: str, payload: dict) -> dict:
    """POST to a GitHub API resource with an App JWT bearer assertion."""
    req = urllib.request.Request(  # noqa: S310 — fixed api.github.com base, not user input
        f"{API}{path}",
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {assertion}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req) as r:  # noqa: S310 — fixed api.github.com base
        return json.load(r)


def resolve_installation_id(agent: AgentApp, assertion: str, repo: str) -> str:
    """Find the installation id: explicit KV secret, else discover via the App JWT."""
    if agent.installation_id_secret:
        return kv(agent.installation_id_secret)
    return str(_api(f"/repos/{repo}/installation", assertion, bearer=True)["id"])


def apply_git_config() -> None:
    """Set canonical agent commit metadata in the current repository."""
    try:
        subprocess.run(
            ["git", "config", "--local", "user.name", CANONICAL_GIT_NAME], check=True
        )
        subprocess.run(
            ["git", "config", "--local", "user.email", CANONICAL_GIT_EMAIL],
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise SystemExit(
            f"agent-token: --git-config failed to set canonical git metadata ({exc}); "
            f"run inside a git repo, or drop --git-config and set it by hand."
        ) from None
    print(
        f"agent-token: git metadata set to {CANONICAL_GIT_NAME} "
        f"<{CANONICAL_GIT_EMAIL}>",
        file=sys.stderr,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="agent-token",
        description=(
            "Mint a short-lived per-agent GitHub App installation token for a "
            "trusted host broker or platform operator."
        ),
    )
    p.add_argument(
        "--agent",
        choices=[k for k in AGENTS if k != CANONICAL],
        default=None,
        help=f"per-agent App to mint as (default: the canonical {CANONICAL} App)",
    )
    p.add_argument(
        "--repo",
        required=True,
        type=repository_scope,
        metavar="OWNER/REPO",
        help=f"required single-repository token scope ({TRUSTED_OWNER}/REPO)",
    )
    p.add_argument(
        "--git-config",
        action="store_true",
        help="set repository-local metadata to the canonical three-cubes-agent[bot] identity",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    agent = resolve_agent(args.agent)

    app_id = kv(agent.app_id_secret)
    pem = kv(agent.private_key_secret)

    assertion = jwt.encode(jwt_claims(app_id, int(time.time())), pem, algorithm="RS256")
    inst_id = resolve_installation_id(agent, assertion, args.repo)
    repo_name = args.repo.split("/", maxsplit=1)[1]
    token = _post(
        f"/app/installations/{inst_id}/access_tokens",
        assertion,
        {"repositories": [repo_name]},
    )["token"]

    if args.git_config:
        apply_git_config()

    print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
