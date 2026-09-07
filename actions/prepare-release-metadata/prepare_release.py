"""Prepare one reviewed release ledger from its immutable tag coordinate."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

SCHEMA = "three-cubes/release-preparation/v1"
UNRELEASED = re.compile(r"^## \[Unreleased\][^\n]*(?:\n|$)", re.MULTILINE)
SECOND_LEVEL = re.compile(r"^## ", re.MULTILINE)
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _label(version: str) -> str:
    label = version.removeprefix("v")
    if not label or any(character in label for character in "\r\n[]"):
        raise ValueError("version must be a non-empty single-line tag")
    return label


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def prepare(
    *,
    version: str,
    release_date: str,
    changelog: Path,
    version_file: Path | None,
    preparation_file: Path,
) -> None:
    label = _label(version)
    if not DATE.fullmatch(release_date):
        raise ValueError("date must be ISO-8601 YYYY-MM-DD")
    if not changelog.is_file():
        raise ValueError(f"changelog does not exist: {changelog}")

    document = changelog.read_text(encoding="utf-8")
    target = re.compile(rf"^## \[{re.escape(label)}\](?:\s|$)", re.MULTILINE)
    if target.search(document):
        raise ValueError(f"changelog already has a [{label}] section")
    unreleased = UNRELEASED.search(document)
    if unreleased is None:
        raise ValueError("changelog has no ## [Unreleased] section")
    following = SECOND_LEVEL.search(document, unreleased.end())
    end = following.start() if following else len(document)
    body = document[unreleased.end() : end]
    if not body.strip():
        raise ValueError("changelog Unreleased section has no release notes")

    promoted = (
        document[: unreleased.end()].rstrip("\n")
        + f"\n\n## [{label}] — {release_date}\n"
        + body
        + document[end:]
    )
    _write(changelog, promoted)
    if version_file is not None:
        _write(version_file, f"{label}\n")

    receipt: dict[str, str] = {
        "schema": SCHEMA,
        "version": version,
        "changelog": str(changelog),
        "changelog_sha256": _sha256(changelog),
        "version_file": "",
        "version_file_sha256": "",
    }
    if version_file is not None:
        receipt["version_file"] = str(version_file)
        receipt["version_file_sha256"] = _sha256(version_file)
    _write(preparation_file, json.dumps(receipt, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--date", default=dt.datetime.now(tz=dt.UTC).date().isoformat())
    parser.add_argument("--changelog", default="CHANGELOG.md")
    parser.add_argument("--version-file", default="VERSION")
    parser.add_argument("--preparation-file", default=".release-prepared.json")
    arguments = parser.parse_args()
    try:
        prepare(
            version=arguments.version,
            release_date=arguments.date,
            changelog=Path(arguments.changelog),
            version_file=Path(arguments.version_file)
            if arguments.version_file
            else None,
            preparation_file=Path(arguments.preparation_file),
        )
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"prepared release {arguments.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
