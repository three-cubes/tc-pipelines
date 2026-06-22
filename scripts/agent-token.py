#!/usr/bin/env python3
"""Mint a short-lived three-cubes-agent GitHub App installation token.

Reads the App credentials from Azure Key Vault (kv-tc-agents) via `az` — so a local
or MCP agent that is `az login`'d (as a Key Vault Secrets reader) authenticates to
GitHub AS THE APP, never as a human. The App key never leaves the vault except as a
~9-minute in-memory assertion; the printed token is a ~1-hour installation token.

Usage:
    export GH_TOKEN="$(python3 agent-token.py)"
    git config user.name  'three-cubes-agent[bot]'
    git config user.email '<app-id>+three-cubes-agent[bot]@users.noreply.github.com'
    git push / gh pr create / gh pr merge ...   # now act as the App
"""
import json
import subprocess
import sys
import time
import urllib.request

import jwt  # PyJWT

VAULT = "kv-tc-agents"


def kv(name: str) -> str:
    return subprocess.check_output(
        ["az", "keyvault", "secret", "show", "--vault-name", VAULT,
         "--name", name, "--query", "value", "-o", "tsv"],
        text=True,
    ).strip()


def main() -> int:
    app_id = kv("github-threecubes-agent-app-id")
    inst_id = kv("github-threecubes-agent-installation-id")
    pem = kv("github-threecubes-agent-private-key")

    now = int(time.time())
    assertion = jwt.encode(
        {"iat": now - 60, "exp": now + 540, "iss": app_id}, pem, algorithm="RS256"
    )
    req = urllib.request.Request(
        f"https://api.github.com/app/installations/{inst_id}/access_tokens",
        method="POST",
        headers={
            "Authorization": f"Bearer {assertion}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req) as r:
        print(json.load(r)["token"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
