"""`queue-pr`: one bounded merge-queue enrolment, as the App, bound to the reviewed head."""

from __future__ import annotations

import urllib.error
from pathlib import Path
from typing import Any

import pytest
from tc_agent_tools import agent_token as at
from tc_agent_tools import queue_pr as qp

pytestmark = pytest.mark.unit

SHA = "0123456789abcdef0123456789abcdef01234567"  # pragma: allowlist secret (a fixture SHA)
OTHER = "fedcba9876543210fedcba9876543210fedcba98"  # pragma: allowlist secret (a fixture SHA)


@pytest.fixture(autouse=True)
def _trusted_install(monkeypatch: pytest.MonkeyPatch) -> None:
    # This checkout is writable by the test user; production refuses that (tested below).
    monkeypatch.setattr(qp, "installation_is_trusted", lambda: None)


def test_a_caller_writable_installation_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()  # the real check, against this writable checkout
    monkeypatch.setattr(
        qp.agent_token.os, "geteuid", lambda: 501
    )  # as a non-root caller, whoever runs the gate
    with pytest.raises(PermissionError, match="writable by the invoking user"):
        qp.installation_is_trusted()


def _mint(monkeypatch: pytest.MonkeyPatch) -> None:
    # The token path is agent_token's; here it is a seam, so the test never reaches Key Vault.
    monkeypatch.setattr(qp, "mint_token", lambda agent, repo, *, api: f"ghs_test_for_{agent.key}_{repo}")


class _GitHub:
    """A recording GraphQL seam standing in for api.github.com."""

    def __init__(
        self,
        *,
        state: str = "OPEN",
        head: str = SHA,
        merge_state: str = "BLOCKED",
        arm_errors: list[dict[str, Any]] | None = None,
        arm_payload: dict[str, Any] | None = None,
        base: str = "main",
        author: dict[str, str] | None = None,
    ):
        self.state, self.head, self.merge_state, self.arm_errors = state, head, merge_state, arm_errors
        self.base = base
        self.author = {"__typename": "Bot", "login": "three-cubes-agent"} if author is None else author
        self.arm_payload = arm_payload  # a 200 whose mutation payload is empty or null
        self.calls: list[tuple[str, dict[str, Any], str, str]] = []

    def __call__(self, query: str, variables: dict[str, Any], token: str, api: str) -> dict[str, Any]:
        self.calls.append((query, variables, token, api))
        if "pullRequest(number" in query:
            pr = {
                "id": "PR_1",
                "state": self.state,
                "headRefOid": self.head,
                "mergeStateStatus": self.merge_state,
                "baseRefName": self.base,
                "author": self.author,
            }
            return {"data": {"repository": {"defaultBranchRef": {"name": "main"}, "pullRequest": pr}}}
        if self.arm_errors:
            return {"errors": self.arm_errors}
        if self.arm_payload is not None:
            return self.arm_payload
        if "enqueuePullRequest" in query:
            return {"data": {"enqueuePullRequest": {"mergeQueueEntry": {"state": "QUEUED", "position": 1}}}}
        return {
            "data": {
                "enablePullRequestAutoMerge": {"pullRequest": {"autoMergeRequest": {"enabledAt": "now"}}}
            }
        }


def test_queue_looks_the_pull_request_up_then_arms_auto_merge_bound_to_the_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mint(monkeypatch)
    github = _GitHub()
    qp.queue(182, SHA, graphql=github)
    lookup, arm = github.calls
    assert lookup[1] == {"owner": "three-cubes", "name": "agent-platform", "number": 182}
    assert "enablePullRequestAutoMerge" in arm[0]
    assert arm[1] == {"id": "PR_1", "head": SHA}
    assert "mergeMethod: MERGE" in arm[0]
    # The token is the App's, scoped to the repository being queued, and goes only to the API seam.
    assert {c[2] for c in github.calls} == {f"ghs_test_for_{at.CANONICAL}_three-cubes/agent-platform"}
    assert {c[3] for c in github.calls} == {qp.API}


