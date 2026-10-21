"""Checkov is provisioned as a uv tool, pinned from scanner-versions.json (PLA-471).

The provisioner is driven through its real entry point. Only the `uv` executable
is a stand-in, put first on PATH: it records its argv and lays down the tool
directory a real `uv tool install` would, so the test needs no network.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

PIPELINES_ROOT = Path(__file__).resolve().parents[3]
ACTION_DIR = PIPELINES_ROOT / "actions" / "python-gate-body"
PROVISIONER = ACTION_DIR / "provision_scanners.py"
CATALOGUE = ACTION_DIR / "scanner-versions.json"
CONSTRAINTS = ACTION_DIR / "checkov-constraints.txt"

FAKE_UV = r"""#!/usr/bin/env python3
import os
import pathlib
import sys

pathlib.Path(os.environ["FAKE_UV_LOG"]).write_text("\n".join(sys.argv[1:]) + "\n", encoding="utf-8")
tool_dir = pathlib.Path(os.environ["UV_TOOL_DIR"]) / "checkov" / "bin"
tool_bin = pathlib.Path(os.environ["UV_TOOL_BIN_DIR"])
tool_dir.mkdir(parents=True)
tool_bin.mkdir(parents=True)
version = sys.argv[-1].split("==", 1)[1]
python = tool_dir / "python"
body = "exit 1\n" if os.environ.get("FAKE_INSPECT_FAILS") else f"echo '{os.environ['FAKE_DISTRIBUTIONS']}'\n"
probe = 'echo "${UV_PYTHON-}${PYTHONPATH-}${PYTHONHOME-}${VIRTUAL_ENV-}" > "$FAKE_UV_LOG.probe"\n'
python.write_text("#!/bin/sh\n" + probe + body, encoding="utf-8")
seen = "".join(os.environ.get(name, "") for name in ("UV_PYTHON", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"))
pathlib.Path(os.environ["FAKE_UV_LOG"] + ".env").write_text(seen, encoding="utf-8")
python.chmod(0o755)
checkov = tool_bin / "checkov"
checkov.write_text(
    "#!/bin/sh\n"
    'if [ "$1" = --interpreter-state ]; then echo "${PYTHONPATH-}${PYTHONHOME-}${VIRTUAL_ENV-}"; exit 0; fi\n'
    f"echo {version}\n",
    encoding="utf-8",
)
checkov.chmod(0o755)
"""


def _pinned_checkov() -> str:
    return json.loads(CATALOGUE.read_text(encoding="utf-8"))["checkov"]["version"]


def _pins() -> dict[str, str]:
    """The committed constraints, as `name -> version` (the distributions a real install holds)."""
    pins = {}
    for line in CONSTRAINTS.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].split(";", 1)[0].strip()
        if entry:
            name, version = entry.split("==")
            pins[name] = version
    return pins


def _provision(
    tmp_path: Path,
    *,
    asteval: str | None = None,
    distributions: dict[str, str] | None = None,
    extra_env: dict[str, str] | None = None,
):
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    uv = fake_bin / "uv"
    uv.write_text(FAKE_UV, encoding="utf-8")
    uv.chmod(uv.stat().st_mode | stat.S_IXUSR)
    scanner_bin = tmp_path / "scanners" / "bin"
    installed = {**_pins(), **(distributions or {})}
    if asteval is not None:
        installed["asteval"] = asteval
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "INSTALL_CHECKOV_SCANNER": "true",
        "TC_SCANNER_BIN_DIR": str(scanner_bin),
        "FAKE_UV_LOG": str(tmp_path / "uv.log"),
        "FAKE_DISTRIBUTIONS": json.dumps(installed),
        **(extra_env or {}),
    }
    result = subprocess.run(
        [sys.executable, str(PROVISIONER)], env=env, capture_output=True, text=True, check=False, cwd=tmp_path
    )
    return result, scanner_bin


def test_checkov_installs_as_a_uv_tool_at_the_catalogued_version(tmp_path: Path) -> None:
    """`uv tool install` gets exactly the scanner-versions.json pin and the asteval override."""
    version = _pinned_checkov()

    result, scanner_bin = _provision(tmp_path)

    assert result.returncode == 0, result.stderr
    argv = (tmp_path / "uv.log").read_text(encoding="utf-8").split()
    assert argv[:3] == ["tool", "install", "--force"]
    assert argv[-1] == f"checkov=={version}"
    overrides = Path(argv[argv.index("--overrides") + 1])
    assert overrides.read_text(encoding="utf-8").strip() == "asteval>=1.0.9,<1.1"
    assert Path(argv[argv.index("--constraints") + 1]) == CONSTRAINTS
    published = scanner_bin / "checkov"
    assert published.is_symlink()
    reported = subprocess.run([str(published), "--version"], capture_output=True, text=True, check=True)
    assert reported.stdout.strip() == version


@pytest.mark.parametrize("name", ["UV_PYTHON", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"])
def test_the_callers_interpreter_state_reaches_neither_the_install_nor_the_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """A gate's PYTHONPATH would make the inspection report another site-packages as constraint drift.

    In process: a PYTHONHOME in the provisioner's own environment would stop its interpreter starting.
    """
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    uv = fake_bin / "uv"
    uv.write_text(FAKE_UV, encoding="utf-8")
    uv.chmod(uv.stat().st_mode | stat.S_IXUSR)
    for key, value in {
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "INSTALL_CHECKOV_SCANNER": "true",
        "TC_SCANNER_BIN_DIR": str(tmp_path / "scanners" / "bin"),
        "FAKE_UV_LOG": str(tmp_path / "uv.log"),
        "FAKE_DISTRIBUTIONS": json.dumps(_pins()),
        name: "/caller/state",
    }.items():
        monkeypatch.setenv(key, value)

    assert _provisioner_module().main() == 0

    assert (tmp_path / "uv.log.env").read_text(encoding="utf-8") == ""
    assert (tmp_path / "uv.log.probe").read_text(encoding="utf-8").strip() == ""


def test_a_vulnerable_asteval_in_the_tool_environment_fails_the_install(tmp_path: Path) -> None:
    """The override is proved on the environment uv built, not assumed."""
    result, scanner_bin = _provision(tmp_path, asteval="1.0.6")

    assert result.returncode == 1
    assert "must keep asteval in asteval>=1.0.9,<1.1" in result.stderr
    assert not (scanner_bin / "checkov").exists()


def test_a_requested_checkov_that_differs_from_the_catalogue_is_refused(tmp_path: Path) -> None:
    """A caller cannot move the pin: scanner-versions.json is the one place it lives."""
    result, _ = _provision(tmp_path, extra_env={"CHECKOV_VERSION": "0.0.1"})

    assert result.returncode == 1
    assert "differs from catalogued version" in result.stderr
    assert not (tmp_path / "uv.log").exists()


def test_no_second_checkov_lock_or_library_dependency_remains() -> None:
    """The workspace lock holds no checkov, and the scanner has no project of its own."""
    assert not (ACTION_DIR / "checkov-tool").exists()
    platform_root = PIPELINES_ROOT.parents[1]
    lock = platform_root / "uv.lock"
    if not lock.is_file():
        pytest.skip("the exported tree carries no workspace lock")
    assert 'name = "checkov"' not in lock.read_text(encoding="utf-8")


def test_a_tool_environment_that_cannot_be_inspected_fails_the_install(tmp_path: Path) -> None:
    result, scanner_bin = _provision(tmp_path, extra_env={"FAKE_INSPECT_FAILS": "1"})

    assert result.returncode == 1
    assert "cannot be inspected" in result.stderr
    assert not (scanner_bin / "checkov").exists()


def test_a_tool_environment_holding_another_checkov_fails_the_install(tmp_path: Path) -> None:
    result, scanner_bin = _provision(tmp_path, distributions={"checkov": "0.0.1"})

    assert result.returncode == 1
    assert "holds checkov 0.0.1" in result.stderr
    assert not (scanner_bin / "checkov").exists()


def test_an_unparseable_asteval_version_fails_the_install(tmp_path: Path) -> None:
    result, _ = _provision(tmp_path, asteval="dev")

    assert result.returncode == 1
    assert "invalid asteval version: dev" in result.stderr


def test_a_symlinked_tool_directory_is_refused(tmp_path: Path) -> None:
    """The owned cache entry is never followed out of the cache."""
    version = _pinned_checkov()
    target = tmp_path / "scanners" / "checkov" / version
    target.mkdir(parents=True)
    (target / ".tc-pipelines-scanner").write_text(
        f"tc-pipelines-scanner-v1\ntool=checkov\nversion={version}\n", encoding="utf-8"
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (target / "tools").symlink_to(elsewhere)

    result, _ = _provision(tmp_path)

    assert result.returncode == 1
    assert "symlinked Checkov tool directory" in result.stderr
    assert not (tmp_path / "uv.log").exists()


def test_the_published_checkov_runs_without_the_callers_interpreter_state(tmp_path: Path) -> None:
    """The gate's PYTHONPATH points at another interpreter's site-packages; the scanner never sees it."""
    result, scanner_bin = _provision(tmp_path)
    assert result.returncode == 0, result.stderr

    seen = subprocess.run(
        [str(scanner_bin / "checkov"), "--interpreter-state"],
        env={
            **os.environ,
            "PYTHONPATH": "/caller/site-packages",
            "PYTHONHOME": "/caller",
            "VIRTUAL_ENV": "/caller/.venv",
        },
        capture_output=True,
        text=True,
        check=True,
    )

    assert seen.stdout.strip() == ""


def test_the_committed_constraints_pin_the_catalogued_checkov_and_every_line_exactly() -> None:
    """The pins are generated from the catalogue; a bump of one without the other is caught here."""
    pins = _pins()
    assert pins["checkov"] == _pinned_checkov()
    assert "ecdsa" not in pins
    assert "python-ecdsa" not in pins
    for line in CONSTRAINTS.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].split(";", 1)[0].strip()
        assert not entry or re.fullmatch(r"[A-Za-z0-9._-]+==[0-9][0-9A-Za-z.!+]*", entry), line


def test_a_distribution_outside_the_constraints_fails_the_install(tmp_path: Path) -> None:
    """A transitive dependency that floats past the pins is caught on the environment uv built."""
    result, scanner_bin = _provision(tmp_path, distributions={"left-pad": "1.0.0"})

    assert result.returncode == 1
    assert "differs from checkov-constraints.txt: left-pad 1.0.0" in result.stderr
    assert not (scanner_bin / "checkov").exists()


def test_a_distribution_at_another_version_than_its_pin_fails_the_install(tmp_path: Path) -> None:
    assert _pins()["yarl"] != "0.0.1"
    result, _ = _provision(tmp_path, distributions={"yarl": "0.0.1"})

    assert result.returncode == 1
    assert "yarl 0.0.1" in result.stderr


@pytest.mark.parametrize("forbidden", ["ecdsa", "python-ecdsa"])
def test_a_tool_environment_holding_ecdsa_fails_the_install(tmp_path: Path, forbidden: str) -> None:
    result, scanner_bin = _provision(tmp_path, distributions={forbidden: "0.19.2"})

    assert result.returncode == 1
    assert f"forbidden distribution: {forbidden}" in result.stderr
    assert not (scanner_bin / "checkov").exists()


def test_a_tool_environment_reporting_an_unreadable_distribution_list_fails_the_install(
    tmp_path: Path,
) -> None:
    result, scanner_bin = _provision(tmp_path, extra_env={"FAKE_DISTRIBUTIONS": "not json"})

    assert result.returncode == 1
    assert "unreadable distribution list" in result.stderr
    assert not (scanner_bin / "checkov").exists()


def _provisioner_module():
    spec = importlib.util.spec_from_file_location("provision_scanners_under_test", PROVISIONER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("constraints", "expected"),
    [
        (None, "cannot read the Checkov constraints"),
        ("checkov>=3.2\n", "must pin each distribution with =="),
        ("yarl==1.25.1\n", "pin checkov None, not the catalogued"),
        (f"checkov=={_pinned_checkov()}\necdsa==0.19.2\n", "forbidden distribution: ecdsa"),
    ],
)
def test_a_constraints_file_that_does_not_pin_the_catalogued_checkov_cleanly_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, constraints: str | None, expected: str
) -> None:
    """The committed pins are checked before uv runs, so a bad file never reaches an install."""
    module = _provisioner_module()
    pins = tmp_path / "constraints.txt"
    if constraints is not None:
        pins.write_text(constraints, encoding="utf-8")
    monkeypatch.setattr(module, "CHECKOV_CONSTRAINTS", pins)

    with pytest.raises(module.ProvisionError, match=expected):
        module._install_checkov(tmp_path / "root", tmp_path / "bin")
