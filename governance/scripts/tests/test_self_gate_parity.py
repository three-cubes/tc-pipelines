"""The tc-pipelines self-check must exercise its declared local gate.

The repository publishes the reusable workflows that make local and CI quality
checks converge for consumers.  Its own contract-test lane is the smallest
place that assertion can drift: running pytest there independently can pass
while the configured gate local contributors run is absent or broken.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

from conftest import pytest_xdist_auto_num_workers

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
PYPROJECT = REPO_ROOT / "pyproject.toml"
MAKEFILE = REPO_ROOT / "Makefile"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
FITNESS_COMMIT = "73d7ffc4b563849edcd607b377fbb3ee4ba6da32"


def _project_config() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _ci_workflow() -> dict:
    return yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8")) or {}


def _dry_run_make_check() -> list[str]:
    result = subprocess.run(
        ["make", "--no-print-directory", "--dry-run", "check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"{MAKEFILE.name}: cannot dry-run the local check target: {result.stderr.strip()}"
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def test_self_gate_declares_the_contract_test_command() -> None:
    """Changing the gate's pytest argv would otherwise leave CI on another command."""
    steps = _project_config().get("tool", {}).get("tc_fitness", {}).get("steps", [])
    contract_steps = [step for step in steps if step.get("id") == "contract-tests"]
    assert len(contract_steps) == 1, (
        f"{PYPROJECT.name}: expected exactly one `contract-tests` tc-fitness step, "
        f"found {len(contract_steps)}. fix: declare the workflow contract suite in "
        "[tool.tc_fitness]."
    )
    assert contract_steps[0].get("run") == ["pytest", "-q"], (
        f"{PYPROJECT.name}: `contract-tests` runs "
        f"{contract_steps[0].get('run')!r}, not ['pytest', '-q']. fix: make the "
        "configured self-gate run the repository's contract suite."
    )


def test_make_check_reaches_fitness_after_the_preparation_checkpoint() -> None:
    """Preparation and its clean-tree checkpoint precede the repository fitness gate."""
    commands = _dry_run_make_check()
    clean_index = next(index for index, command in enumerate(commands) if "assert-clean" in command)
    fitness_index = next(index for index, command in enumerate(commands) if "tc-fitness run" in command)

    assert clean_index < fitness_index


def test_assert_clean_rejects_a_real_dirty_git_checkout(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "contract"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "contract@example.invalid"], cwd=tmp_path, check=True)
    (tmp_path / "tracked.txt").write_text("clean\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=tmp_path, check=True)
    command = ["make", "--no-print-directory", "-f", str(MAKEFILE), "assert-clean"]
    assert subprocess.run(command, cwd=tmp_path, check=False).returncode == 0
    (tmp_path / "tracked.txt").write_text("dirty\n")
    assert subprocess.run(command, cwd=tmp_path, check=False).returncode != 0


def test_ci_contract_tests_run_make_check() -> None:
    """A direct CI pytest invocation would bypass the configured local gate."""
    jobs = _ci_workflow().get("jobs") or {}
    steps = (jobs.get("tests") or {}).get("steps") or []
    run_commands = [step.get("run") for step in steps if isinstance(step, dict) and "run" in step]
    assert run_commands == ["make check"], (
        f"{CI_WORKFLOW.name}: the `tests` job runs {run_commands!r}. fix: invoke "
        "`make check` so CI executes the same configured tc-fitness gate as local "
        "contributors."
    )


def test_every_direct_ci_fitness_install_matches_the_locked_engine_commit() -> None:
    """A standalone CI job must not retain an older fitness implementation."""
    dependencies = _project_config()["project"]["dependencies"]
    locked_refs = [
        match.group("commit")
        for dependency in dependencies
        if (
            match := re.fullmatch(
                r"three-cubes-fitness @ git\+https://github\.com/three-cubes/"
                r"tc-fitness\.git@(?P<commit>[a-f0-9]{40})",
                dependency,
            )
        )
    ]
    assert locked_refs == [FITNESS_COMMIT], (
        f"{PYPROJECT.name}: expected the approved immutable three-cubes-fitness "
        f"commit {FITNESS_COMMIT}, found {locked_refs!r}."
    )
    direct_refs = re.findall(
        r"git\+https://github\.com/three-cubes/tc-fitness@"
        r"([a-f0-9]{40})",
        CI_WORKFLOW.read_text(encoding="utf-8"),
    )
    assert direct_refs and set(direct_refs) == {FITNESS_COMMIT}, (
        f"{CI_WORKFLOW.name}: direct fitness installs {direct_refs!r}, not the "
        f"locked engine {FITNESS_COMMIT}. fix: repin every executable fitness "
        "reference with pyproject.toml and regenerate uv.lock."
    )


def test_contract_suite_configures_supported_parallel_pytest_execution() -> None:
    """Removing xdist or ``-n auto`` would make the full required local gate miss its budget."""
    project = _project_config()
    dev_dependencies = project.get("dependency-groups", {}).get("dev", [])
    assert any(dependency.startswith("pytest-xdist") for dependency in dev_dependencies), (
        f"{PYPROJECT.name}: the contract suite has no pytest-xdist dependency, so "
        "the supported `-n auto` acceleration cannot be installed. fix: declare "
        "pytest-xdist in the dev dependency group."
    )
    options = project.get("tool", {}).get("pytest", {}).get("ini_options", {})
    addopts = shlex.split(options.get("addopts", ""))
    assert any(addopts[index : index + 2] == ["-n", "auto"] for index in range(len(addopts))), (
        f"{PYPROJECT.name}: pytest addopts is {options.get('addopts')!r}, so the "
        "complete contract suite runs sequentially. fix: set `addopts = '-n auto'` "
        "while retaining the fitness step argv as `pytest -q`."
    )
    workers = pytest_xdist_auto_num_workers(None)
    assert 1 <= workers <= 6, (
        f"pytest auto-selected {workers} workers. fix: cap automatic workers at six "
        "so subprocess-heavy contracts do not oversubscribe contributor machines."
    )