@pytest.mark.parametrize("repo", ["three-cubes/tc-agent-zone", "three-cubes/kairix"])
def test_every_queue_enabled_repository_is_targeted_with_a_token_scoped_to_it(
    repo: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mint(monkeypatch)
    github = _GitHub()
    assert qp.parse_args(["17", "--head", SHA, "--repo", repo]).repo == repo
    qp.queue(17, SHA, repo, graphql=github)
    name = repo.split("/")[1]
    assert github.calls[0][1] == {"owner": "three-cubes", "name": name, "number": 17}
    assert {c[2] for c in github.calls} == {f"ghs_test_for_{at.CANONICAL}_{repo}"}


def test_a_moved_head_is_refused_before_anything_is_armed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mint(monkeypatch)
    github = _GitHub(head=OTHER)
    with pytest.raises(qp.QueueRefused, match="not the reviewed 01234567"):
        qp.queue(182, SHA, graphql=github)
    assert len(github.calls) == 1


@pytest.mark.parametrize("state", ["MERGED", "CLOSED"])
def test_a_pull_request_that_is_not_open_is_refused(monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    _mint(monkeypatch)
    with pytest.raises(qp.QueueRefused, match="not open"):
        qp.queue(182, SHA, graphql=_GitHub(state=state))


def test_a_missing_pull_request_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _mint(monkeypatch)
    with pytest.raises(qp.QueueRefused, match="was not found"):
        qp.queue(182, SHA, graphql=lambda q, v, t, a: {"data": {"repository": {"pullRequest": None}}})


@pytest.mark.parametrize("merge_state", ["CLEAN", "BLOCKED"])
def test_a_pull_request_into_any_branch_but_the_queued_default_is_refused_before_any_mutation(
    merge_state: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only the default branch carries the queue ruleset; auto-merge elsewhere would be a direct merge.
    _mint(monkeypatch)
    github = _GitHub(merge_state=merge_state, base="release/2026.10")
    with pytest.raises(qp.QueueRefused, match=r"targets 'release/2026\.10', not the queue-protected 'main'"):
        qp.queue(182, SHA, graphql=github)
    assert len(github.calls) == 1


@pytest.mark.parametrize(
    "author",
    [
        {"__typename": "User", "login": "quanyeomans"},
        {"__typename": "Bot", "login": "dependabot"},
        {"__typename": "User", "login": "three-cubes-agent"},  # the App's name claimed by a user account
        None,
    ],
)
def test_a_pull_request_not_authored_by_an_agent_app_is_refused_before_any_mutation(
    author: dict[str, str] | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mint(monkeypatch)
    github = _GitHub(author=author or {})
    with pytest.raises(qp.QueueRefused, match="not an agent App"):
        qp.queue(182, SHA, graphql=github)
    assert len(github.calls) == 1


@pytest.mark.parametrize("login", sorted(qp.AGENT_AUTHORS))
def test_every_agent_app_may_author_a_queued_pull_request(
    login: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mint(monkeypatch)
    github = _GitHub(author={"__typename": "Bot", "login": login})
    qp.queue(182, SHA, graphql=github)
    assert len(github.calls) == 2


def test_github_refusing_the_arm_is_reported_as_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    _mint(monkeypatch)
    github = _GitHub(arm_errors=[{"message": "Pull request is not mergeable"}])
    with pytest.raises(qp.QueueRefused, match="not mergeable"):
        qp.queue(182, SHA, graphql=github)


@pytest.mark.parametrize(
    ("merge_state", "payload"),
    [
        ("CLEAN", {"data": {"enqueuePullRequest": None}}),
        ("CLEAN", {"data": {"enqueuePullRequest": {"mergeQueueEntry": None}}}),
        ("BLOCKED", {"data": {"enablePullRequestAutoMerge": None}}),
        ("BLOCKED", {"data": {"enablePullRequestAutoMerge": {"pullRequest": {"autoMergeRequest": None}}}}),
        ("BLOCKED", {"data": None}),
        ("BLOCKED", {}),
    ],
)
def test_a_200_without_the_mutations_confirmation_is_a_refusal_not_a_success(
    merge_state: str, payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    # GitHub's mutation payload fields are nullable: no confirmation object, no "queued:"/"armed:".
    _mint(monkeypatch)
    with pytest.raises(qp.QueueRefused, match="no confirmation"):
        qp.queue(182, SHA, graphql=_GitHub(merge_state=merge_state, arm_payload=payload))


@pytest.mark.parametrize(
    "bad",
    [
        "--admin",
        "182 --admin",
        "-R",
        "other/repo#1",
        "0",
        "-1",
        "abc",
        "",
        "182",  # no --head: the enrolment must be bound to a reviewed head
        "182 --head abc123",  # a short SHA
        "182 --head main",  # a ref, not a commit
        f"182 --head {SHA} --admin",
        f"182 --head {SHA} --repo other-org/agent-platform",
        f"182 --head {SHA} --repo three-cubes/tc-fitness",  # three-cubes, but not queue-enabled
    ],
)
def test_anything_but_a_number_a_full_head_sha_and_an_allowlisted_repo_is_refused(bad: str) -> None:
    with pytest.raises(SystemExit) as exc:
        qp.parse_args(bad.split() if bad else [""])
    assert exc.value.code == 2


def test_main_reports_the_queued_pull_request_and_never_the_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _mint(monkeypatch)
    assert qp.main(["182", "--head", SHA], graphql=_GitHub(merge_state="CLEAN")) == 0
    out = capsys.readouterr()
    assert "queued: three-cubes/agent-platform#182 at 01234567 entered the merge queue" in out.out
    assert qp.main(["182", "--head", SHA], graphql=_GitHub()) == 0
    assert "armed: three-cubes/agent-platform#182 at 01234567" in capsys.readouterr().out
    assert "ghs_test" not in out.out + out.err


def test_main_turns_a_refusal_into_an_actionable_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _mint(monkeypatch)
    assert qp.main(["182", "--head", SHA], graphql=_GitHub(head=OTHER)) == 1
    err = capsys.readouterr().err
    assert "FAIL queue-pr" in err and "fix:" in err and "next:" in err
    assert "ghs_test" not in err


def test_the_token_is_only_ever_sent_over_https_to_the_api_host(monkeypatch: pytest.MonkeyPatch) -> None:
    _mint(monkeypatch)
    with pytest.raises(qp.QueueRefused, match="refusing to send the App token"):
        qp.queue(182, SHA, api="ftp://api.github.com")


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError("az not found in /usr/bin"),
        __import__("subprocess").CalledProcessError(1, ["az", "keyvault", "secret", "show"]),
        KeyError("token"),
        ValueError("bad json"),
        __import__("jwt").exceptions.InvalidKeyError("Could not parse the provided public key."),
    ],
)
def test_a_credential_provider_failure_is_an_actionable_envelope_with_no_value(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], failure: Exception
) -> None:
    def failing_mint(agent, repo, *, api):
        raise failure

    monkeypatch.setattr(qp, "mint_token", failing_mint)
    assert qp.main(["182", "--head", SHA], graphql=_GitHub()) == 1
    err = capsys.readouterr().err
    assert "FAIL queue-pr: could not mint the App token" in err and "fix:" in err and "next:" in err
    assert "Traceback" not in err


def test_an_untrusted_installation_is_an_actionable_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse() -> None:
        raise PermissionError("/tmp/tools/bin/queue-pr is writable by the invoking user")

    monkeypatch.setattr(qp, "installation_is_trusted", refuse)
    assert qp.main(["182", "--head", SHA], graphql=_GitHub()) == 1
    err = capsys.readouterr().err
    assert "FAIL queue-pr: untrusted installation" in err and "next:" in err


def test_verify_installation_asks_only_whether_the_installation_is_trusted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(qp, "installation_is_trusted", lambda: calls.append("checked"))
    github = _GitHub()
    assert qp.main(["--verify-installation"], graphql=github) == 0
    assert capsys.readouterr().out.strip() == "PASS queue-pr: trusted installation"
    assert calls == ["checked"] and github.calls == []  # nothing minted, nothing queued


def test_verify_installation_reports_an_untrusted_installation_in_the_envelope(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse() -> None:
        raise PermissionError("/opt/x/bin/queue-pr is writable by the invoking user")

    monkeypatch.setattr(qp, "installation_is_trusted", refuse)
    assert qp.main(["--verify-installation"], graphql=_GitHub()) == 1
    err = capsys.readouterr().err
    assert err.startswith("FAIL queue-pr: untrusted installation:") and "next:" in err


def test_a_queue_operation_still_requires_the_number_and_the_head() -> None:
    with pytest.raises(SystemExit) as exc:
        qp.parse_args(["--repo", "three-cubes/kairix"])
    assert exc.value.code == 2


def test_the_credential_failure_remedy_names_the_sibling_agent_token_by_absolute_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # The bootstrap-host layout, built under tmp_path so the result does not
    # depend on whether this host has /opt/tc-agent-tools installed (PLA-549):
    # bin/queue-pr is a symlink into the install, whose bin holds agent-token.
    install_bin = tmp_path / "tc-agent-tools" / "bin"
    install_bin.mkdir(parents=True)
    (install_bin / "queue-pr").write_text("", encoding="utf-8")
    link_bin = tmp_path / "bin"
    link_bin.mkdir()
    (link_bin / "queue-pr").symlink_to(install_bin / "queue-pr")
    monkeypatch.setattr(qp.sys, "argv", [str(link_bin / "queue-pr")])

    def missing(*_a: object, **_k: object) -> str:
        raise FileNotFoundError("az")

    monkeypatch.setattr(qp, "mint_token", missing)
    assert qp.main(["182", "--head", SHA], graphql=_GitHub()) == 1
    expected = install_bin.resolve() / "agent-token"
    assert f"next: {expected} --repo three-cubes/agent-platform" in capsys.readouterr().err


@pytest.mark.parametrize(
    "failure",
    [
        urllib.error.URLError("connection refused"),
        urllib.error.HTTPError("https://api.example.test/graphql", 401, "Unauthorized", {}, None),  # type: ignore[arg-type]
        TimeoutError("timed out"),
    ],
)
def test_a_network_failure_after_the_mint_never_prints_the_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], failure: Exception
) -> None:
    # PLA-570: the token is held in process while the API is called; no failure path of that call echoes it.
    _mint(monkeypatch)

    def failing(query: str, variables: dict[str, Any], token: str, api: str) -> dict[str, Any]:
        raise failure

    assert qp.main(["182", "--head", SHA], graphql=failing) == 1
    out = capsys.readouterr()
    assert "FAIL queue-pr" in out.err
    assert "ghs_test" not in out.out + out.err
