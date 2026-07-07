#!/usr/bin/env python3
"""Fail closed on fatal Azure VM run-command message output."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple


FATAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|\n)FAIL(?:\s|:)", re.IGNORECASE),
    re.compile(r"(^|\n)✗\s+"),
    re.compile(r"(^|\n)ERROR:", re.IGNORECASE),
    re.compile(r"\bPermission denied\b", re.IGNORECASE),
    re.compile(r"(^|\n)fatal:\s+", re.IGNORECASE),
    re.compile(r"\bcommand not found\b", re.IGNORECASE),
    re.compile(r"Traceback \(most recent call last\):"),
    re.compile(r"\bIllegal option -o pipefail\b"),
)


class GateResult(NamedTuple):
    failed: bool
    matches: list[str]


def classify_run_command_message(message: str) -> GateResult:
    matches: list[str] = []
    for pattern in FATAL_PATTERNS:
        match = pattern.search(message)
        if match:
            matches.append(match.group(0).strip())
    return GateResult(failed=bool(matches), matches=matches)


def _read_message(path: str | None) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    return sys.stdin.read()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("message_file", nargs="?", help="File containing az vm run-command value[0].message output")
    parser.add_argument("--label", default="run-command", help="Human-readable label for error output")
    args = parser.parse_args(argv)

    result = classify_run_command_message(_read_message(args.message_file))
    if not result.failed:
        return 0

    print(f"{args.label}: fatal marker(s) found in Azure run-command output:", file=sys.stderr)
    for match in result.matches:
        print(f"  - {match}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
