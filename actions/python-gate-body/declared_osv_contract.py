#!/usr/bin/env python3
"""Emit the consumer-declared OSV install contract for the composite action."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

EXACT_VERSION = re.compile(r"\d+\.\d+\.\d+")


def _config_path(repo_root: Path) -> tuple[Path, tuple[str, ...]] | None:
    """Mirror tc_fitness.gate_config: dedicated config wins over pyproject."""
    dedicated = repo_root / ".tc-fitness.toml"
    if dedicated.is_file():
        return dedicated, ("core_checks", "osv_scanner_sca")
    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        return pyproject, ("tool", "tc_fitness", "core_checks", "osv_scanner_sca")
    return None


def _without_comment(line: str) -> str:
    quote = ""
    escaped = False
    for index, character in enumerate(line):
        if quote:
            if character == "\\" and quote == '"' and not escaped:
                escaped = True
                continue
            if character == quote and not escaped:
                quote = ""
            escaped = False
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "#":
            return line[:index]
    return line


def _value(raw: str) -> Any:
    value = raw.strip()
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith('"'):
        return json.loads(value)
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    if value.startswith("["):
        return [_value(item) for item in value[1:-1].split(",") if item.strip()]
    return value


def _config(repo_root: Path) -> dict[str, Any]:
    selected = _config_path(repo_root)
    if selected is None:
        return {}
    path, wanted = selected
    current: tuple[str, ...] = ()
    contract: dict[str, Any] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = _without_comment(raw_line).strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = tuple(part.strip() for part in line[1:-1].split("."))
            continue
        if current != wanted or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        contract[key.strip()] = _value(raw_value)
    return contract


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
