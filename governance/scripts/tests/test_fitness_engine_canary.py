"""Contract test for the fitness-engine-canary.sh pre-release gate (SGO-275).

The canary is the missing step between "engine PR merged" and "tag + fleet
repin": it runs a REAL consumer's fitness gate against the CANDIDATE engine (a
git ref to the fix branch/SHA, never a tag) and blocks the release if that gate
reds. The v0.13.0 empty-roots regression escaped because nothing ran a
consumer's gate against the candidate before the tag went out.

Core contract, exercised here: the canary's exit code EQUALS the consumer gate's
exit code — a red consumer gate (non-zero) → the canary exits non-zero (release
blocked); a green gate (0) → the canary exits 0 (proceed). The gate command is
injectable so this stays hermetic: no network, no real tc-fitness, no live
engine — a stub gate stands in for `uv run tc-fitness run`, and a temp consumer
dir carries a real tc-fitness pin so the repin path is exercised.

Interface: shell-entrypoint.governance.scripts.fitness-engine-canary
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = "governance/scripts/fitness-engine-canary.sh"

# The buggy tag that shipped the regression; the consumer fixture pins it so the
# repin has something real to rewrite. The candidate is a FIX ref (branch/SHA).
BASELINE_PIN_REF = "v0.13.0"
CANDIDATE_REF = "dan/sgo-275-fix-empty-roots"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    # Literal script path (not a Path var) so an outcome-test gate can match the
    # surface name in the subprocess call; cwd resolves it.
    return subprocess.run(
        ["bash", "governance/scripts/fitness-engine-canary.sh", *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )


def _make_consumer(dir_: Path, *, pin_ref: str = BASELINE_PIN_REF) -> Path:
    """A minimal consumer checkout carrying a real three-cubes-fitness pin."""
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / "pyproject.toml").write_text(
        "[project]\n"
        'name = "sample-consumer"\n'
        'version = "0.0.0"\n'
        'requires-python = ">=3.12"\n'
        "dependencies = [\n"
        '    "three-cubes-fitness @ '
        f'git+https://github.com/three-cubes/tc-fitness.git@{pin_ref}",\n'
        "]\n",
        encoding="utf-8",
    )
    return dir_


def _stub_gate(dir_: Path, exit_code: int) -> str:
    """A stubbed gate command that records the cwd it ran in, then exits.

    Returned as a command STRING for `--gate-cmd`, so the canary runs it exactly
    where it would run `uv run tc-fitness run`.
    """
    stub = dir_ / f"stub-gate-{exit_code}.sh"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        '# Prove the gate ran in the consumer dir: drop a marker in $PWD.\n'
        'echo "$PWD" > gate-ran.marker\n'
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return f"bash {stub}"


def _pin_ref_of(consumer: Path) -> str:
    line = next(
        ln
        for ln in (consumer / "pyproject.toml").read_text(encoding="utf-8").splitlines()
        if "tc-fitness.git@" in ln
    )
    return line.split("tc-fitness.git@", 1)[1].rstrip('",').strip()


# ── the CORE contract: canary exit code == consumer gate exit code ───────────


@pytest.mark.parametrize("gate_exit", [0, 1, 2, 42])
def test_canary_exit_code_equals_consumer_gate_exit_code(tmp_path: Path, gate_exit: int) -> None:
    consumer = _make_consumer(tmp_path / "consumer")
    result = _run(
        "--consumer-dir", str(consumer),
        "--candidate-ref", CANDIDATE_REF,
        "--gate-cmd", _stub_gate(tmp_path, gate_exit),
    )
    assert result.returncode == gate_exit, (
        f"canary must exit with the gate's code ({gate_exit}), got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_red_consumer_gate_blocks_the_release(tmp_path: Path) -> None:
    # A red (non-zero) consumer gate → the release is BLOCKED (canary non-zero).
    consumer = _make_consumer(tmp_path / "consumer")
    result = _run(
        "--consumer-dir", str(consumer),
        "--candidate-ref", CANDIDATE_REF,
        "--gate-cmd", _stub_gate(tmp_path, 1),
    )
    assert result.returncode != 0, "a red consumer gate must block the release"


def test_green_consumer_gate_lets_the_release_proceed(tmp_path: Path) -> None:
    consumer = _make_consumer(tmp_path / "consumer")
    result = _run(
        "--consumer-dir", str(consumer),
        "--candidate-ref", CANDIDATE_REF,
        "--gate-cmd", _stub_gate(tmp_path, 0),
    )
    assert result.returncode == 0, result.stderr


# ── the repin path is really exercised ───────────────────────────────────────


def test_repin_rewrites_the_consumer_pin_to_the_candidate_ref(tmp_path: Path) -> None:
    consumer = _make_consumer(tmp_path / "consumer")
    assert _pin_ref_of(consumer) == BASELINE_PIN_REF  # precondition
    result = _run(
        "--consumer-dir", str(consumer),
        "--candidate-ref", CANDIDATE_REF,
        "--gate-cmd", _stub_gate(tmp_path, 0),
    )
    assert result.returncode == 0, result.stderr
    assert _pin_ref_of(consumer) == CANDIDATE_REF, (
        "the canary must repin the consumer to the CANDIDATE engine ref before "
        f"running the gate (still {_pin_ref_of(consumer)})"
    )


def test_gate_runs_inside_the_consumer_dir(tmp_path: Path) -> None:
    consumer = _make_consumer(tmp_path / "consumer")
    result = _run(
        "--consumer-dir", str(consumer),
        "--candidate-ref", CANDIDATE_REF,
        "--gate-cmd", _stub_gate(tmp_path, 0),
    )
    assert result.returncode == 0, result.stderr
    marker = consumer / "gate-ran.marker"
    assert marker.exists(), "the gate must run with the consumer dir as cwd"
    assert marker.read_text(encoding="utf-8").strip() == str(consumer.resolve())


# ── actionable errors (the org fix:/next: idiom) ─────────────────────────────


def test_help_exits_zero_and_documents_the_flags() -> None:
    result = _run("--help")
    assert result.returncode == 0
    out = result.stdout
    assert "fitness-engine-canary" in out
    for flag in ("--consumer-dir", "--candidate-ref", "--gate-cmd"):
        assert flag in out, f"help text omits {flag}"


def test_missing_candidate_ref_is_an_actionable_error(tmp_path: Path) -> None:
    consumer = _make_consumer(tmp_path / "consumer")
    result = _run("--consumer-dir", str(consumer))  # no --candidate-ref
    assert result.returncode == 2
    assert "--candidate-ref" in result.stderr
    assert "fix:" in result.stderr


def test_missing_consumer_is_an_actionable_error() -> None:
    result = _run("--candidate-ref", CANDIDATE_REF)  # no --consumer-dir / --repo
    assert result.returncode == 2
    assert "fix:" in result.stderr


def test_consumer_without_a_fitness_pin_is_an_actionable_error(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "pyproject.toml").write_text(
        '[project]\nname = "no-pin"\nversion = "0.0.0"\ndependencies = []\n',
        encoding="utf-8",
    )
    result = _run(
        "--consumer-dir", str(consumer),
        "--candidate-ref", CANDIDATE_REF,
        "--gate-cmd", _stub_gate(tmp_path, 0),
    )
    assert result.returncode == 2
    assert "three-cubes-fitness" in result.stderr
    assert "fix:" in result.stderr
