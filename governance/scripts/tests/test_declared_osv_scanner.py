"""The shared gate provisions OSV only for an explicit, exact SCA contract."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "actions" / "python-gate-body" / "declared_osv_contract.py"
ACTION = REPO_ROOT / "actions" / "python-gate-body" / "action.yml"


def _run(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_repo_without_sca_contract_does_not_request_install(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.tc_fitness]\n", encoding="utf-8")

    result = _run(tmp_path)

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["required=false", "version="]


def test_repo_without_pyproject_does_not_request_install(tmp_path: Path) -> None:
    result = _run(tmp_path)

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["required=false", "version="]


def test_explicitly_optional_contract_does_not_request_install(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.tc_fitness.core_checks.osv_scanner_sca]\nrequired = false\n",
        encoding="utf-8",
    )

    result = _run(tmp_path)

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["required=false", "version="]


def test_required_contract_emits_the_consumers_exact_pin(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.tc_fitness.core_checks.osv_scanner_sca]
required = true
scanner_version = "2.2.4"
lockfiles = ["uv.lock", "pnpm-lock.yaml"]
""".strip(),
        encoding="utf-8",
    )

    result = _run(tmp_path)

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["required=true", "version=2.2.4"]


@pytest.mark.parametrize("required", ['"true"', "1", '"false"'])
def test_malformed_required_value_cannot_silently_disable_scanning(tmp_path: Path, required: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.tc_fitness.core_checks.osv_scanner_sca]\n"
        f"required = {required}\n"
        'scanner_version = "2.2.4"\n'
        'lockfiles = ["uv.lock"]\n',
        encoding="utf-8",
    )

    result = _run(tmp_path)

    assert result.returncode != 0
    assert "required must be a boolean" in result.stderr


@pytest.mark.parametrize(
    "lockfiles_line",
    ["", "lockfiles = []\n", 'lockfiles = "uv.lock"\n', 'lockfiles = ["", 1]\n'],
)
def test_required_contract_rejects_missing_or_malformed_lockfiles(
    tmp_path: Path, lockfiles_line: str
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.tc_fitness.core_checks.osv_scanner_sca]\n"
        "required = true\n"
        'scanner_version = "2.2.4"\n'
        + lockfiles_line,
        encoding="utf-8",
    )

    result = _run(tmp_path)

    assert result.returncode != 0
    assert "non-empty lockfiles list" in result.stderr


@pytest.mark.parametrize("version", ["", "v2.2.4", "2.2", "latest", "2.2.4 # comment"])
def test_required_contract_rejects_a_missing_or_non_exact_pin(tmp_path: Path, version: str) -> None:
    version_line = f'scanner_version = "{version}"\n' if version else ""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.tc_fitness.core_checks.osv_scanner_sca]\nrequired = true\n" + version_line,
        encoding="utf-8",
    )

    result = _run(tmp_path)

    assert result.returncode != 0
    assert "exact scanner_version" in result.stderr


def test_composite_installs_and_verifies_only_when_lane_owns_provisioning() -> None:
    document = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
    steps = (document.get("runs") or {}).get("steps") or []
    detect = next(step for step in steps if step.get("id") == "osv-contract")
    install = next(step for step in steps if step.get("name") == "Install declared OSV scanner")

    assert "declared_osv_contract.py" in detect["run"]
    assert detect["if"] == "inputs.provision-osv-scanner == 'true'"
    assert install["if"] == "steps.osv-contract.outputs.required == 'true'"
    assert "osv-scanner_SHA256SUMS" in install["run"]
    assert '"$install_dir/osv-scanner" --version' in install["run"]
    assert "steps.osv-contract.outputs.version" in install["env"]["OSV_SCANNER_VERSION"]


def test_full_and_sharded_workflow_provision_scanner_exactly_once() -> None:
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "python-quality-gate.yml").read_text(
            encoding="utf-8"
        )
    )
    jobs = workflow["jobs"]

    unsharded_count = int(
        jobs["quality"]["steps"][0]["with"]["provision-osv-scanner"] is True
    )
    sharded_count = (
        4
        * int(
            jobs["quality-shard"]["steps"][0]["with"]["provision-osv-scanner"]
            is True
        )
        + int(
            jobs["quality-non-shard"]["steps"][1]["with"]["provision-osv-scanner"]
            is True
        )
    )

    assert unsharded_count == 1
    assert sharded_count == 1
