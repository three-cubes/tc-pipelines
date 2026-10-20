"""`queue-pr`: enrol one pull request in its repository's merge queue, as the App.

The one bounded GitHub write an agent session may run on its own. It takes a
pull-request number, the reviewed head SHA and one of two allowlisted
repositories, and nothing else. It mints the App token for that repository,
checks that the pull request's head is still the reviewed one, and arms
auto-merge bound to that head through GitHub's GraphQL API, so the queue takes
the pull request when its checks pass and refuses it if the head moves. The
token never leaves this process: no child executable, no environment, no output.

It runs from an installation outside any checkout (`uv tool install` of this
package), and the Claude Code permission that allows it lives in the host's
user-level settings, so nothing an agent can edit in a worktree changes what
the allowed command does or widens what is allowed (merge-queue runbook).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path

import jwt

from tc_agent_tools import agent_token
from tc_agent_tools.agent_token import (
    AGENTS,
    API,
    CANONICAL,
    TIMEOUT_SECONDS,
    mint_token,
    not_writable_by_caller,
    opener,
    resolve_agent,
)

# The repositories this operation may queue into; anything else is refused by the parser.
# The queue-enabled product repositories (ADR-0003): kairix adopts the queue; so do the two platform repos.
REPOSITORIES = ("three-cubes/agent-platform", "three-cubes/tc-agent-zone", "three-cubes/kairix")
REPOSITORY = REPOSITORIES[0]

GraphQL = Callable[[str, dict[str, object], str, str], dict]

_LOOKUP = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { name }
    pullRequest(number: $number) {
      id state headRefOid mergeStateStatus baseRefName
      author { __typename login }
    }
  }
}
"""
# The remote actors that may author a pull request queue-pr enrols: the agent Apps.
# A human-authored pull request is recreated through the broker, never queued by it.
AGENT_AUTHORS = frozenset(app.bot_slug for app in AGENTS.values())
_ARM = """
mutation($id: ID!, $head: GitObjectID!) {
  enablePullRequestAutoMerge(input: {pullRequestId: $id, expectedHeadOid: $head, mergeMethod: MERGE}) {
    pullRequest { autoMergeRequest { enabledAt } }
  }
}
"""
_ENQUEUE = """
mutation($id: ID!, $head: GitObjectID!) {
  enqueuePullRequest(input: {pullRequestId: $id, expectedHeadOid: $head}) {
    mergeQueueEntry { state position }
  }
}
"""


class QueueRefused(Exception):
    """The pull request is not in a state this operation may queue."""


def installation_is_trusted() -> None:
    """Refuse to run from an installation the invoking user could have modified.

    The allowed command is only a boundary if the harness UID cannot change what it
    does: the executable, this package and the interpreter must be owned by someone
    else (the runbook installs them root-owned under /opt). A per-user `uv tool
    install` fails here on purpose.
    """
    import os

    for path in (
        sys.argv[0] if sys.argv and sys.argv[0] else sys.executable,
        sys.executable,
        __file__,
        agent_token.__file__,
    ):
        not_writable_by_caller(os.path.realpath(path))


def pull_request_number(value: str) -> int:
    """A positive integer and nothing else: no flags, no `owner/repo#n`, no URL."""
    if not value.isdigit() or int(value) <= 0:
        raise argparse.ArgumentTypeError(f"expected a pull-request number, got {value!r}")
    return int(value)


def head_sha(value: str) -> str:
    """A full 40-hex commit SHA: the head the readiness check reviewed."""
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise argparse.ArgumentTypeError(f"expected the reviewed head as a 40-hex SHA, got {value!r}")
    return value


def repository(value: str) -> str:
    """One of the allowlisted repositories, spelled exactly."""
    if value not in REPOSITORIES:
        raise argparse.ArgumentTypeError(f"expected one of {', '.join(REPOSITORIES)}, got {value!r}")
    return value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="queue-pr",
        description="Enrol one pull request in its repository's merge queue as the App.",
    )
    p.add_argument("number", nargs="?", type=pull_request_number, help="the pull-request number")
    p.add_argument(
        "--head",
        type=head_sha,
        metavar="SHA",
        help="the reviewed head; another head is refused",
    )
    p.add_argument(
        "--verify-installation",
        action="store_true",
        help="only check that this installation is one the invoking user cannot modify, then exit",
    )
    p.add_argument(
        "--repo",
        default=REPOSITORY,
        type=repository,
        metavar="OWNER/REPO",
        help=f"one of {', '.join(REPOSITORIES)}",
    )
    args = p.parse_args(argv)
    if not args.verify_installation and (args.number is None or args.head is None):
        p.error("the following arguments are required: number, --head")
    return args


