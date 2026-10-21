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
writes the canonical ``three-cubes-agent[bot]`` metadata, independent of the
selected remote actor, and mints and prints no token. Only the bare form writes
the token, to stdout, for ``GH_TOKEN=$(agent-token --repo …)``. No other output, and no error path, carries a
credential: a failure prints the kind of failure, never its message or traceback (PLA-689).
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.request
from collections.abc import Mapping
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
        private_key_secret="github-threecubes-agent-private-key",  # pragma: allowlist secret (a secret name)
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


# Where `az` may live: the system-managed prefixes of the platforms the broker runs
# on. The inherited PATH is never searched, and the executable must not be writable
# by the invoking user, so an agent-writable directory or file can never stand in
# for the real CLI and read the App credentials Key Vault returns. Tests point this
# at their stand-in.
AZ_SEARCH_PATH = ":".join(
    (
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/snap/bin",
        "/home/linuxbrew/.linuxbrew/bin",
    )
)
# One bound for every network and child-process operation the broker performs.
TIMEOUT_SECONDS = 60.0


def not_writable_by_caller(path: str) -> str:
    """`path`, after checking the invoking user cannot modify it or its directory.

    Root can modify anything, so the check is vacuous for root: a root session is
    the operator identity the boundary protects, not the harness UID it protects
    against (CI runs the gate as root).
    """
    if os.geteuid() == 0:
        return path
    for candidate in (path, os.path.dirname(path)):
        if os.access(candidate, os.W_OK):
            raise PermissionError(
                f"{candidate} is writable by the invoking user; "
                "fix: install it root-owned (tools/README.md#queue-pr)"
            )
    return path


# The Azure CLI an operator vouches for, as root, once per host: a root-owned file whose
# one line is the absolute path of the `az` queue-pr may run. Nothing a session can
# write (it cannot write /etc) changes it, and no pin means no Key Vault read.
AZ_PIN = "/etc/tc-agent-tools/az"


def owned_by_root(path: str) -> bool:
    """True when `path` is owned by uid 0 and writable by nobody else (a seam for tests)."""
    st = os.stat(path)
    return st.st_uid == 0 and not st.st_mode & 0o022


def pinned_az(pin: str | None = None) -> str:
    """The Azure CLI the operator pinned at `pin` (default AZ_PIN); anything short of a root-owned pin is refused."""
    pin = AZ_PIN if pin is None else pin
    remedy = (
        "fix: as root, pin the Azure CLI this host trusts "
        f"(sudo mkdir -p {os.path.dirname(pin)} && echo /path/to/az | sudo tee {pin}); see tools/README.md#queue-pr"
    )
    if not os.path.isfile(pin):
        raise PermissionError(f"{pin} is missing, so no Azure CLI is trusted on this host; {remedy}")
    if not (owned_by_root(os.path.dirname(pin)) and owned_by_root(pin)):
        raise PermissionError(f"{pin} or its directory is not root-owned and root-only writable; {remedy}")
    with open(pin, encoding="utf-8") as f:
        az = f.read().strip()
    if not os.path.isabs(az) or not os.access(az, os.X_OK):
        raise PermissionError(f"{pin} names {az!r}, which is not an absolute path to an executable; {remedy}")
    return az


def az_executable(*, guarded: bool = True) -> str:
    """The Azure CLI to run.

    `guarded` (the default) is the root-owned pin, `AZ_PIN`: the guard for a command that
    holds the credentials it mints in-process (`queue-pr`). `agent-token` prints the token
    to its caller, so a caller-controlled az would protect nothing there; unguarded, it
    resolves `az` from the fixed system prefixes (`AZ_SEARCH_PATH`), never the inherited
    `PATH`, so the operator's own (for example Homebrew-owned) Azure CLI serves it.
    """
    if guarded:
        return pinned_az()
    found = shutil.which("az", path=AZ_SEARCH_PATH)
    if found is None:
        raise FileNotFoundError(
            f"az not found in {AZ_SEARCH_PATH}; fix: install the Azure CLI there and `az login`"
        )
    return found


# What the Azure CLI subprocess inherits: a fixed PATH, locale and identity names, and an
# Azure configuration root taken from the account database rather than the environment.
# Never the proxy, CA or verification overrides a harness could use to intercept the Key
# Vault exchange (az honours HTTP(S)_PROXY, REQUESTS_CA_BUNDLE and
# AZURE_CLI_DISABLE_CONNECTION_VERIFICATION), and never a caller-selected HOME,
# AZURE_CONFIG_DIR or TMPDIR, through which az would load a caller's account cache,
# command index or extensions (extensions are executable Python).
_AZ_ENV_PASSTHROUGH = ("USER", "LOGNAME", "LANG", "LC_ALL")


def account_home() -> str:
    """The invoking account's home directory per the account database, not `$HOME`."""
    return pwd.getpwuid(os.geteuid()).pw_dir


def az_environment(environ: Mapping[str, str] | None = None, *, home: str | None = None) -> dict[str, str]:
    """A broker-owned environment for `az`: passthrough names, the fixed PATH, the account's own `.azure`."""
    source = os.environ if environ is None else environ
    env = {k: source[k] for k in _AZ_ENV_PASSTHROUGH if k in source}
    env["PATH"] = AZ_SEARCH_PATH
    env["HOME"] = account_home() if home is None else home
    env["AZURE_CONFIG_DIR"] = os.path.join(env["HOME"], ".azure")
    return env


