"""Shared input defaults must agree across the reusables a consumer pairs.

`pytest-durations-refresh.yml` produces the `.test_durations` map that
`python-quality-gate.yml` splits on. The map is only meaningful if both ran the
same suite in the same environment, and both restate the same environment
inputs. Where an input is optional in both and their defaults differ, a consumer
that states it in neither call — the common case, since both are optional — gets
a silently different environment on each side and a map describing a run its
gate never performs.

That failure has already happened twice, on `pnpm-install-args` and
`pnpm-version`, and neither was catchable by actionlint or yamllint: both files
were individually valid. This pins the relationship between them.

A difference that is deliberate is declared in DELIBERATE with its reason, so
intent stays distinguishable from drift.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
GATE = WORKFLOWS / "python-quality-gate.yml"
REFRESH = WORKFLOWS / "pytest-durations-refresh.yml"

# input -> why the refresh deliberately differs from the gate.
DELIBERATE = {
    "fetch-depth": (
        "The refresh checks out full history: a suite whose tests read git "
        "history times them differently against a shallow clone, and the map "
        "has to describe the slow case."
    ),
    "ts-coverage-command": (
        "TS coverage adds nothing to a pytest durations map and only lengthens "
        "the run; node is still provisioned via run-node."
    ),
}


def _call_inputs(path: Path) -> dict[str, dict]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    # `on:` parses as the boolean True under YAML 1.1.
    triggers = document.get(True) or document.get("on")
    return triggers["workflow_call"]["inputs"]


def _optional_shared() -> list[str]:
    gate, refresh = _call_inputs(GATE), _call_inputs(REFRESH)
    return sorted(
        name
        for name in set(gate) & set(refresh)
        # A required input carries no default, so the caller is forced to state
        # it and cannot silently inherit a differing one.
        if not refresh[name].get("required")
    )


@pytest.mark.parametrize("name", _optional_shared())
def test_optional_shared_default_matches_the_gate(name: str) -> None:
    gate, refresh = _call_inputs(GATE), _call_inputs(REFRESH)
    gate_default = gate[name].get("default")
    refresh_default = refresh[name].get("default")

    if name in DELIBERATE:
        assert gate_default != refresh_default, (
            f"{name} is listed in DELIBERATE but now matches the gate. "
            f"fix: drop it from DELIBERATE so the parity assertion covers it."
        )
        return

    assert refresh_default == gate_default, (
        f"{name} defaults differ: python-quality-gate={gate_default!r} vs "
        f"pytest-durations-refresh={refresh_default!r}. A consumer stating it "
        f"in neither call gets a different environment on each side, so the "
        f"durations map describes a run its gate never performs. "
        f"fix: match the gate's default, or add {name} to DELIBERATE with the "
        f"reason it must differ."
    )


def test_every_deliberate_difference_names_a_real_input() -> None:
    """A stale DELIBERATE entry would silently exempt an input from parity."""
    shared = set(_call_inputs(GATE)) & set(_call_inputs(REFRESH))
    unknown = sorted(set(DELIBERATE) - shared)
    assert not unknown, (
        f"DELIBERATE names inputs that are no longer shared: {unknown}. "
        f"fix: remove them, or the exemption outlives the input it explains."
    )