def _graphql(query: str, variables: dict[str, object], token: str, api: str) -> dict:
    """POST one GraphQL document to the fixed GitHub API host; the token goes nowhere else."""
    if not api.startswith(("https://", "http://127.0.0.1", "http://localhost")):
        raise QueueRefused(f"refusing to send the App token to {api!r}")
    req = urllib.request.Request(
        f"{api}/graphql",
        method="POST",
        data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    with opener().open(req, timeout=TIMEOUT_SECONDS) as r:
        return json.load(r)


def queue(
    number: int, head: str, repo: str = REPOSITORY, *, graphql: GraphQL = _graphql, api: str = API
) -> None:
    """Arm auto-merge on `repo`#`number`, bound to `head`. Raises QueueRefused when it must not."""
    token = mint_token(resolve_agent(CANONICAL), repo, api=api)
    owner, name = repo.split("/", maxsplit=1)
    found = graphql(_LOOKUP, {"owner": owner, "name": name, "number": number}, token, api)
    repository = (found.get("data") or {}).get("repository") or {}
    pr = repository.get("pullRequest")
    if not pr:
        raise QueueRefused(f"{repo}#{number} was not found")
    if pr["state"] != "OPEN":
        raise QueueRefused(f"{repo}#{number} is {pr['state'].lower()}, not open")
    if pr["headRefOid"] != head:
        raise QueueRefused(f"{repo}#{number} is at {pr['headRefOid'][:8]}, not the reviewed {head[:8]}")
    # Only the default branch carries the merge-queue ruleset; auto-merge into any other
    # branch would be a direct merge, so the operation is refused there.
    queued_branch = (repository.get("defaultBranchRef") or {}).get("name")
    if not queued_branch or pr.get("baseRefName") != queued_branch:
        raise QueueRefused(
            f"{repo}#{number} targets {pr.get('baseRefName')!r}, not the queue-protected {queued_branch!r}"
        )
    # Only an agent App's pull request is enrolled; a human-authored one stays with its author.
    author = pr.get("author") or {}
    if author.get("__typename") != "Bot" or author.get("login") not in AGENT_AUTHORS:
        raise QueueRefused(
            f"{repo}#{number} was opened by {author.get('login') or 'an unknown actor'}, not an agent App"
        )
    # A pull request whose checks have passed goes straight into the queue; one still
    # waiting on checks is armed to enter it when they pass. Both are bound to `head`.
    document = _ENQUEUE if pr.get("mergeStateStatus") == "CLEAN" else _ARM
    result = graphql(document, {"id": pr["id"], "head": head}, token, api)
    if result.get("errors"):
        raise QueueRefused("; ".join(e.get("message", "unknown error") for e in result["errors"]))
    # GitHub may answer 200 with a null payload; success is the mutation's confirmation object.
    data = result.get("data") or {}
    if document is _ENQUEUE:
        confirmed = (data.get("enqueuePullRequest") or {}).get("mergeQueueEntry")
    else:
        confirmed = ((data.get("enablePullRequestAutoMerge") or {}).get("pullRequest") or {}).get(
            "autoMergeRequest"
        )
    if not confirmed:
        raise QueueRefused(f"GitHub returned no confirmation for {repo}#{number}; it was not enrolled")
    return document is _ENQUEUE


def _sibling(name: str) -> str:
    """The absolute path of a console script installed beside this one (the install's bin is not on PATH)."""
    return str(Path(sys.argv[0]).resolve().parent / name)


def main(argv: Sequence[str] | None = None, *, graphql: GraphQL = _graphql, api: str = API) -> int:
    args = parse_args(argv)
    try:
        installation_is_trusted()
        if args.verify_installation:
            # The host bootstrap's verification: the refusal above is the only thing it asks.
            print("PASS queue-pr: trusted installation")
            return 0
        entered = queue(args.number, args.head, args.repo, graphql=graphql, api=api)
    except PermissionError as exc:
        print(
            f"FAIL queue-pr: untrusted installation: {exc}. next: see tools/README.md#queue-pr",
            file=sys.stderr,
        )
        return 1
    except (QueueRefused, urllib.error.URLError, TimeoutError, subprocess.TimeoutExpired) as exc:
        print(
            f"FAIL queue-pr: {exc}. fix: check the pull request is open at {args.head[:8]} with no unresolved "
            "threads, required checks green and any code-owner review given; re-run the readiness check if the "
            f"head moved. next: gh pr view {args.number} --repo {args.repo} --json headRefOid,mergeStateStatus",
            file=sys.stderr,
        )
        return 1
    except (FileNotFoundError, subprocess.CalledProcessError, KeyError, ValueError, jwt.PyJWTError) as exc:
        # The credential provider (az, Key Vault, the App token exchange) failed; say so without any value.
        print(
            f"FAIL queue-pr: could not mint the App token ({type(exc).__name__}). fix: `az login` as an operator "
            "with Key Vault Secrets User on the agent vault, with the Azure CLI installed in a system bin "
            f"directory. next: {_sibling('agent-token')} --repo {args.repo} >/dev/null && echo ok",
            file=sys.stderr,
        )
        return 1
    if entered:
        print(f"queued: {args.repo}#{args.number} at {args.head[:8]} entered the merge queue")
    else:
        print(
            f"armed: {args.repo}#{args.number} at {args.head[:8]} enters the merge queue when its checks pass"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
