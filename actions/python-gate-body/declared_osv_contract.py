"""Validate the consumer's SCA opt-in and emit tc-pipelines' pinned OSV version."""

from __future__ import annotations

import argparse
import json
import re
import sys

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10; provisioned by the composite action.
    import tomli as tomllib
from pathlib import Path
from typing import Any

EXACT_VERSION = re.compile(r"\d+\.\d+\.\d+")
SCANNER_CATALOGUE = Path(__file__).with_name("scanner-versions.json")


def _config_path(repo_root: Path) -> tuple[Path, tuple[str, ...]] | None:
    """Mirror tc_fitness.gate_config: dedicated config wins over pyproject."""
    dedicated = repo_root / ".tc-fitness.toml"
    if dedicated.is_file():
        return dedicated, ("core_checks", "osv_scanner_sca")
    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        return pyproject, ("tool", "tc_fitness", "core_checks", "osv_scanner_sca")
    return None


def _config(repo_root: Path) -> dict[str, Any]:
    selected = _config_path(repo_root)
    if selected is None:
        return {}
    path, wanted = selected
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    current: Any = document
    for key in wanted:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


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
    declared_version = str(contract.get("scanner_version", "")).strip()
    if EXACT_VERSION.fullmatch(declared_version) is None:
        print(
            "required OSV SCA contract must declare an exact scanner_version (x.y.z)",
            file=sys.stderr,
        )
        return 1
    # Existing fitness declarations carry a scanner_version field. The
    # executable pin belongs to tc-pipelines so consumers cannot drift to a
    # stale binary independently of this provisioner.
    try:
        catalogue = json.loads(SCANNER_CATALOGUE.read_text(encoding="utf-8"))
        version = catalogue["osv-scanner"]["version"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"cannot read canonical OSV Scanner version: {error}", file=sys.stderr)
        return 1
    if EXACT_VERSION.fullmatch(version) is None:
        print("catalogued OSV Scanner version must be exact x.y.z", file=sys.stderr)
        return 1
    if declared_version != version:
        print(
            "consumer declares OSV Scanner "
            f"{declared_version}, but tc-pipelines provisions {version}; "
            "update scanner_version in the consumer SCA contract to match",
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
