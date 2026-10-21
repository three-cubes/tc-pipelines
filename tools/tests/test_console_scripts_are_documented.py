"""Every console script the package declares has its own section in the exported README."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

PACKAGE = Path(__file__).resolve().parents[1]


def test_each_project_script_has_a_readme_section() -> None:
    scripts = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    headings = set(
        re.findall(r"^## `([^`]+)`", (PACKAGE / "README.md").read_text(encoding="utf-8"), re.MULTILINE)
    )
    missing = sorted(set(scripts) - headings)
    assert not missing, f"fix: add a `## \\`{missing[0]}\\`` section to execution/pipelines/tools/README.md"
