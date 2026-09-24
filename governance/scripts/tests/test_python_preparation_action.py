"""Execute the reusable Python preparation action's portable shell body."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.contract


def test_consumer_preparation_command_is_the_only_preparation_authority(
    tmp_path: Path,
) -> None:
    document = yaml.safe_load(
        (ROOT / "actions/python-preparation/action.yml").read_text()
    )
    script = document["runs"]["steps"][0]["run"]
    repo = tmp_path / "consumer"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "consumer"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (repo / "prepare.sh").write_text(
        '#!/bin/sh\nprintf "prepared\\n" >> preparation.log\n',
        encoding="utf-8",
    )
    (repo / "prepare.sh").chmod(0o755)
    (repo / "tracked.py").write_text("value=1\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "pyproject.toml", "prepare.sh", "tracked.py"],
        cwd=repo,
        check=True,
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "uvx").write_text(
        '#!/bin/sh\necho "shared preparation ran" >&2\nexit 97\n', encoding="utf-8"
    )
    (fake_bin / "uvx").chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GITHUB_ACTION_PATH": str(ROOT / "actions/python-preparation"),
        "PREPARATION_COMMAND": "./prepare.sh",
        "RUFF_VERSION": "0.16.8",
        "UV_VERSION": "0.12.5",
    }

    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=repo,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (repo / "preparation.log").read_text(encoding="utf-8") == "prepared\n"


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
        "GITHUB_ACTION_PATH": str(ROOT / "actions/python-preparation"),
        "UV_VERSION": "",
        "RUFF_VERSION": "0.16.8",
    }
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=repo,
        env=environment,
        check=False,
    )
    assert result.returncode == 0
    calls = log.read_text(encoding="utf-8").splitlines()
    assert any("uv==0.12.5" in call and " uv lock" in call for call in calls)
    assert any("tracked.py" in call and "ignored.py" not in call for call in calls)
    assert any("--target-version py312" in call for call in calls)
    assert any("--line-length 110" in call for call in calls)


def test_consumer_ruff_config_is_a_fixed_point_without_executing_project_code(
    tmp_path: Path,
) -> None:
    document = yaml.safe_load(
        (ROOT / "actions/python-preparation/action.yml").read_text()
    )
    script = document["runs"]["steps"][0]["run"]
    repo = tmp_path / "consumer"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "ruff-consumer"\nversion = "0.1.0"\nrequires-python = ">=3.10"\n\n'
        '[tool.ruff]\ntarget-version = "py310"\nline-length = 120\n',
        encoding="utf-8",
    )
    (repo / "alias.py").write_text("Alias = int | str\n", encoding="utf-8")
    (repo / "formatting.py").write_text(
        "result = compute(\n"
        "    first_argument, second_argument, third_argument,\n"
        "    fourth_argument, fifth_argument, sixth_argument\n"
        ")\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "pyproject.toml", "alias.py", "formatting.py"],
        cwd=repo,
        check=True,
    )
    environment = {
        **os.environ,
        "GITHUB_ACTION_PATH": str(ROOT / "actions/python-preparation"),
        "UV_VERSION": "",
        "RUFF_VERSION": "0.16.8",
    }

    first = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=repo,
        env=environment,
        check=False,
    )
    assert first.returncode == 0
    prepared = {path.name: path.read_bytes() for path in repo.glob("*.py")}
    assert prepared["alias.py"] == b"Alias = int | str\n"
    assert b"result = compute(first_argument," in prepared["formatting.py"]
    settings = subprocess.run(
        [
            "uvx",
            "--from",
            "ruff==0.16.8",
            "ruff",
            "check",
            "--show-settings",
            "alias.py",
        ],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert settings.returncode == 0, settings.stderr
    assert "linter.unresolved_target_version = 3.10" in settings.stdout
    assert "formatter.line_width = 120" in settings.stdout

    second = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=repo,
        env=environment,
        check=False,
    )
    assert second.returncode == 0
    assert {path.name: path.read_bytes() for path in repo.glob("*.py")} == prepared


def test_nested_ruff_config_does_not_change_unconfigured_sibling_defaults(
    tmp_path: Path,
) -> None:
    document = yaml.safe_load(
        (ROOT / "actions/python-preparation/action.yml").read_text()
    )
    script = document["runs"]["steps"][0]["run"]
    repo = tmp_path / "mixed-consumer"
    nested = repo / "package"
    nested.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "ruff-base.toml").write_text(
        'target-version = "py310"\nline-length = 100\n', encoding="utf-8"
    )
    (nested / "pyproject.toml").write_text(
        '[tool.ruff]\ntarget-version = "py313"\nline-length = 88\n', encoding="utf-8"
    )
    (nested / "ruff.toml").write_text(
        'target-version = "py311"\nline-length = 100\n', encoding="utf-8"
    )
    (nested / ".ruff.toml").write_text(
        'extend = "../ruff-base.toml"\nline-length = 120\n', encoding="utf-8"
    )
    (repo / "-root_format.py").write_text(
        "result = compute(\n"
        "    first_argument, second_argument, third_argument,\n"
        "    fourth_argument, fifth_argument\n"
        ")\n",
        encoding="utf-8",
    )
    (nested / "nested_format.py").write_text(
        "result = compute(\n"
        "    first_argument, second_argument, third_argument,\n"
        "    fourth_argument, fifth_argument, sixth_argument\n"
        ")\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            "git",
            "add",
            "--",
            "ruff-base.toml",
            "package/pyproject.toml",
            "package/ruff.toml",
            "package/.ruff.toml",
            "-root_format.py",
            "package/nested_format.py",
        ],
        cwd=repo,
        check=True,
    )
    environment = {
        **os.environ,
        "GITHUB_ACTION_PATH": str(ROOT / "actions/python-preparation"),
        "RUFF_VERSION": "0.16.8",
        "UV_VERSION": "",
    }

    first = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=repo,
        env=environment,
        check=False,
    )
    assert first.returncode == 0
    prepared = {
        "root": (repo / "-root_format.py").read_bytes(),
        "nested": (nested / "nested_format.py").read_bytes(),
    }
    assert b"result = compute(first_argument," in prepared["root"]
    assert b"result = compute(first_argument," in prepared["nested"]

    second = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=repo,
        env=environment,
        check=False,
    )
    assert second.returncode == 0
    assert (repo / "-root_format.py").read_bytes() == prepared["root"]
    assert (nested / "nested_format.py").read_bytes() == prepared["nested"]


def test_requires_python_infers_ruff_target_without_forcing_shared_defaults(
    tmp_path: Path,
) -> None:
    document = yaml.safe_load(
        (ROOT / "actions/python-preparation/action.yml").read_text()
    )
    script = document["runs"]["steps"][0]["run"]
    repo = tmp_path / "python-inference"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "python-inference"\nversion = "0.1.0"\nrequires-python = ">=3.13,<3.14"\n',
        encoding="utf-8",
    )
    (repo / "module.py").write_text(
        "result = compute(\n"
        "    first_argument, second_argument, third_argument,\n"
        "    fourth_argument, fifth_argument\n"
        ")\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "pyproject.toml", "module.py"], cwd=repo, check=True)
    real_uvx = shutil.which("uvx")
    assert real_uvx is not None
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "uvx").write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$UVX_LOG"\nexec "$REAL_UVX" "$@"\n',
        encoding="utf-8",
    )
    (fake_bin / "uvx").chmod(0o755)
    log = tmp_path / "uvx.log"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "UVX_LOG": str(log),
        "REAL_UVX": real_uvx,
        "GITHUB_ACTION_PATH": str(ROOT / "actions/python-preparation"),
        "RUFF_VERSION": "0.16.8",
        "UV_VERSION": "",
    }

    prepared = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=repo,
        env=environment,
        check=False,
    )
    assert prepared.returncode == 0
    ruff_calls = [
        call
        for call in log.read_text(encoding="utf-8").splitlines()
        if "ruff==" in call
    ]
    assert len(ruff_calls) == 2
    assert all(
        "--isolated" not in call and "--target-version" not in call
        for call in ruff_calls
    )
    assert "--line-length 110" not in ruff_calls[0]
    assert "--line-length 110" in ruff_calls[1]
    prepared_source = (repo / "module.py").read_text(encoding="utf-8")
    assert "result = compute(first_argument," in prepared_source

    settings = subprocess.run(
        [
            "uvx",
            "--from",
            "ruff==0.16.8",
            "ruff",
            "check",
            "--show-settings",
            "module.py",
        ],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert settings.returncode == 0, settings.stderr
    assert "linter.unresolved_target_version = 3.13" in settings.stdout

    second = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=repo,
        env=environment,
        check=False,
    )
    assert second.returncode == 0
    assert (repo / "module.py").read_text(encoding="utf-8") == prepared_source


def test_nested_requires_python_keeps_ancestor_ruff_formatting_policy(
    tmp_path: Path,
) -> None:
    document = yaml.safe_load(
        (ROOT / "actions/python-preparation/action.yml").read_text()
    )
    script = document["runs"]["steps"][0]["run"]
    repo = tmp_path / "nested-python-metadata"
    nested = repo / "package"
    nested.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "root-policy"\nversion = "0.1.0"\n\n'
        '[tool.ruff]\ntarget-version = "py313"\nline-length = 120\n',
        encoding="utf-8",
    )
    (nested / "pyproject.toml").write_text(
        '[project]\nname = "nested-metadata"\nversion = "0.1.0"\nrequires-python = ">=3.13,<3.14"\n',
        encoding="utf-8",
    )
    (nested / "module.py").write_text(
        "result = compute(\n"
        "    first_argument, second_argument, third_argument,\n"
        "    fourth_argument, fifth_argument, sixth_argument\n"
        ")\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "pyproject.toml", "package/pyproject.toml", "package/module.py"],
        cwd=repo,
        check=True,
    )
    environment = {
        **os.environ,
        "GITHUB_ACTION_PATH": str(ROOT / "actions/python-preparation"),
        "RUFF_VERSION": "0.16.8",
        "UV_VERSION": "",
    }

    prepared = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=repo,
        env=environment,
        check=False,
    )

    assert prepared.returncode == 0
    prepared_source = (nested / "module.py").read_text(encoding="utf-8")
    expected_call = (
        "result = compute(first_argument, second_argument, third_argument, "
        "fourth_argument, fifth_argument, sixth_argument)"
    )
    assert expected_call in prepared_source
    settings = subprocess.run(
        [
            "uvx",
            "--from",
            "ruff==0.16.8",
            "ruff",
            "check",
            "--show-settings",
            "package/module.py",
        ],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert settings.returncode == 0, settings.stderr
    assert "formatter.line_width = 120" in settings.stdout
    assert "linter.unresolved_target_version = 3.13" in settings.stdout
