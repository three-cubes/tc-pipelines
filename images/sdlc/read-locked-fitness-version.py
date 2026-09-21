#!/usr/bin/env python3
"""Print the sole locked three-cubes-fitness version from a uv lockfile."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path


def main() -> None:
    packages = tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get("package", [])
    versions = [
        package.get("version") for package in packages if package.get("name") == "three-cubes-fitness"
    ]
    if len(versions) != 1 or not isinstance(versions[0], str):
        raise SystemExit("uv.lock must contain exactly one three-cubes-fitness package version")
    print(versions[0])


if __name__ == "__main__":
    main()
