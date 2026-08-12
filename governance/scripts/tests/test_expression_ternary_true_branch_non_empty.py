"""A `COND && VALUE || FALLBACK` expression must not select an always-empty VALUE.

GitHub expressions have no ternary operator. The idiom is a `&&`/`||` chain that
resolves by truthiness: a `&&` chain yields its LAST operand when every operand
is truthy, and `||` yields its first truthy alternative. An empty string, `0` and
`false` are all falsy. So when the selected VALUE is empty the chain yields an
empty string, `||` reads that as failure, and the expression returns FALLBACK —
the branch it was written to avoid — while the condition held the whole time. The
expression looks correct, the run reports no error, and the wrong value reaches
the step.

Only this file's own declarations can prove that statically, and there are exactly
two such proofs. A literal empty true-branch is dead on every run. An
`inputs.<name>` true-branch whose own `workflow_call` / `workflow_dispatch` /
action declaration supplies a falsy default is dead for every caller that relies
on that default — which is what a reusable exists for. The `<name> != ''`
self-guard is what makes that second shape correct: it states that FALLBACK IS
the intended empty-case route, so the chain is not routing on the condition
alone. A guard naming a DIFFERENT operand than the one selected restores the trap
while looking guarded, and that drift is what this pins.

`python-quality-gate.yml` is the reachable instance: `shard-tier` and `tier` both
default to empty and the shard lane picks between them in one chain. Move the
`!= ''` onto the other name and a caller setting `shard-tier` but not `tier`
hands the shard step an empty tier, so every shard runs the whole catalogue
instead of the sharded steps. Both files stay individually valid, so neither
actionlint nor yamllint can see it.

The scan asserts nothing about a `steps.` / `env.` / `needs.` / `github.` /
`secrets.` / `matrix.` read or a function call in the true-branch: no declaration
here fixes those values, so emptiness is not knowable and a verdict either way
would be a guess.

An expression whose always-empty selection is intentional is declared in
DELIBERATE with its reason, so intent stays distinguishable from drift.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
ACTION_DIRS = (REPO_ROOT / "actions", REPO_ROOT / ".github" / "actions")

EXPRESSION = re.compile(r"\$\{\{(.+?)\}\}", re.DOTALL)
INPUT_REFERENCE = re.compile(r"^inputs\.([A-Za-z_][A-Za-z0-9_\-]*)$")
QUOTED = re.compile(r"^'([^']*(?:''[^']*)*)'$")
NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")

# "<path>:<key path>" -> why an always-empty selection is intentional there.
DELIBERATE: dict[str, str] = {}


def _split_top_level(expression: str, operator: str) -> list[str]:
    """Split on `operator` outside parentheses and outside string literals.

    `always() && (failure() || cancelled())` is ONE alternative, not two, and a
    `||` inside `contains(x, 'a || b')` is text. A regex cannot see either.
    """
    parts: list[str] = []
    buffer: list[str] = []
    depth = 0
    quoted = False
    index = 0
    while index < len(expression):
        char = expression[index]
        if quoted:
            buffer.append(char)
            if char == "'":
                # `''` inside a literal is an escaped quote, not the end of it.
                quoted = expression[index + 1 : index + 2] == "'"
                if quoted:
                    buffer.append("'")
                    index += 1
            index += 1
            continue
        if char == "'":
            quoted = True
            buffer.append(char)
            index += 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if depth == 0 and expression[index : index + len(operator)] == operator:
            parts.append("".join(buffer))
            buffer = []
            index += len(operator)
            continue
        buffer.append(char)
        index += 1
    parts.append("".join(buffer))
    return [part.strip() for part in parts]


def _as_ternary(body: str) -> tuple[str, list[str], str] | None:
    """(selected value, guards preceding it, fallback), or None if not a ternary.

    A ternary is a top-level `||` whose FIRST alternative is a top-level `&&`
    chain. The value that alternative yields when it holds is its last operand.
    """
    alternatives = _split_top_level(body.strip(), "||")
    if len(alternatives) < 2:
        return None
    conjuncts = _split_top_level(alternatives[0], "&&")
    if len(conjuncts) < 2:
        return None
    return conjuncts[-1], conjuncts[:-1], " || ".join(alternatives[1:])


def _declared_inputs(document: dict) -> dict[str, dict]:
    """Every input the `inputs.` context resolves to inside this document."""
    declared: dict = {}
    if isinstance(document.get("inputs"), dict):  # composite action
        declared.update(document["inputs"])
    # `on:` parses as the boolean True under YAML 1.1.
    triggers = document.get(True) or document.get("on")
    if isinstance(triggers, dict):
        for trigger in ("workflow_dispatch", "workflow_call"):
            section = triggers.get(trigger)
            if isinstance(section, dict) and isinstance(section.get("inputs"), dict):
                declared.update(section["inputs"])
    return {name: spec for name, spec in declared.items() if isinstance(spec, dict)}


def _is_self_guarded(operand: str, guards: list[str]) -> bool:
    wanted = re.sub(r"\s+", "", f"{operand}!=''")
    return any(re.sub(r"\s+", "", guard) == wanted for guard in guards)


def _always_empty_reason(
    operand: str, guards: list[str], declared: dict[str, dict]
) -> str | None:
    """Why the selected value is always falsy, or None when it is not provably so."""
    quoted = QUOTED.match(operand)
    if quoted:
        return "it is an empty string literal" if quoted.group(1) == "" else None
    if NUMBER.match(operand):
        return "the literal 0 is falsy" if float(operand) == 0 else None
    if operand == "false":
        return "the literal false is falsy"
    reference = INPUT_REFERENCE.match(operand)
    if reference is None:
        return None
    if _is_self_guarded(operand, guards):
        return None
    spec = declared.get(reference.group(1))
    if spec is None or spec.get("required"):
        return None
    default = spec.get("default")
    if default is None:
        return (
            "its declaration carries no default, so an unset caller sends an "
            "empty string"
        )
    if default in ("", False, 0):
        return f"its declaration defaults to {default!r}, which is falsy"
    return None


def _strings(node: object, path: tuple[str, ...]) -> list[tuple[tuple[str, ...], str]]:
    if isinstance(node, dict):
        found: list = []
        for key, value in node.items():
            found += _strings(value, (*path, str(key)))
        return found
    if isinstance(node, list):
        found = []
        for index, value in enumerate(node):
            found += _strings(value, (*path, str(index)))
        return found
    if isinstance(node, str):
        return [(path, node)]
    return []


def _yaml_files() -> list[Path]:
    files = list(WORKFLOW_DIR.glob("*.yml")) + list(WORKFLOW_DIR.glob("*.yaml"))
    for directory in ACTION_DIRS:
        files += list(directory.glob("*/action.yml"))
        files += list(directory.glob("*/action.yaml"))
    return sorted(files)


def _ternaries() -> list[tuple[str, str, str, list[str], str, dict]]:
    found = []
    for path in _yaml_files():
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        declared = _declared_inputs(document)
        for keypath, text in _strings(document, ()):
            # An `if:` is a boolean context, where yielding the falsy last
            # operand IS the correct answer. Only value positions are ternaries.
            if keypath and keypath[-1] == "if":
                continue
            # Reading only inside the `${{ }}` delimiters keeps shell `&&`/`||`
            # in `run:` bodies out of the scan.
            for body in EXPRESSION.findall(text):
                ternary = _as_ternary(body)
                if ternary is None:
                    continue
                selected, guards, fallback = ternary
                found.append(
                    (
                        str(path.relative_to(REPO_ROOT)),
                        "/".join(keypath),
                        selected,
                        guards,
                        fallback,
                        declared,
                    )
                )
    return found


TERNARIES = _ternaries()


def _resolved() -> list[tuple]:
    resolved = []
    for entry in TERNARIES:
        reference = INPUT_REFERENCE.match(entry[2])
        if reference and reference.group(1) in entry[5]:
            resolved.append(entry)
    return resolved


def test_the_scan_resolves_selected_values_against_declarations() -> None:
    """A scan matching nothing, or resolving nothing, passes every assertion below."""
    resolved = _resolved()
    assert len(TERNARIES) >= 4 and len(resolved) >= 3, (
        f"{len(TERNARIES)} `COND && VALUE || FALLBACK` expressions found across "
        f"{len(_yaml_files())} workflow and action files, {len(resolved)} of them "
        f"selecting an input that resolved to a declaration — too few for the "
        f"assertion below to be checking anything, so a real dead branch would "
        f"merge unseen. Either the `${{{{ }}}}` extraction, the top-level split, "
        f"or the input lookup has drifted. "
        f"fix: confirm the scan still sees the chains in publish-pypi.yml, "
        f"docker-build-publish.yml and python-quality-gate.yml, and that "
        f"_declared_inputs still reads `on.workflow_call.inputs`."
    )


@pytest.mark.parametrize(
    ("source", "keypath", "selected", "guards", "fallback", "declared"),
    TERNARIES,
    ids=[f"{source}:{keypath}" for source, keypath, _, _, _, _ in TERNARIES],
)
def test_ternary_does_not_select_an_always_empty_value(
    source: str,
    keypath: str,
    selected: str,
    guards: list[str],
    fallback: str,
    declared: dict,
) -> None:
    key = f"{source}:{keypath}"
    reason = _always_empty_reason(selected, guards, declared)

    if key in DELIBERATE:
        assert reason is not None, (
            f"{key} is listed in DELIBERATE but its selected value is no longer "
            f"provably empty. fix: drop it from DELIBERATE so the assertion "
            f"covers it."
        )
        return

    assert reason is None, (
        f"{source}: the expression at `{keypath}` selects `{selected}` when its "
        f"condition holds, but {reason}. GitHub casts a falsy value to false and "
        f"a `&&` chain yields its last operand, so the chain falls through to "
        f"`{fallback}` even when the condition held — the expression silently "
        f"returns the branch it exists to avoid, and the run reports no error. A "
        f"`!= ''` guard on a DIFFERENT operand than the one selected does not "
        f"prevent this. "
        f"fix: give `{selected}` a non-empty default, or mark it required, so the "
        f"selected branch can win; or self-guard it as `{selected} != '' && "
        f"<condition> && {selected} || {fallback}` when `{fallback}` IS the "
        f"intended empty-case route; or add '{key}' to DELIBERATE with the reason "
        f"an always-empty selection is correct there."
    )


def test_every_deliberate_exemption_names_a_real_ternary() -> None:
    """A stale DELIBERATE entry would outlive the expression it explains."""
    known = {f"{source}:{keypath}" for source, keypath, _, _, _, _ in TERNARIES}
    unknown = sorted(set(DELIBERATE) - known)
    assert not unknown, (
        f"DELIBERATE names expressions the scan no longer finds: {unknown}. "
        f"fix: remove them, or correct the key path — an exemption that matches "
        f"nothing hides the next expression that moves under that key."
    )


EMPTY = {"default": ""}
SET = {"default": "release-alpha"}
REQUIRED = {"required": True}
NO_DEFAULT = {"description": "optional, no default"}

# (expression, declared inputs, verdict) — the classifier is the load-bearing
# logic, so its ability to separate these shapes is asserted directly.
CLASSIFIER_CASES = [
    ("inputs.ref != '' && inputs.ref || github.ref", {"ref": EMPTY}, "ok"),
    ("inputs.t != ''&&inputs.t||inputs.u", {"t": EMPTY}, "ok"),
    ("contains(a, 'x || y') && 'literal' || b", {}, "ok"),
    ("(x || inputs.is-alpha) && inputs.env || inputs.other", {"env": SET}, "ok"),
    ("cond && inputs.env || inputs.other", {"env": REQUIRED}, "ok"),
    # Unresolvable contexts are outside the claim: no declaration fixes them.
    ("cond && steps.build.outputs.sha || ''", {}, "ok"),
    ("cond && format('{0}', x) || 'y'", {}, "ok"),
    ("cond && env.PROD_URL || env.DEV_URL", {}, "ok"),
    # Dead true-branches.
    ("cond && '' || 'fallback'", {}, "always-empty"),
    ("cond && inputs.env || inputs.other", {"env": EMPTY}, "always-empty"),
    ("cond && inputs.env || inputs.other", {"env": NO_DEFAULT}, "always-empty"),
    ("inputs.u != '' && inputs.t || inputs.u", {"t": EMPTY, "u": EMPTY}, "always-empty"),
    # Not ternaries at all.
    ("secrets.gh-token || github.token", {}, "not-a-ternary"),
    ("inputs.sign && inputs.push", {}, "not-a-ternary"),
    ("always() && (failure() || cancelled()) && inputs.s != ''", {}, "not-a-ternary"),
]


@pytest.mark.parametrize(("expression", "declared", "expected"), CLASSIFIER_CASES)
def test_the_classifier_separates_the_shapes_it_must_not_confuse(
    expression: str, declared: dict, expected: str
) -> None:
    ternary = _as_ternary(expression)
    if expected == "not-a-ternary":
        assert ternary is None, (
            f"{expression!r} was classified as a ternary. A plain `||` fallback, "
            f"value-position boolean composition, and a parenthesised `||` inside "
            f"a condition are all correct as written; treating them as ternaries "
            f"makes this guard fire on sound expressions, and it gets muted. "
            f"fix: restore the top-level `&&` + top-level `||` requirement and "
            f"the paren/quote awareness in _split_top_level."
        )
        return

    assert ternary is not None, (
        f"{expression!r} is a ternary but the classifier missed it, so a real "
        f"dead true-branch would go unchecked. "
        f"fix: restore the top-level `||` / `&&` detection in _as_ternary."
    )
    selected, guards, _ = ternary
    reason = _always_empty_reason(selected, guards, declared)
    actual = "always-empty" if reason else "ok"
    assert actual == expected, (
        f"{expression!r} with declarations {declared} classified {actual}, "
        f"expected {expected} (selected `{selected}`, guards {guards}). The rule "
        f"is that only a falsy literal, or an unguarded `inputs.<name>` whose own "
        f"declaration defaults to a falsy value, is provably empty — every other "
        f"context is outside the claim. "
        f"fix: restore that rule in _always_empty_reason."
    )
