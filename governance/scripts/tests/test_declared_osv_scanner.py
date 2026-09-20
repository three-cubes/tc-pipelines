"""The shared gate provisions OSV only for an explicit, exact SCA contract."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

from assurance.live_scanners import _rule_database, scanner_outcome

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "actions" / "python-gate-body" / "declared_osv_contract.py"
ACTION = REPO_ROOT / "actions" / "python-gate-body" / "action.yml"
PROVISIONER = REPO_ROOT / "actions" / "python-gate-body" / "provision-scanners.sh"
SCANNER_CATALOGUE = REPO_ROOT / "actions" / "python-gate-body" / "scanner-versions.json"
CHECKOV_LOCK = REPO_ROOT / "actions" / "python-gate-body" / "checkov-tool" / "uv.lock"


def _default_scanner_bin() -> Path:
    cache_home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache_home / "tc-pipelines" / "scanners" / "bin"


def _catalogued_osv_version() -> str:
    return json.loads(SCANNER_CATALOGUE.read_text(encoding="utf-8"))["osv-scanner"]["version"]


def _lane_owns_provisioning(value: bool | str, *, shard_tier: str) -> bool:
    if isinstance(value, bool):
        return value
    if value == "${{ inputs.shard-tier == '' }}":
        return shard_tier == ""
    raise AssertionError(f"unknown scanner-provisioning expression: {value}")


def _run(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )


def _run_with_python310_tomli_fallback(repo: Path) -> subprocess.CompletedProcess[str]:
    """Run the reader with ``tomllib`` unavailable and a ``tomli`` substitute."""
    runner = f"""
import importlib.abc
import runpy
import sys
import tomllib as stdlib_tomllib
import types

fallback = types.ModuleType("tomli")
fallback.loads = stdlib_tomllib.loads
sys.modules["tomli"] = fallback
sys.modules.pop("tomllib", None)

