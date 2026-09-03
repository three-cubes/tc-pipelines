#!/usr/bin/env python3
"""Advance every tc-pipelines self-pin to one immutable released commit."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


SHA = re.compile(r"[0-9a-f]{40}")
VERSION = re.compile(r"v[0-9]+(?:\.[0-9]+){2}(?:[-.][0-9A-Za-z]+)*")
SELF_PIN = re.compile(
    r"(?P<prefix>uses:\s*three-cubes/tc-pipelines/[^@\s]+@)(?P<sha>[0-9a-f]{40})"
    r"(?P<comment>\s*#\s*)(?P<version>v[^\s#]+)"
)
TARGETS = (Path(".github/workflows"), Path(".github/actions"), Path("actions"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--sha", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def source_files(root: Path) -> list[Path]:
    return sorted(
        path
        for target in TARGETS
        if (root / target).is_dir()
        for path in (root / target).rglob("*.yml")
    )


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    if not SHA.fullmatch(args.sha) or not VERSION.fullmatch(args.version):
        print("--sha and --version must name an immutable release", file=sys.stderr)
        return 2

    changed = 0
    stale: list[str] = []
    found = 0
    for path in source_files(root):
        text = path.read_text(encoding="utf-8")
        matches = list(SELF_PIN.finditer(text))
        found += len(matches)
        stale.extend(
            f"{path}:{match.start('sha') + 1}={match.group('sha')}"
            for match in matches
            if match.group("sha") != args.sha
        )
        updated = SELF_PIN.sub(
            lambda match: (
                f"{match.group('prefix')}{args.sha}{match.group('comment')}{args.version}"
            ),
            text,
        )
        if not args.check and updated != text:
            path.write_text(updated, encoding="utf-8")
            changed += 1

    if found == 0:
        print("no tc-pipelines self-pins found", file=sys.stderr)
        return 1
    if args.check and stale:
        print("stale tc-pipelines self-pin(s):\n" + "\n".join(stale), file=sys.stderr)
        return 1
    if not args.check:
        print(f"updated {changed} file(s) to {args.version} ({args.sha})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
