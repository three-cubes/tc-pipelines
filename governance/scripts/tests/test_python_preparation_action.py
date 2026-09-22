"""Execute the reusable Python preparation action's portable shell body."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.contract


def test_preparation_action_reads_non_newline_version_and_only_tracked_python(
    tmp_path: Path,
) -> None:
    document = yaml.safe_load(
        (ROOT / "actions/python-preparation/action.yml").read_text()
    )
    script = document["runs"]["steps"][0]["run"]
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / ".uv-version").write_text("0.12.5", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (repo / "tracked.py").write_text("value = 1\n", encoding="utf-8")
    (repo / "ignored.py").write_text("value = 2\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", ".uv-version", "pyproject.toml", "tracked.py"],
        cwd=repo,
        check=True,
    )
    log = tmp_path / "uvx.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "uvx").write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$UVX_LOG"\n',
        encoding="utf-8",
    )
    (fake_bin / "uvx").chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "UVX_LOG": str(log),
        "UV_VERSION": "",
        "RUFF_VERSION": "0.16.8",
        "TARGET_VERSION": "py312",
        "LINE_LENGTH": "110",
    }
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script], cwd=repo, env=environment
    )
    assert result.returncode == 0
    calls = log.read_text(encoding="utf-8").splitlines()
    assert any("uv==0.12.5" in call and " uv lock" in call for call in calls)
    assert any("tracked.py" in call and "ignored.py" not in call for call in calls)