class BlockTomllib(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "tomllib":
            raise ModuleNotFoundError("No module named 'tomllib'", name="tomllib")
        return None

sys.meta_path.insert(0, BlockTomllib())
sys.argv = [{str(SCRIPT)!r}, "--repo-root", {str(repo)!r}]
runpy.run_path({str(SCRIPT)!r}, run_name="__main__")
"""
    return subprocess.run(
        [sys.executable, "-c", runner],
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


def test_required_contract_rejects_a_consumer_pin_that_differs_from_the_catalogue(
    tmp_path: Path,
) -> None:
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

    assert result.returncode != 0
    assert "consumer declares OSV Scanner 2.2.4, but tc-pipelines provisions" in result.stderr


def test_required_contract_emits_its_exact_catalogued_pin(tmp_path: Path) -> None:
    version = _catalogued_osv_version()
    (tmp_path / "pyproject.toml").write_text(
        "[tool.tc_fitness.core_checks.osv_scanner_sca]\n"
        "required = true\n"
        f'scanner_version = "{version}"\n'
        'lockfiles = ["uv.lock"]\n',
        encoding="utf-8",
    )

    result = _run(tmp_path)

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["required=true", f"version={version}"]


def test_dedicated_config_wins_over_pyproject_for_required_contract(
    tmp_path: Path,
) -> None:
    version = _catalogued_osv_version()
    (tmp_path / "pyproject.toml").write_text(
        "[tool.tc_fitness.core_checks.osv_scanner_sca]\nrequired = false\n",
        encoding="utf-8",
    )
    (tmp_path / ".tc-fitness.toml").write_text(
        f"""
[core_checks.osv_scanner_sca]
required = true
scanner_version = "{version}"
lockfiles = ["uv.lock"]
""".strip(),
        encoding="utf-8",
    )

    result = _run(tmp_path)
    assert result.returncode == 0
    assert result.stdout.splitlines() == ["required=true", f"version={version}"]


@pytest.mark.parametrize(
    ("name", "contract"),
    [
        (
            ".tc-fitness.toml",
            """
[core_checks.osv_scanner_sca]
required = true
scanner_version = "@CATALOGUED_VERSION@"
lockfiles = [
  "uv.lock",
]
""",
        ),
        (
            "pyproject.toml",
            """
[tool.tc_fitness.core_checks.osv_scanner_sca]
required = true
scanner_version = "@CATALOGUED_VERSION@"
lockfiles = [
  "uv.lock",
]
""",
        ),
    ],
)
def test_required_contract_accepts_multiline_lockfiles(tmp_path: Path, name: str, contract: str) -> None:
    contract = contract.replace("@CATALOGUED_VERSION@", _catalogued_osv_version())
    (tmp_path / name).write_text(contract.strip(), encoding="utf-8")

    result = _run(tmp_path)

    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "required=true",
        f"version={_catalogued_osv_version()}",
    ]


def test_python310_tomli_fallback_reads_multiline_contract(tmp_path: Path) -> None:
    version = _catalogued_osv_version()
    (tmp_path / ".tc-fitness.toml").write_text(
        f"""
[core_checks.osv_scanner_sca]
required = true
scanner_version = "{version}"
lockfiles = [
  "uv.lock",
]
""".strip(),
        encoding="utf-8",
    )

    result = _run_with_python310_tomli_fallback(tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["required=true", f"version={version}"]


def test_provisioner_runs_under_python310_with_its_tomli_dependency(
    tmp_path: Path,
) -> None:
    scanner_bin = _default_scanner_bin()
    current_environment = os.environ.copy()
    current_environment.update(
        INSTALL_CHECKOV_SCANNER="true",
        INSTALL_OSV_SCANNER="true",
        TC_SCANNER_BIN_DIR=str(scanner_bin),
    )
    warm_cache = subprocess.run(
        ["bash", str(PROVISIONER)],
        cwd=REPO_ROOT,
        env=current_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert warm_cache.returncode == 0, warm_cache.stdout + warm_cache.stderr

    python310_environment = tmp_path / "python310"
    create_environment = subprocess.run(
        ["uv", "venv", "--python", "3.10", str(python310_environment)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert create_environment.returncode == 0, create_environment.stdout + create_environment.stderr
    python310 = python310_environment / "bin" / "python"
    install_tomli = subprocess.run(
        ["uv", "pip", "install", "--python", str(python310), "tomli==2.3.0"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert install_tomli.returncode == 0, install_tomli.stdout + install_tomli.stderr
    environment = current_environment | {
        "PATH": os.pathsep.join((str(python310_environment / "bin"), current_environment["PATH"]))
    }

    result = subprocess.run(
        ["bash", str(PROVISIONER)],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Installed isolated Checkov" in result.stdout
    assert "Installed verified OSV Scanner" in result.stdout
    interpreter_version = subprocess.run(
        [str(python310), "--version"], capture_output=True, text=True, check=True
    )
    assert "Python 3.10" in interpreter_version.stdout + interpreter_version.stderr


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
    version = _catalogued_osv_version()
    (tmp_path / "pyproject.toml").write_text(
        "[tool.tc_fitness.core_checks.osv_scanner_sca]\n"
        "required = true\n"
        f'scanner_version = "{version}"\n' + lockfiles_line,
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
    assert "uv pip install --python python --no-deps tomli==2.3.0" in detect["run"]
    assert detect["if"] == "inputs.provision-osv-scanner == 'true'"
    assert install["if"] == "steps.osv-contract.outputs.required == 'true'"
    assert "provision-scanners.sh" in install["run"]
    assert install["env"]["OSV_SCANNER_VERSION"] == "${{ steps.osv-contract.outputs.version }}"
    assert install["env"]["TC_SCANNER_BIN_DIR"] == "${{ runner.temp }}/tc-pipelines-scanners/bin"
    assert 'export TC_SCANNER_PATH_FILE="$GITHUB_PATH"' in install["run"]
    assert "GITHUB_PATH" not in PROVISIONER.read_text(encoding="utf-8")


def test_full_and_partitioned_sharded_workflow_provision_scanner_exactly_once() -> None:
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "python-quality-gate.yml").read_text(encoding="utf-8")
    )
    jobs = workflow["jobs"]

    unsharded_count = int(jobs["quality"]["steps"][0]["with"]["provision-osv-scanner"] is True)
    shard_owner = jobs["quality-shard"]["steps"][0]["with"]["provision-osv-scanner"]
    partitioned_sharded_count = 4 * int(_lane_owns_provisioning(shard_owner, shard_tier="matrix")) + int(
        jobs["quality-non-shard"]["steps"][1]["with"]["provision-osv-scanner"] is True
    )

    assert unsharded_count == 1
    assert partitioned_sharded_count == 1


def test_unpartitioned_shards_keep_required_scanner_available() -> None:
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "python-quality-gate.yml").read_text(encoding="utf-8")
    )

    shard_owner = workflow["jobs"]["quality-shard"]["steps"][0]["with"]["provision-osv-scanner"]
    assert _lane_owns_provisioning(shard_owner, shard_tier="") is True


def test_real_checkov_install_uses_explicit_bin_and_preserves_consumer_lock_environment(
    tmp_path: Path,
) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "pyproject.toml").write_text(
        '[project]\nname = "scanner-consumer-fixture"\nversion = "0.0.0"\n'
        'requires-python = ">=3.12"\ndependencies = ["asteval==1.0.9"]\n',
        encoding="utf-8",
    )
    for command in (
        ["uv", "lock", "--python", "3.12"],
        ["uv", "sync", "--locked", "--python", "3.12"],
    ):
        result = subprocess.run(command, cwd=consumer, text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
    lock_before = (consumer / "uv.lock").read_bytes()
    install_bin = _default_scanner_bin()
    path_file = tmp_path / "scanner-path"
    environment = {
        key: value for key, value in os.environ.items() if key not in {"RUNNER_TEMP", "GITHUB_PATH"}
    }
    environment.update(
        INSTALL_CHECKOV_SCANNER="true",
        TC_SCANNER_BIN_DIR=str(install_bin),
        TC_SCANNER_PATH_FILE=str(path_file),
    )

    provision = subprocess.run(
        ["bash", str(PROVISIONER)],
        cwd=consumer,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    consumer_asteval = subprocess.run(
        [
            str(consumer / ".venv" / "bin" / "python"),
            "-c",
            "import asteval; print(asteval.__version__)",
        ],
        cwd=consumer,
        text=True,
        capture_output=True,
        check=False,
    )
    checkov_python = (install_bin / "checkov").resolve().parent / "python"
    checkov_asteval = subprocess.run(
        [str(checkov_python), "-c", "import asteval; print(asteval.__version__)"],
        cwd=consumer,
        text=True,
        capture_output=True,
        check=False,
    )
    checkov_version = subprocess.run(
        [str(install_bin / "checkov"), "--version"],
        cwd=consumer,
        text=True,
        capture_output=True,
        check=False,
    )
    checkov_ecdsa = subprocess.run(
        [
            str(checkov_python),
            "-c",
            "import importlib.metadata as m; print(any(d.metadata['Name'].lower() in {'ecdsa', 'python-ecdsa'} for d in m.distributions()))",
        ],
        cwd=consumer,
        text=True,
        capture_output=True,
        check=False,
    )
    checkov_clean = subprocess.run(
        [
            str(install_bin / "checkov"),
            "-d",
            str(REPO_ROOT / "assurance/fixtures/live-scanners/checkov/compliant"),
            "--check",
            "CKV_AWS_20",
            "--output",
            "json",
            "--quiet",
        ],
        cwd=consumer,
        text=True,
        capture_output=True,
        check=False,
    )
    checkov_violation = subprocess.run(
        [
            str(install_bin / "checkov"),
            "-d",
            str(REPO_ROOT / "assurance/fixtures/live-scanners/checkov/violation"),
            "--check",
            "CKV_AWS_20",
            "--output",
            "json",
            "--quiet",
        ],
        cwd=consumer,
        text=True,
        capture_output=True,
        check=False,
    )

    lock = tomllib.loads(CHECKOV_LOCK.read_text(encoding="utf-8"))
    locked_asteval = next(row["version"] for row in lock["package"] if row["name"] == "asteval")
    assert tuple(int(part) for part in locked_asteval.split(".")) >= (1, 0, 9)
    assert tuple(int(part) for part in locked_asteval.split(".")) < (1, 1)
    assert (
        provision.returncode,
        (install_bin / "checkov").is_file(),
        consumer_asteval.stdout.strip(),
        checkov_asteval.stdout.strip(),
        checkov_version.returncode,
        checkov_ecdsa.stdout.strip(),
        scanner_outcome(checkov_clean.returncode, checkov_clean.stdout, "CKV_AWS_20"),
        scanner_outcome(checkov_violation.returncode, checkov_violation.stdout, "CKV_AWS_20"),
        (consumer / "uv.lock").read_bytes() == lock_before,
    ) == (
        0,
        True,
        "1.0.9",
        locked_asteval,
        0,
        "False",
        "clean",
        "finding",
        True,
    ), (
        provision.stdout
        + provision.stderr
        + consumer_asteval.stderr
        + checkov_asteval.stderr
        + checkov_version.stdout
        + checkov_version.stderr
        + checkov_ecdsa.stderr
        + checkov_clean.stdout
        + checkov_clean.stderr
        + checkov_violation.stdout
        + checkov_violation.stderr
    )
    assert path_file.read_text(encoding="utf-8").splitlines() == [str(install_bin)]
    rule_kind, rule_identity, _ = _rule_database("checkov", checkov_clean.stdout, install_bin / "checkov")
    assert rule_kind == "packaged-checkov-policy-tree"
    assert rule_identity.startswith("sha256:")


def test_make_prepare_exposes_pinned_scanners_to_a_later_process() -> None:
    environment = os.environ.copy()
    environment.pop("TC_SCANNER_BIN_DIR", None)
    environment.pop("TC_SCANNER_PATH_FILE", None)
    scanner_bin = str(_default_scanner_bin().resolve())
    environment["PATH"] = os.pathsep.join(
        entry
        for entry in environment.get("PATH", "").split(os.pathsep)
        if str(Path(entry).expanduser().resolve()) != scanner_bin
    )

    prepared = subprocess.run(
        ["make", "prepare"],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    evaluated = subprocess.run(
        ["make", "scanner-versions"],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    catalogue = json.loads(SCANNER_CATALOGUE.read_text(encoding="utf-8"))

    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    assert evaluated.returncode == 0, evaluated.stdout + evaluated.stderr
    assert scanner_bin in evaluated.stdout
    assert catalogue["osv-scanner"]["version"] in evaluated.stdout
    assert catalogue["checkov"]["version"] in evaluated.stdout


def test_real_osv_install_checks_release_hash_and_executes_json_reports(
    tmp_path: Path,
) -> None:
    install_bin = _default_scanner_bin()
    path_file = tmp_path / "scanner-path"
    environment = {
        key: value for key, value in os.environ.items() if key not in {"RUNNER_TEMP", "GITHUB_PATH"}
    }
    environment.update(
        INSTALL_OSV_SCANNER="true",
        TC_SCANNER_BIN_DIR=str(install_bin),
        TC_SCANNER_PATH_FILE=str(path_file),
    )
    provision = subprocess.run(
        ["bash", str(PROVISIONER)],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    installed_version = subprocess.run(
        [str(install_bin / "osv-scanner"), "--version"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    catalogue = json.loads(SCANNER_CATALOGUE.read_text(encoding="utf-8"))
    outcomes = []
    for case, expected_finding in (
        ("compliant", None),
        ("violation", "GHSA-35jh-r3h4-6jhm"),
    ):
        lockfile = REPO_ROOT / "assurance/fixtures/live-scanners/osv" / case / "package-lock.json"
        report = subprocess.run(
            [
                str(install_bin / "osv-scanner"),
                "--lockfile",
                str(lockfile),
                "--format",
                "json",
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        outcomes.append(scanner_outcome(report.returncode, report.stdout, expected_finding))

    assert provision.returncode == 0, provision.stdout + provision.stderr
    assert installed_version.returncode == 0
    assert catalogue["osv-scanner"]["version"] in installed_version.stdout + installed_version.stderr
    assert outcomes == ["clean", "finding"]
    assert path_file.read_text(encoding="utf-8").splitlines() == [str(install_bin)]

    scanner_root = install_bin.parent
    binary = scanner_root / "osv-scanner" / catalogue["osv-scanner"]["version"] / "osv-scanner"
    machine = platform.machine().lower()
    architecture = "amd64" if machine in {"amd64", "x86_64"} else "arm64"
    expected_hash = catalogue["osv-scanner"]["sha256"][f"{platform.system().lower()}_{architecture}"]
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == expected_hash

    # A damaged owned cache is replaced from the same verified release bytes.
    source_dir = tmp_path / "release"
    source_dir.mkdir()
    asset = f"osv-scanner_{platform.system().lower()}_{architecture}"
    fixture_asset = source_dir / asset
    fixture_asset.write_bytes(binary.read_bytes())
    isolated_bin = tmp_path / "isolated-scanners" / "bin"
    isolated_environment = environment | {
        "TC_SCANNER_BIN_DIR": str(isolated_bin),
        "TC_OSV_RELEASE_BASE_URL": source_dir.as_uri(),
    }
    isolated_install = subprocess.run(
        ["bash", str(PROVISIONER)],
        cwd=REPO_ROOT,
        env=isolated_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    isolated_binary = (
        isolated_bin.parent / "osv-scanner" / catalogue["osv-scanner"]["version"] / "osv-scanner"
    )
    assert isolated_install.returncode == 0, isolated_install.stdout + isolated_install.stderr
    isolated_binary.write_bytes(b"corrupted scanner cache")
    repaired = subprocess.run(
        ["bash", str(PROVISIONER)],
        cwd=REPO_ROOT,
        env=isolated_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert repaired.returncode == 0, repaired.stdout + repaired.stderr
    assert hashlib.sha256(isolated_binary.read_bytes()).hexdigest() == expected_hash

    # A verified cache entry with damaged executable metadata is repaired in place.
    isolated_binary.chmod(0o644)
    mode_repaired = subprocess.run(
        ["bash", str(PROVISIONER)],
        cwd=REPO_ROOT,
        env=isolated_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert mode_repaired.returncode == 0, mode_repaired.stdout + mode_repaired.stderr
    assert stat.S_IMODE(isolated_binary.stat().st_mode) == 0o755
    assert hashlib.sha256(isolated_binary.read_bytes()).hexdigest() == expected_hash

    # A valid cache avoids all network access, including the release checksum fetch.
    offline_environment = isolated_environment | {
        "TC_OSV_RELEASE_BASE_URL": (tmp_path / "missing-source").as_uri(),
    }
    cached = subprocess.run(
        ["bash", str(PROVISIONER)],
        cwd=REPO_ROOT,
        env=offline_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert cached.returncode == 0, cached.stdout + cached.stderr


def test_osv_provisioner_rejects_stale_version_and_unowned_cache_paths(
    tmp_path: Path,
) -> None:
    catalogue = json.loads(SCANNER_CATALOGUE.read_text(encoding="utf-8"))
    version = catalogue["osv-scanner"]["version"]
    bin_dir = tmp_path / "scanner-tools" / "bin"
    base_environment = {
        key: value for key, value in os.environ.items() if key not in {"RUNNER_TEMP", "GITHUB_PATH"}
    }
    stale = base_environment | {
        "INSTALL_OSV_SCANNER": "true",
        "OSV_SCANNER_VERSION": "2.5.0",
        "TC_SCANNER_BIN_DIR": str(bin_dir),
    }
    stale_result = subprocess.run(
        ["bash", str(PROVISIONER)],
        cwd=REPO_ROOT,
        env=stale,
        capture_output=True,
        text=True,
        check=False,
    )
    assert stale_result.returncode != 0
    assert "differs from catalogued version" in stale_result.stderr

    external = tmp_path / "external-tools"
    external.mkdir()
    sentinel = external / "keep.txt"
    sentinel.write_text("caller-owned", encoding="utf-8")
    tool_root = bin_dir.parent / "osv-scanner"
    tool_root.symlink_to(external, target_is_directory=True)
    environment = base_environment | {
        "INSTALL_OSV_SCANNER": "true",
        "TC_SCANNER_BIN_DIR": str(bin_dir),
    }
    refused_symlink = subprocess.run(
        ["bash", str(PROVISIONER)],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert refused_symlink.returncode != 0
    assert "cannot be a symlink" in refused_symlink.stderr
    assert sentinel.read_text(encoding="utf-8") == "caller-owned"

    tool_root.unlink()
    tool_root.mkdir()
    unowned = tool_root / version
    unowned.mkdir()
    keep = unowned / "keep.txt"
    keep.write_text("unowned", encoding="utf-8")
    refused_unowned = subprocess.run(
        ["bash", str(PROVISIONER)],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert refused_unowned.returncode != 0
    assert "without our ownership marker" in refused_unowned.stderr
    assert keep.read_text(encoding="utf-8") == "unowned"
