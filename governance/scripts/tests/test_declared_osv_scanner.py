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


def test_composite_installs_and_verifies_only_when_contract_is_required() -> None:
    document = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
    steps = (document.get("runs") or {}).get("steps") or []
    detect = next(step for step in steps if step.get("id") == "osv-contract")
    install = next(step for step in steps if step.get("name") == "Install declared OSV scanner")

    assert "declared_osv_contract.py" in detect["run"]
    assert install["if"] == "steps.osv-contract.outputs.required == 'true'"
    assert "osv-scanner_SHA256SUMS" in install["run"]
    assert '"$install_dir/osv-scanner" --version' in install["run"]
    assert "steps.osv-contract.outputs.version" in install["env"]["OSV_SCANNER_VERSION"]

