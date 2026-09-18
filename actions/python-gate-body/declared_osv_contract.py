#!/usr/bin/env python3
"""Emit the consumer-declared OSV install contract for the composite action."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

EXACT_VERSION = re.compile(r"\d+\.\d+\.\d+")


def _config(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "pyproject.toml"
    if not path.is_file():
        return {}
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    tool = document.get("tool") or {}
    fitness = tool.get("tc_fitness") or {}
    checks = fitness.get("core_checks") or {}
    contract = checks.get("osv_scanner_sca") or {}
    return contract if isinstance(contract, dict) else {}


def emit(repo_root: Path) -> int:
    contract = _config(repo_root)
    if not contract:
        print("required=false")
        print("version=")
        return 0
    required_value = contract.get("required")
    if not isinstance(required_value, bool):
        print("OSV SCA contract required must be a boolean", file=sys.stderr)
        return 1
    required = required_value
    if not required:
        print("required=false")
        print("version=")
        return 0
    version = str(contract.get("scanner_version", "")).strip()
    if EXACT_VERSION.fullmatch(version) is None:
        print(
            "required OSV SCA contract must declare an exact scanner_version (x.y.z)",
            file=sys.stderr,
        )
        return 1
    lockfiles = contract.get("lockfiles")
    if (
        not isinstance(lockfiles, list)
        or not lockfiles
        or any(not isinstance(path, str) or not path.strip() for path in lockfiles)
    ):
        print(
            "required OSV SCA contract must declare a non-empty lockfiles list",
            file=sys.stderr,
        )
        return 1
    print("required=true")
    print(f"version={version}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    return emit(args.repo_root.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
