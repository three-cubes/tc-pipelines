"""Run trusted Ruff preparation with each tracked file's effective config."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

DEFAULT_TARGET_VERSION = "py312"
DEFAULT_LINE_LENGTH = "110"
RUFF_VERSION = "0.16.8"
RUFF_TABLE = re.compile(
    r"^[\t ]*\[[\t ]*tool[\t ]*\.[\t ]*ruff(?:[\t ]*\.[^\]]*)?\]",
    re.MULTILINE,
)
PROJECT_TABLE = re.compile(
    r"^[\t ]*\[project\][\t ]*(?:\#[^\n]*)?$(.*?)(?=^[\t ]*\[|\Z)",
    re.MULTILINE | re.DOTALL,
)
REQUIRES_PYTHON = re.compile(r"^[\t ]*requires-python[\t ]*=", re.MULTILINE)


class RuffPreparationError(RuntimeError):
    """Ruff could not prepare one of the tracked file groups."""


def _config_in(directory: Path) -> Path | None:
    for name in (".ruff.toml", "ruff.toml"):
        candidate = directory / name
        if candidate.is_file():
            return candidate
    candidate = directory / "pyproject.toml"
    if candidate.is_file():
        content = candidate.read_text(encoding="utf-8")
        project = PROJECT_TABLE.search(content)
        if RUFF_TABLE.search(content) or (
            project is not None and REQUIRES_PYTHON.search(project.group(1)) is not None
        ):
            return candidate
    return None


def _config_for_path(root: Path, relative_path: str) -> Path | None:
    directory = (root / relative_path).parent
    while directory != root.parent:
        config = _config_in(directory)
        if config is not None:
            return config.relative_to(root)
        if directory == root:
            break
        directory = directory.parent
    return None


def ruff_groups(root: Path, paths: list[str]) -> list[tuple[Path | None, list[str]]]:
    """Partition tracked paths by their nearest Ruff config, preserving order."""
    groups: dict[Path | None, list[str]] = {}
    for relative_path in sorted(paths):
        groups.setdefault(_config_for_path(root, relative_path), []).append(relative_path)
    return sorted(groups.items(), key=lambda group: "" if group[0] is None else group[0].as_posix())


def _arguments(config_path: Path | None, task: str) -> list[str]:
    arguments = [task]
    if config_path is None:
        arguments.extend(["--isolated", "--target-version", DEFAULT_TARGET_VERSION])
        if task == "format":
            arguments.extend(["--line-length", DEFAULT_LINE_LENGTH])
    if task == "check":
        arguments.extend(
            [
                "--force-exclude",
                "--select",
                "E,F,I,UP,B,S,RUF",
                "--ignore",
                "E501,RUF022",
                "--fix",
                "--no-unsafe-fixes",
                "--exit-zero",
            ]
        )
    else:
        arguments.append("--force-exclude")
    return arguments


def run_ruff_preparation(
    root: Path,
    paths: list[str],
    ruff_version: str = RUFF_VERSION,
    environment: dict[str, str] | None = None,
) -> None:
    """Apply the pinned lint fixes and formatter without executing project code."""
    for config_path, grouped_paths in ruff_groups(root, paths):
        for task in ("check", "format"):
            result = subprocess.run(
                [
                    "uvx",
                    "--from",
                    f"ruff=={ruff_version}",
                    "ruff",
                    *_arguments(config_path, task),
                    "--",
                    *grouped_paths,
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
                env=environment,
            )
            if result.stdout:
                sys.stdout.write(result.stdout)
            if result.stderr:
                sys.stderr.write(result.stderr)
            if result.returncode:
                detail = (result.stderr or result.stdout).strip()
                raise RuffPreparationError(f"ruff {task} failed: {detail}")


if __name__ == "__main__":
    if len(sys.argv) < 4 or sys.argv[1] != "prepare":
        raise SystemExit("usage: ruff_policy.py prepare ROOT RUFF_VERSION [TRACKED_PYTHON_PATH ...]")
    try:
        run_ruff_preparation(Path(sys.argv[2]), sys.argv[4:], ruff_version=sys.argv[3])
    except RuffPreparationError as error:
        print(f"ruff preparation: {error}", file=sys.stderr)
        raise SystemExit(1) from error
