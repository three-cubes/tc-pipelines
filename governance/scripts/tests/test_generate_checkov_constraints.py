"""The Checkov constraints are written by a committed generator, never by hand (PLA-471).

The generator runs for real in a throwaway copy of the monorepo layout. Only `uv` is a
stand-in on PATH: like `uv pip compile --output-file` it keeps the pins already in the
output file, so a rerun at the same Checkov must leave both committed copies unchanged.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

PIPELINES_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = PIPELINES_ROOT.parents[1]
ACTION_DIR = PIPELINES_ROOT / "actions" / "python-gate-body"
PACKAGED = REPO_ROOT / "assurance" / "fitness" / "src" / "tc_fitness" / "checkov-constraints.txt"
GENERATOR = "generate-checkov-constraints.sh"

if not PACKAGED.is_file():
    pytest.skip("the exported pipelines tree carries no tc-fitness package", allow_module_level=True)

FAKE_UV = r"""#!/usr/bin/env python3
import os
import pathlib
import sys

args = sys.argv[1:]
assert args[:2] == ["pip", "compile"], args
requested = pathlib.Path(args[2]).read_text(encoding="utf-8")
overrides = pathlib.Path(args[args.index("--overrides") + 1]).read_text(encoding="utf-8")
pathlib.Path(os.environ["FAKE_UV_LOG"]).write_text(requested + overrides + " ".join(args), encoding="utf-8")
output = pathlib.Path(args[args.index("--output-file") + 1])
lines = [line for line in output.read_text(encoding="utf-8").splitlines() if line]
swapped = [requested.strip() if line.startswith("checkov==") else line for line in lines]
output.write_text("\n".join(swapped) + "\n", encoding="utf-8")
"""


def _layout(tmp_path: Path, version: str | None = None) -> Path:
    """A copy of the generator, its catalogue, both constraints files, and a fake uv."""
    root = tmp_path / "repo"
    action = root / "execution" / "pipelines" / "actions" / "python-gate-body"
    action.mkdir(parents=True)
    for name in (GENERATOR, "scanner-versions.json", "checkov-constraints.txt"):
        shutil.copy2(ACTION_DIR / name, action / name)
    packaged = root / "assurance" / "fitness" / "src" / "tc_fitness"
    packaged.mkdir(parents=True)
    shutil.copy2(PACKAGED, packaged / PACKAGED.name)
    if version is not None:
        catalogue = json.loads((action / "scanner-versions.json").read_text(encoding="utf-8"))
        catalogue["checkov"]["version"] = version
        (action / "scanner-versions.json").write_text(json.dumps(catalogue), encoding="utf-8")
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    uv = fake_bin / "uv"
    uv.write_text(FAKE_UV, encoding="utf-8")
    uv.chmod(uv.stat().st_mode | stat.S_IXUSR)
    return root


def _generate(tmp_path: Path, root: Path, **extra_env: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{tmp_path / 'fake-bin'}{os.pathsep}{os.environ['PATH']}",
        "FAKE_UV_LOG": str(tmp_path / "uv.log"),
        **extra_env,
    }
    script = root / "execution" / "pipelines" / "actions" / "python-gate-body" / GENERATOR
    return subprocess.run(
        ["bash", str(script)], env=env, capture_output=True, text=True, check=False, cwd=tmp_path
    )


def test_a_rerun_at_the_committed_pin_reproduces_both_copies_byte_for_byte(tmp_path: Path) -> None:
    root = _layout(tmp_path)

    result = _generate(tmp_path, root)

    assert result.returncode == 0, result.stderr
    action = root / "execution" / "pipelines" / "actions" / "python-gate-body" / "checkov-constraints.txt"
    packaged = root / "assurance" / "fitness" / "src" / "tc_fitness" / "checkov-constraints.txt"
    assert action.read_bytes() == (ACTION_DIR / "checkov-constraints.txt").read_bytes()
    assert packaged.read_bytes() == PACKAGED.read_bytes()


def test_a_checkov_bump_in_the_catalogue_rewrites_both_copies_and_keeps_the_header(tmp_path: Path) -> None:
    root = _layout(tmp_path, version="9.9.9")

    result = _generate(tmp_path, root)

    assert result.returncode == 0, result.stderr
    assert "checkov==9.9.9" in (tmp_path / "uv.log").read_text(encoding="utf-8")
    assert "asteval>=1.0.9,<1.1" in (tmp_path / "uv.log").read_text(encoding="utf-8")
    for copy in (
        root / "execution" / "pipelines" / "actions" / "python-gate-body" / "checkov-constraints.txt",
        root / "assurance" / "fitness" / "src" / "tc_fitness" / "checkov-constraints.txt",
    ):
        text = copy.read_text(encoding="utf-8")
        assert "checkov==9.9.9\n" in text
        assert "checkov==3.2.531" not in text
        assert text.startswith("# The complete Checkov tool environment")
        assert f"bash execution/pipelines/actions/python-gate-body/{GENERATOR}" in text


def test_the_documented_regeneration_recipe_names_the_committed_generator() -> None:
    lines = (ACTION_DIR / "checkov-constraints.txt").read_text(encoding="utf-8").splitlines()
    header = "\n".join(line for line in lines if line.startswith("#"))
    assert f"bash execution/pipelines/actions/python-gate-body/{GENERATOR}" in header
    assert (ACTION_DIR / GENERATOR).stat().st_mode & stat.S_IXUSR
    assert "--output-file" in (ACTION_DIR / GENERATOR).read_text(encoding="utf-8")


def test_upgrade_refreshes_the_transitive_pins(tmp_path: Path) -> None:
    root = _layout(tmp_path)

    assert _generate(tmp_path, root, UPGRADE="1").returncode == 0

    assert "--upgrade" in (tmp_path / "uv.log").read_text(encoding="utf-8")
