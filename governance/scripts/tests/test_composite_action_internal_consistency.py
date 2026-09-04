"""A composite action's `runs:` body must honour the contract its own header declares.

Nothing reads an `action.yml` past its YAML syntax: actionlint parses only
`.github/workflows/**`, and yamllint judges style. So every way a composite
action can contradict itself ships green here and surfaces inside a consumer's
run instead — in tc-agent-zone, kairix and kata, against a tag already cut.

A `run:` step missing `shell:` is a hard error the moment any consumer calls the
action. A declared input the body never reads turns a caller's `with:` into a
no-op: the step runs, behaves as though the value were never passed, and reports
success — the same silent shape as a gate lane dropping a consumer's
`pre-steps`. An `inputs.<name>` the header does not declare resolves to the
empty string with no warning at all. A declared output naming a step id that
does not exist, or a step whose body never writes the key, hands the caller an
empty string that a downstream `if:` then reads as false.

The `required: true` declarations on `python-gate-body` are load-bearing beyond
documentation. `test_internal_call_contracts.py` computes each caller's
obligation as `spec.get("required") and "default" not in spec`, so adding a
`default:` to one of them drops it from that set and every gate lane silently
stops being required to forward it — with no failing test anywhere. Eleven of
the twenty are held by that computation alone; they are not in that test's
CONSUMER_FORWARDED list.

Only `using: composite` actions are in scope. A node or docker action receives
its inputs as `INPUT_*` environment variables read by the program it runs, so
its header cannot be reconciled against its body from the YAML alone.

"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTION_ROOTS = (REPO_ROOT / "actions", REPO_ROOT / ".github" / "actions")
GATE_BODY = "actions/python-gate-body"

# An output whose key reaches $GITHUB_OUTPUT from somewhere other than a literal
# write in the step body — a helper script the step invokes, for instance. The
# step id is still resolved; only the key-write check is waived. Keyed
# "<action>:<output>", with the reason.
OUTPUT_WRITE_OK: dict[str, str] = {}

# python-gate-body inputs that carry no caller obligation. Each is optional with
# an empty default whose meaning its description spells out: an unset
# secret-scan detector, an unsharded run, the full (untiered) gate.
DELIBERATELY_OPTIONAL = {
    "private-infra-patterns": (
        "Consumer-specific secret forwarded as PRIVATE_INFRA_PATTERNS; empty "
        "leaves the detector unset, which is the correct default for a repo "
        "that has no private-infra patterns."
    ),
    "shard-index": (
        "Empty runs the gate unsharded — byte-identical to the unsharded body, "
        "so a caller that never shards must not be forced to state it."
    ),
    "shard-total": "Paired with shard-index; empty means the same unsharded run.",
    "tier": (
        "Empty runs the full gate; a value needs three-cubes-fitness >= v0.10.0, "
        "so requiring it would break consumers on an older engine pin."
    ),
}

# `inputs.<name>` in an action's own context. `github.event.inputs.<name>` is
# the workflow_dispatch event context and names a caller's input, not this
# action's, so it is removed before matching.
DISPATCH_INPUT = re.compile(r"github\.event\.inputs\.[A-Za-z0-9_-]+")
OWN_INPUT = re.compile(r"(?<!\.)\binputs\.([A-Za-z0-9_-]+)")
STEP_OUTPUT = re.compile(
    r"^\$\{\{\s*steps\.([A-Za-z0-9_-]+)\.outputs\.([A-Za-z0-9_-]+)\s*\}\}$"
)
# `$GITHUB_OUTPUT` and `${GITHUB_OUTPUT}` are the same file handle.
OUTPUT_HANDLE = re.compile(r"\$\{?GITHUB_OUTPUT\}?")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _action_paths() -> list[Path]:
    return sorted(
        (path for root in ACTION_ROOTS for path in root.glob("*/action.yml")),
        key=lambda path: path.as_posix(),
    )


def _action_id(path: Path) -> str:
    return path.parent.relative_to(REPO_ROOT).as_posix()


def _is_composite(document: dict) -> bool:
    return str((document.get("runs") or {}).get("using", "")).strip() == "composite"


def _runs_text(path: Path) -> str:
    """The raw `runs:` block, bounded by the next top-level key.

    Inputs are referenced from bare `if:` conditions carrying no `${{ }}`
    wrapper, so a structured walk of expression values misses them. Everything
    outside the block is excluded because a usage example in a `description:` is
    documentation, and the block is bounded rather than run to end-of-file so
    that a header written after `runs:` cannot feed its prose into the scan.
    """
    body: list[str] = []
    inside = False
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        if not inside:
            inside = line.startswith("runs:")
            continue
        # A top-level key ends the block; blank lines and column-0 comments
        # do not.
        if line[:1] not in ("", " ", "\t", "\n", "#"):
            break
        body.append(line)
    return "".join(body)


def _referenced_inputs(runs_text: str) -> set[str]:
    return set(OWN_INPUT.findall(DISPATCH_INPUT.sub("", runs_text)))


def _steps(document: dict) -> list[dict]:
    steps = (document.get("runs") or {}).get("steps") or []
    return [step for step in steps if isinstance(step, dict)]


def _resolved_outputs(document: dict) -> list[tuple[str, str, str]]:
    """(output name, step id, key) for each output whose `value:` names a step."""
    resolved = []
    for name, spec in (document.get("outputs") or {}).items():
        match = STEP_OUTPUT.match(str((spec or {}).get("value", "")).strip())
        if match:
            resolved.append((name, *match.groups()))
    return resolved


ACTIONS = [(_action_id(path), path) for path in _action_paths()]
ACTION_IDS = [action_id for action_id, _ in ACTIONS]
COMPOSITE = [
    (action_id, path) for action_id, path in ACTIONS if _is_composite(_load(path))
]
COMPOSITE_IDS = [action_id for action_id, _ in COMPOSITE]
INPUT_CASES = [
    (action_id, name)
    for action_id, path in COMPOSITE
    for name in (_load(path).get("inputs") or {})
]
GATE_BODY_INPUTS = sorted(
    _load(REPO_ROOT / GATE_BODY / "action.yml").get("inputs") or {}
)


def test_the_scan_found_actions_to_check() -> None:
    """A scan that silently matches nothing would pass every assertion below."""
    roots = {action_id.split("/")[0] for action_id in ACTION_IDS}
    resolved = 0
    body_checked = 0
    for _, path in COMPOSITE:
        document = _load(path)
        steps = {step["id"]: step for step in _steps(document) if step.get("id")}
        for _, step_id, _ in _resolved_outputs(document):
            resolved += 1
            step = steps.get(step_id)
            if step is not None and step.get("run"):
                body_checked += 1

    assert len(ACTIONS) >= 10, (
        f"only {len(ACTIONS)} actions discovered — the glob has probably "
        f"drifted, so these contracts are no longer being checked. "
        f"fix: reconcile ACTION_ROOTS against the action directories on disk."
    )
    assert len(COMPOSITE) >= 8, (
        f"only {len(COMPOSITE)} of {len(ACTIONS)} actions parse as "
        f"`using: composite` — either the actions were converted away from "
        f"composite, or `_is_composite` no longer recognises them and every "
        f"body assertion below covers nothing. "
        f"fix: confirm each `runs.using` value, then reset this floor."
    )
    assert len(INPUT_CASES) >= 55, (
        f"only {len(INPUT_CASES)} declared inputs discovered across "
        f"{len(COMPOSITE)} composite actions — the input parse has drifted."
    )
    assert resolved >= 5, (
        f"only {resolved} declared outputs resolve through STEP_OUTPUT to a "
        f"step id — the `value:` parse has drifted, so the step-resolution "
        f"assertion covers nothing."
    )
    assert body_checked >= 3, (
        f"only {body_checked} resolved outputs land on a step with a `run:` "
        f"body, so the key-write half of the output assertion covers almost "
        f"nothing. fix: confirm the outputs still resolve to their own steps "
        f"rather than to nested `uses:` steps."
    )
    assert roots == {"actions", ".github"}, (
        f"actions were found under {sorted(roots)} only. Both roots hold "
        f"composite actions, and the ones under .github/actions/ mint App "
        f"tokens and run `az vm run-command`. "
        f"fix: restore the glob over both roots in ACTION_ROOTS."
    )


@pytest.mark.parametrize(
    ("action_id", "name"),
    INPUT_CASES,
    ids=[f"{action_id}:{name}" for action_id, name in INPUT_CASES],
)
def test_every_declared_input_is_referenced_by_the_body(
    action_id: str, name: str
) -> None:
    referenced = _referenced_inputs(_runs_text(REPO_ROOT / action_id / "action.yml"))

    assert name in referenced, (
        f"{action_id}: input `{name}` is declared but never read by `runs:`. A "
        f"caller passing it gets no effect — the step runs with the old "
        f"behaviour and reports success. "
        f"fix: reference `inputs.{name}` in the body or drop the declaration."
    )


@pytest.mark.parametrize("action_id", COMPOSITE_IDS)
def test_every_referenced_input_is_declared(action_id: str) -> None:
    path = REPO_ROOT / action_id / "action.yml"
    declared = set(_load(path).get("inputs") or {})
    undeclared = sorted(_referenced_inputs(_runs_text(path)) - declared)
    assert not undeclared, (
        f"{action_id}: `runs:` reads input(s) {undeclared} the header does not "
        f"declare. Actions resolves an undeclared input to the empty string "
        f"with no warning, so the step runs on empty values and reports "
        f"success. "
        f"fix: declare them under `inputs:`, or correct the reference."
    )


@pytest.mark.parametrize("action_id", COMPOSITE_IDS)
def test_every_run_step_declares_a_shell(action_id: str) -> None:
    path = REPO_ROOT / action_id / "action.yml"
    missing = [
        step.get("name") or step.get("id") or f"step[{index}]"
        for index, step in enumerate(_steps(_load(path)))
        if "run" in step and not str(step.get("shell") or "").strip()
    ]
    assert not missing, (
        f"{action_id}: `run:` step(s) {missing} declare no `shell:`. That is a "
        f"hard error the moment any consumer calls the action, and nothing "
        f"here lints action.yml, so the tag ships green and breaks every "
        f"consumer at once. "
        f"fix: add `shell: bash` to each step listed."
    )


@pytest.mark.parametrize("action_id", COMPOSITE_IDS)
def test_every_declared_output_resolves_to_a_step_that_sets_it(action_id: str) -> None:
    path = REPO_ROOT / action_id / "action.yml"
    document = _load(path)
    steps = {step["id"]: step for step in _steps(document) if step.get("id")}

    broken, exempt_but_written = [], []
    for name, step_id, key in _resolved_outputs(document):
        step = steps.get(step_id)
        if step is None:
            broken.append(f"{name} -> steps.{step_id} (no step carries that id)")
            continue
        if step.get("uses"):
            # A nested action's outputs come from the action itself; resolving
            # them would need the network, so the step id is all that can be
            # verified.
            continue
        body = str(step.get("run") or "")
        # Both write forms count: `key=value` and the `key<<EOF` heredoc.
        written = bool(
            re.search(rf"(?<![A-Za-z0-9_-]){re.escape(key)}(=|<<)", body)
            and OUTPUT_HANDLE.search(body)
        )
        if f"{action_id}:{name}" in OUTPUT_WRITE_OK:
            if written:
                exempt_but_written.append(name)
        elif not written:
            broken.append(
                f"{name} -> steps.{step_id} never writes `{key}` to $GITHUB_OUTPUT"
            )

    assert not broken, (
        f"{action_id}: declared output(s) {broken}. Actions hands the caller an "
        f"empty string, which a downstream `if:` reads as false — the dependent "
        f"job is skipped and the run still reports success. "
        f"fix: write the key to $GITHUB_OUTPUT in that step, point `value:` at "
        f"the step that does, or add '{action_id}:<output>' to OUTPUT_WRITE_OK "
        f"with the reason the key is published indirectly."
    )
    assert not exempt_but_written, (
        f"{action_id}: output(s) {exempt_but_written} are listed in "
        f"OUTPUT_WRITE_OK but the step now writes the key literally. "
        f"fix: drop them from OUTPUT_WRITE_OK so the write assertion covers them."
    )


@pytest.mark.parametrize("name", GATE_BODY_INPUTS)
def test_gate_body_input_stays_required_unless_deliberately_optional(name: str) -> None:
    spec = _load(REPO_ROOT / GATE_BODY / "action.yml")["inputs"][name] or {}
    # The same derivation test_internal_call_contracts.py applies to decide
    # whether a caller is obliged to pass this input.
    obliges_the_caller = bool(spec.get("required")) and "default" not in spec

    if name in DELIBERATELY_OPTIONAL:
        assert not obliges_the_caller, (
            f"{GATE_BODY}: `{name}` is listed in DELIBERATELY_OPTIONAL but now "
            f"obliges every caller to pass it. "
            f"fix: drop it from DELIBERATELY_OPTIONAL so the requiredness "
            f"assertion covers it."
        )
        return

    assert obliges_the_caller, (
        f"{GATE_BODY}: `{name}` must stay `required: true` with no `default:`. "
        f"test_internal_call_contracts.py derives each caller's obligation as "
        f"`spec.get('required') and 'default' not in spec`, so a default here "
        f"drops `{name}` from that set and every gate lane silently stops being "
        f"required to forward it — lanes then run differently configured gates "
        f"behind one required status context. "
        f"fix: keep it required and defaultless, or add `{name}` to "
        f"DELIBERATELY_OPTIONAL with the reason a caller may omit it."
    )


def test_every_declared_exception_names_a_real_target() -> None:
    """A stale exemption would silently exempt a target it no longer explains."""
    outputs = {
        f"{action_id}:{name}"
        for action_id, path in COMPOSITE
        for name in (_load(path).get("outputs") or {})
    }
    stale = sorted(set(OUTPUT_WRITE_OK) - outputs)
    stale += sorted(
        f"{GATE_BODY}:{name}"
        for name in set(DELIBERATELY_OPTIONAL) - set(GATE_BODY_INPUTS)
    )
    assert not stale, (
        f"exception(s) {stale} name inputs or outputs that no longer exist. "
        f"fix: remove them, or the exemption outlives the target it explains."
    )