def kv(name: str, *, guarded: bool = True) -> str:
    """Read a secret value from the agent Key Vault via the local `az` login."""
    return subprocess.check_output(
        [
            az_executable(guarded=guarded),
            "keyvault",
            "secret",
            "show",
            "--vault-name",
            VAULT,
            "--name",
            name,
            "--query",
            "value",
            "-o",
            "tsv",
        ],
        text=True,
        timeout=TIMEOUT_SECONDS,
        env=az_environment(),
        # Whatever az says on failure is not ours to relay: the broker's own message names the cause.
        stderr=subprocess.DEVNULL,
    ).strip()


# Environment that would otherwise redirect, intercept or decrypt a credential-bearing
# request: proxy selection (urllib's ProxyHandler reads it), OpenSSL's CA override, and
# the TLS key log `ssl.create_default_context` would open. None is honoured; requests go
# direct, to the system trust store, with no key log.
_TLS_ENV = ("SSL_CERT_FILE", "SSL_CERT_DIR", "SSLKEYLOGFILE")


def opener() -> urllib.request.OpenerDirector:
    """A broker-owned opener: no environment proxies, the system CA store only."""
    saved = {k: os.environ.pop(k) for k in _TLS_ENV if k in os.environ}
    try:
        context = ssl.create_default_context()
    finally:
        os.environ.update(saved)
    if getattr(
        context, "keylog_filename", None
    ):  # pragma: no cover - never set once SSLKEYLOGFILE is stripped
        context.keylog_filename = None
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context)
    )


def _api(path: str, token: str, *, bearer: bool = False, api: str = API) -> dict | list:
    """GET a GitHub API resource with an App JWT (bearer) or installation token."""
    scheme = "Bearer" if bearer else "token"
    req = urllib.request.Request(
        f"{api}{path}",
        headers={
            "Authorization": f"{scheme} {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with opener().open(req, timeout=TIMEOUT_SECONDS) as r:
        return json.load(r)


def _post(path: str, assertion: str, payload: dict, *, api: str = API) -> dict:
    """POST to a GitHub API resource with an App JWT bearer assertion."""
    req = urllib.request.Request(
        f"{api}{path}",
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {assertion}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with opener().open(req, timeout=TIMEOUT_SECONDS) as r:
        return json.load(r)


def resolve_installation_id(
    agent: AgentApp, assertion: str, repo: str, *, api: str = API, guarded: bool = True
) -> str:
    """Find the installation id: explicit KV secret, else discover via the App JWT."""
    if agent.installation_id_secret:
        return kv(agent.installation_id_secret, guarded=guarded)
    return str(_api(f"/repos/{repo}/installation", assertion, bearer=True, api=api)["id"])


def apply_git_config() -> None:
    """Set canonical agent commit metadata in the current repository."""
    try:
        subprocess.run(["git", "config", "--local", "user.name", CANONICAL_GIT_NAME], check=True)
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
        f"agent-token: git metadata set to {CANONICAL_GIT_NAME} <{CANONICAL_GIT_EMAIL}>",
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


def mint_token(agent: AgentApp, repo: str, *, api: str = API, guarded: bool = True) -> str:
    """Mint one installation token for `agent`, scoped to the single repository `repo`.

    The caller holds the token in memory and hands it to one bounded operation;
    `queue_pr` does that for the merge queue, with the az guard on. `api` is the
    GitHub API base URL, a seam for tests; `guarded` is `az_executable`'s guard.
    """
    app_id = kv(agent.app_id_secret, guarded=guarded)
    pem = kv(agent.private_key_secret, guarded=guarded)

    assertion = jwt.encode(jwt_claims(app_id, int(time.time())), pem, algorithm="RS256")
    inst_id = resolve_installation_id(agent, assertion, repo, api=api, guarded=guarded)
    repo_name = repo.split("/", maxsplit=1)[1]
    return _post(
        f"/app/installations/{inst_id}/access_tokens",
        assertion,
        {"repositories": [repo_name]},
        api=api,
    )["token"]


def main(argv: list[str] | None = None, *, api: str = API) -> int:
    """Mint and print the token, or with `--git-config` set the identity and print no token.

    `api` is the GitHub API base URL, a seam for tests.
    """
    args = parse_args(argv)
    if args.git_config:
        # Identity only: no token is minted, so none can reach this command's output (PLA-570).
        apply_git_config()
        return 0
    agent = resolve_agent(args.agent)
    try:
        # Unguarded: the token goes to the caller on stdout, so the az guard would protect nothing here.
        token = mint_token(agent, args.repo, api=api, guarded=False)
    except (PermissionError, FileNotFoundError) as exc:
        # az missing or not executable: the message names a path and a remedy, never a credential.
        raise SystemExit(f"agent-token: {exc}") from None
    except Exception as exc:
        # Any other failure may carry a credential in its message, chain or traceback (a Key Vault
        # value, a response body): report the kind of failure only, with no traceback (PLA-689).
        raise SystemExit(
            f"agent-token: could not mint a token for {args.repo} ({type(exc).__name__}); "
            "check `az login` and the App's installation, then retry"
        ) from None
    print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
