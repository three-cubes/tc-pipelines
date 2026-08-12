"""The secrets contract must hold end to end: declared, referenced, forwarded alike.

A secret is the one input Actions declines to fail loudly over. A composite
action input declared `required: false` with `default: ""` accepts a caller that
never passes it, so the receiving step gets an empty string, runs, and reports
success. `python-gate-body` forwards `private-infra-patterns` into the fitness
gate step's env as `PRIVATE_INFRA_PATTERNS`; a lane that drops it runs a
consumer's private-infra secret-scan detector with an empty pattern set. The
detector matches nothing, soft-passes, and `Python quality gate result` — the
one status context consumers branch-protect — reports green over the leak that
detector exists to catch.

The neighbouring shapes fail just as quietly. A secret referenced but never
declared cannot be named by a caller that maps secrets explicitly, so the
expression resolves to the empty string and the step runs unauthenticated. A
secret declared but never referenced is a contract promising an effect the
implementation no longer has, so consumers keep minting and wiring a credential
that reaches nothing. A secret read from an `if:` does not resolve there at all:
the condition collapses to false, the step skips, and the job reports success.

None of this is reachable by actionlint or yamllint, which judge each file
alone, nor by the script-level tests, which execute shell lifted out of the
workflows rather than the workflows themselves. This pins the relationship
across them.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
ACTION_DIR = REPO_ROOT / "actions"

EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
# A context reference is never preceded by a word character, a dot or a quote.
# The lookbehind is what separates `secrets.gh-token` from the `.secrets.baseline`
# and `'secrets.json'` path literals that appear inside expressions.
CONTEXT_TOKEN = r"(?<![\w.'\"])secrets"
SECRET_REF = re.compile(
    CONTEXT_TOKEN + r"\s*(?:"
    r"\.\s*([A-Za-z_][A-Za-z0-9_-]*)"
    r"|\[\s*'([^']+)'\s*\]"
    r"|\[\s*\"([^\"]+)\"\s*\]"
    r")"
)
# `if:` takes a bare expression as readily as a wrapped one, so the condition
# scan cannot require the `${{ }}` delimiters the reference scan relies on.
SECRETS_CONTEXT = re.compile(CONTEXT_TOKEN + r"\s*[.\[]")

LOCAL_REUSABLE = re.compile(r"^\./\.github/workflows/(.+\.yml)$")
LOCAL_ACTION = re.compile(r"^(?:\./actions/|three-cubes/tc-pipelines/actions/)([^@/]+)")
# An action's own `inputs:`/`outputs:` prose documents the caller's expression
# rather than evaluating one, so it is read as documentation, not as a use.
DOCUMENTED = re.compile(r"^(?:inputs|outputs)\.[^.]+\.description$")

# name -> why it can never appear in an `on.workflow_call.secrets` block.
IMPLICIT_SECRETS = {
    "GITHUB_TOKEN": (
        "Injected into every run by Actions, and the secrets block rejects any "
        "name carrying the GITHUB_ prefix, so declaring it is impossible."
    ),
}

# (workflow, lane, secret) -> why that lane deliberately runs without it.
# Empty by intent: an omission has to be argued in writing here rather than
# disappearing into a `with:` block.
LANE_SECRET_EXEMPT: dict[tuple[str, str, str], str] = {}

# Every job in an `example-*` workflow is an independent illustrative call
# variant rather than one lane of a fan-out, so a secret passed by one variant
# and omitted by the next is the file's purpose, not drift.
ILLUSTRATIVE_PREFIX = "example-"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _triggers(document: dict) -> dict:
    # `on:` parses as the boolean True under YAML 1.1.
    return document.get(True) or document.get("on") or {}


def _outside_the_contract(document: dict) -> dict:
    """The document minus its `on:` block.

    The `workflow_call` block declares the contract. Scanning it would read a
    secret's own declaration as a use of that secret.
    """
    return {
        key: value
        for key, value in document.items()
        if key is not True and key != "on"
    }


def _scalars(node: object, path: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    """Every string in the tree, paired with the dotted path that reached it."""
    if isinstance(node, dict):
        items: object = node.items()
    elif isinstance(node, list):
        items = enumerate(node)
    elif isinstance(node, str):
        return [(".".join(path), node)]
    else:
        return []
    return [
        hit
        for key, value in items  # type: ignore[attr-defined]
        for hit in _scalars(value, path + (str(key),))
    ]


def _secret_names(text: str) -> set[str]:
    """Secret names read from the `secrets` context inside a `${{ }}` span.

    PyYAML drops `#` comments before this sees the document, and confining the
    match to an expression span keeps out Python's stdlib `secrets` module in a
    `run:` block. Path literals such as `.secrets.baseline` sit inside an
    expression often enough that the span alone does not separate them; the
    lookbehind in CONTEXT_TOKEN is what does.
    """
    return {
        name
        for span in EXPRESSION.findall(text)
        for match in SECRET_REF.finditer(span)
        if (name := match.group(1) or match.group(2) or match.group(3))
    }


def _reusables() -> dict[str, dict]:
    """Reusable workflow -> its declared `workflow_call` secrets."""
    contracts = {}
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        call = _triggers(_load(path)).get("workflow_call")
        if isinstance(call, dict):
            contracts[path.name] = call.get("secrets") or {}
    return contracts


def _references(path: Path) -> dict[str, list[str]]:
    """Secret name -> the paths inside the workflow that read it."""
    found: dict[str, list[str]] = {}
    for location, scalar in _scalars(_outside_the_contract(_load(path))):
        for name in _secret_names(scalar):
            found.setdefault(name, []).append(location)
    return found


def _forwarded(*blocks: object) -> set[str]:
    """Secret names appearing in what a call passes to its target."""
    return {
        name
        for block in blocks
        if isinstance(block, dict)
        for _, scalar in _scalars(block)
        for name in _secret_names(scalar)
    }


def _repeated_targets(document: dict) -> dict[str, dict[str, set[str]]]:
    """Internal target called from more than one job -> job -> secrets forwarded."""
    actions = {path.parent.name for path in ACTION_DIR.glob("*/action.yml")}
    targets: dict[str, dict[str, set[str]]] = {}

    def record(target: str, lane: str, names: set[str]) -> None:
        # A job may reach the same target from several steps; union them, so a
        # second call cannot hide what the first passed.
        targets.setdefault(target, {}).setdefault(lane, set()).update(names)

    for lane, job in (document.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        match = LOCAL_REUSABLE.match(str(job.get("uses", "")))
        if match and (WORKFLOW_DIR / match.group(1)).is_file():
            record(match.group(1), lane, _forwarded(job.get("with"), job.get("secrets")))
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            match = LOCAL_ACTION.match(str(step.get("uses", "")))
            if match and match.group(1) in actions:
                record(f"actions/{match.group(1)}", lane, _forwarded(step.get("with")))
    return {target: lanes for target, lanes in targets.items() if len(lanes) > 1}


def _lane_cases() -> list[tuple[str, str, str, str, bool]]:
    """(workflow, target, lane, shared secret, whether the lane forwards it).

    A secret two or more lanes already pass is shared configuration for that
    target, so a lane omitting it is drift. A secret only one lane passes is
    that lane's own business, and demanding the rest match it would invent a
    requirement.
    """
    cases = []
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        if path.name.startswith(ILLUSTRATIVE_PREFIX):
            continue
        for target, lanes in sorted(_repeated_targets(_load(path)).items()):
            carried = Counter(name for forwarded in lanes.values() for name in forwarded)
            for secret in sorted(name for name, seen in carried.items() if seen > 1):
                for lane in sorted(lanes):
                    cases.append(
                        (path.name, target, lane, secret, secret in lanes[lane])
                    )
    return cases


def _conditions() -> dict[str, list[tuple[str, str]]]:
    """Workflow -> every `if:` scalar in it, with the path that reached it."""
    return {
        path.name: [
            (location, scalar)
            for location, scalar in _scalars(_load(path))
            if location.rsplit(".", 1)[-1] == "if"
        ]
        for path in sorted(WORKFLOW_DIR.glob("*.yml"))
    }


REUSABLES = _reusables()
REFERENCES = {workflow: _references(WORKFLOW_DIR / workflow) for workflow in REUSABLES}
DECLARED_PAIRS = [
    (workflow, secret)
    for workflow, declared in REUSABLES.items()
    for secret in sorted(declared)
]
LANE_CASES = _lane_cases()
CONDITIONS = _conditions()
ACTIONS = sorted(path.parent.name for path in ACTION_DIR.glob("*/action.yml"))


def test_the_scan_found_a_secrets_contract_to_check() -> None:
    """A drifted expression pattern would pass every assertion below vacuously."""
    declaring = [workflow for workflow, declared in REUSABLES.items() if declared]
    sites = sum(len(paths) for refs in REFERENCES.values() for paths in refs.values())
    gate_lanes = {
        lane for _, target, lane, _, _ in LANE_CASES if "python-gate-body" in target
    }
    conditions = sum(len(found) for found in CONDITIONS.values())
    illustrative = [
        path.name
        for path in WORKFLOW_DIR.glob("*.yml")
        if path.name.startswith(ILLUSTRATIVE_PREFIX)
    ]

    assert len(REUSABLES) >= 25, (
        f"only {len(REUSABLES)} reusable workflows discovered — the "
        f"`workflow_call` lookup has drifted, so most of the repo's product is "
        f"no longer being checked."
    )
    assert len(DECLARED_PAIRS) >= 12 and len(declaring) >= 8, (
        f"only {len(DECLARED_PAIRS)} declared secrets across {len(declaring)} "
        f"reusables — the `on.workflow_call.secrets` lookup has drifted, so the "
        f"declared-vs-referenced assertions cover almost nothing."
    )
    assert sites >= 15, (
        f"only {sites} `${{{{ }}}}` secret references found — the expression "
        f"pattern has drifted, so an undeclared secret would now go unseen."
    )
    assert len(gate_lanes) >= 2, (
        f"only {len(gate_lanes)} python-gate-body lanes found — parity needs at "
        f"least two lanes to compare, so the lane scan has drifted and a lane "
        f"dropping a secret would no longer be measured against its siblings."
    )
    assert conditions >= 60, (
        f"only {conditions} `if:` conditions found — the condition walk has "
        f"drifted, so a secret read from an unresolvable context would go unseen."
    )
    assert len(ACTIONS) >= 4, (
        f"only {len(ACTIONS)} composite actions found — the "
        f"`actions/*/action.yml` glob has drifted."
    )
    assert illustrative, (
        f"no workflow starts with {ILLUSTRATIVE_PREFIX!r}, so that exemption "
        f"now excuses nothing and only obscures the lane scan's scope. "
        f"fix: drop ILLUSTRATIVE_PREFIX, or point it at the current prefix."
    )


@pytest.mark.parametrize("workflow", sorted(REUSABLES))
def test_every_referenced_secret_is_declared(workflow: str) -> None:
    undeclared = sorted(
        name
        for name in REFERENCES[workflow]
        if name not in REUSABLES[workflow] and name not in IMPLICIT_SECRETS
    )
    assert not undeclared, (
        f"{workflow} reads secret(s) {undeclared} that its `workflow_call` "
        f"contract does not declare. A caller mapping secrets by name cannot "
        f"pass what the contract does not offer, so the expression resolves to "
        f"the empty string and the step runs unauthenticated while still "
        f"reporting success — only a caller using `secrets: inherit` happens to "
        f"work. fix: declare each name under `on.workflow_call.secrets`, or "
        f"correct the reference."
    )


@pytest.mark.parametrize(
    ("workflow", "secret"),
    DECLARED_PAIRS,
    ids=[f"{workflow}:{secret}" for workflow, secret in DECLARED_PAIRS],
)
def test_every_declared_secret_is_referenced(workflow: str, secret: str) -> None:
    assert secret in REFERENCES[workflow], (
        f"{workflow} declares secret `{secret}` and never reads it. The "
        f"contract then promises an effect the implementation no longer has: "
        f"consumers keep minting the credential and wiring it into every call "
        f"for nothing, and an audit of the secret's blast radius reads a use "
        f"that is not there. fix: reference it, or drop it from "
        f"`on.workflow_call.secrets` and tell consumers to stop passing it."
    )


@pytest.mark.parametrize(
    ("workflow", "target", "lane", "secret", "forwarded"),
    LANE_CASES,
    ids=[
        f"{workflow}:{lane}->{target}:{secret}"
        for workflow, target, lane, secret, _ in LANE_CASES
    ],
)
def test_every_lane_forwards_the_same_shared_secret(
    workflow: str, target: str, lane: str, secret: str, forwarded: bool
) -> None:
    reason = LANE_SECRET_EXEMPT.get((workflow, lane, secret))
    if reason:
        assert not forwarded, (
            f"{workflow}: `{lane}` is exempt from forwarding `{secret}` to "
            f"`{target}` but now forwards it. fix: drop the LANE_SECRET_EXEMPT "
            f"entry so the parity assertion covers this lane again."
        )
        return

    assert forwarded, (
        f"{workflow}: lane `{lane}` does not forward `{secret}` to `{target}` "
        f"while its sibling lanes do. The lanes then run differently configured "
        f"gates behind one required status context: the receiving input is "
        f"optional with an empty default, so nothing errors — the step runs with "
        f"the value unset, whatever consumes it matches nothing, and the fan-in "
        f"reports green. fix: pass "
        f"`{secret}: ${{{{ secrets.{secret} }}}}` in this lane too, or add "
        f"({workflow!r}, {lane!r}, {secret!r}) to LANE_SECRET_EXEMPT with the "
        f"reason this lane must run without it."
    )


@pytest.mark.parametrize("workflow", sorted(CONDITIONS))
def test_no_condition_reads_the_secrets_context(workflow: str) -> None:
    offenders = sorted(
        location
        for location, scalar in CONDITIONS[workflow]
        if SECRETS_CONTEXT.search(scalar)
    )
    assert not offenders, (
        f"{workflow} reads the `secrets` context from an `if:` at {offenders}. "
        f"`secrets` is not available to a job- or step-level condition, so it "
        f"does not resolve, the condition collapses to false, and the step "
        f"skips while the job still reports success. fix: capture the value "
        f"into a job-level `env:` and test `env.<NAME>` in the `if:`, as "
        f"docker-build-publish.yml does with HAS_REGISTRY_PASSWORD."
    )


@pytest.mark.parametrize("action", ACTIONS)
def test_no_composite_action_reads_the_secrets_context(action: str) -> None:
    document = _load(ACTION_DIR / action / "action.yml")
    offenders = sorted(
        location
        for location, scalar in _scalars(document)
        if not DOCUMENTED.match(location) and _secret_names(scalar)
    )
    assert not offenders, (
        f"actions/{action} reads the `secrets` context at {offenders}. A "
        f"composite action has no `secrets` context in any position, so the "
        f"expression resolves to nothing and the step runs with the value "
        f"unset while reporting success. fix: declare an input and have the "
        f"calling workflow pass the secret into it."
    )


def test_every_lane_exemption_names_a_real_lane() -> None:
    """A stale exemption would silently excuse a lane that no longer exists."""
    live = {(workflow, lane, secret) for workflow, _, lane, secret, _ in LANE_CASES}
    unknown = sorted(key for key in LANE_SECRET_EXEMPT if key not in live)
    assert not unknown, (
        f"LANE_SECRET_EXEMPT names lanes that are no longer scanned: {unknown}. "
        f"fix: remove them, or the exemption outlives the lane it explains."
    )


def test_every_implicit_secret_carries_its_reason() -> None:
    """An exemption without a reason is indistinguishable from an oversight."""
    bare = sorted(
        name for name, reason in IMPLICIT_SECRETS.items() if not str(reason).strip()
    )
    assert not bare, (
        f"IMPLICIT_SECRETS entries {bare} exempt a name with no stated reason. "
        f"fix: state why the name cannot be declared, or drop the exemption."
    )


def test_the_reference_scan_separates_a_context_from_a_path_literal() -> None:
    """The lookbehind is the only thing keeping a baseline filename out."""
    assert _secret_names("${{ secrets.gh-token || github.token }}") == {"gh-token"}
    assert _secret_names("${{ secrets['GH_PAT'] }}") == {"GH_PAT"}
    assert not _secret_names("${{ contains(inputs.path, '.secrets.baseline') }}")
    assert not SECRETS_CONTEXT.search("${{ endsWith(matrix.file, 'secrets.json') }}")
    assert SECRETS_CONTEXT.search("${{ secrets.gh-token != '' }}")
