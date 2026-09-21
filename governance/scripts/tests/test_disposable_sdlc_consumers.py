"""Public, packed-package disposable consumer assurance for Task 6/F7."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]
CONSUMERS = yaml.safe_load((ROOT / "assurance/fixtures/sdlc/consumers.yaml").read_text())["consumers"]
PACKAGE_VERSION = json.loads((ROOT / "packages/tc-sdlc/package.json").read_text())["version"]


def command(argv: list[str], cwd: Path, *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=False, timeout=timeout)


@pytest.fixture(scope="session")
def packed_cli(tmp_path_factory: pytest.TempPathFactory) -> Path:
    package = ROOT / "packages/tc-sdlc"
    built = command(["pnpm", "build"], package)
    assert built.returncode == 0, built.stdout + built.stderr
    destination = tmp_path_factory.mktemp("tc-sdlc-pack")
    packed = command(["pnpm", "pack", "--pack-destination", str(destination)], package)
    assert packed.returncode == 0, packed.stdout + packed.stderr
    archives = list(destination.glob("three-cubes-tc-sdlc-*.tgz"))
    assert len(archives) == 1
    return archives[0]


def installed_cli(tarball: Path, root: Path) -> Path:
    runner = root / "runner"
    runner.mkdir()
    (runner / "package.json").write_text('{"private":true,"packageManager":"pnpm@11.22.0"}\n')
    installed = command(["pnpm", "add", f"file:{tarball}"], runner)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    runner_lock = (runner / "pnpm-lock.yaml").read_text()
    assert "@three-cubes/tc-sdlc" in runner_lock
    assert tarball.name in runner_lock
    cli = runner / "node_modules/.bin/tc-sdlc"
    assert cli.is_file()
    return cli


def invoke(cli: Path, consumer: Path, *arguments: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return command([str(cli), *arguments], consumer, timeout=timeout)


def exercise(tmp_path: Path, packed_cli: Path, spec: dict[str, object], *, shadow: bool = False) -> tuple[Path, dict[str, object]]:
    consumer = tmp_path / "consumer"
    source = ROOT / "assurance/fixtures/sdlc" / str(spec["fixture"])
    assert not (source / ".venv").exists() and not (source / "node_modules").exists(), "fixtures must not carry dependency state"
    shutil.copytree(source, consumer)
    initialized = command(["git", "init", "-q", "-b", "main"], consumer)
    assert initialized.returncode == 0, initialized.stderr
    assert command(["git", "config", "user.name", "disposable-consumer"], consumer).returncode == 0
    assert command(["git", "config", "user.email", "disposable@example.invalid"], consumer).returncode == 0
    assert command(["git", "add", "."], consumer).returncode == 0
    assert command(["git", "commit", "-qm", "fixture"], consumer).returncode == 0
    cli = installed_cli(packed_cli, tmp_path)
    declaration = consumer / "sdlc.yaml"
    catalogue = consumer / "release-catalogue.json"
    lock = consumer / "tc-sdlc.lock"
    state = tmp_path / "state"
    bootstrap = tmp_path / "bootstrap.json"
    prepare = tmp_path / "prepare.json"
    complete = tmp_path / "complete.json"
    affected = tmp_path / "affected.json"
    catalogued = invoke(cli, consumer, "catalogue", "--version", PACKAGE_VERSION, "--workflow-commit", "0" * 40, "--image-digest", "sha256:" + "0" * 64, "--output", str(catalogue))
    assert catalogued.returncode == 0, catalogued.stdout + catalogued.stderr
    locked = invoke(cli, consumer, "lock", "--declaration", str(declaration), "--catalogue", str(catalogue), "--output", str(lock))
    assert locked.returncode == 0, locked.stdout + locked.stderr
    bootstrapped = invoke(cli, consumer, "bootstrap", "--declaration", str(declaration), "--catalogue", str(catalogue), "--lock", str(lock), "--root", str(consumer), "--state-root", str(state), "--receipt", str(bootstrap), timeout=900)
    assert bootstrapped.returncode == 0, bootstrapped.stdout + bootstrapped.stderr
    if shadow:
        package = consumer / "node_modules/kleur"
        package.mkdir(parents=True)
        (package / "package.json").write_text('{"name":"kleur","version":"0.0.0","type":"module","exports":"./index.js"}\n')
        (package / "index.js").write_text('export default { bold(value) { return `shadow:${value}`; } };\n')
    prepared = invoke(cli, consumer, "prepare", "--declaration", str(declaration), "--catalogue", str(catalogue), "--lock", str(lock), "--root", str(consumer), "--state-root", str(state), "--bootstrap-receipt", str(bootstrap), "--receipt", str(prepare))
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    checked = invoke(cli, consumer, "check-all", "--declaration", str(declaration), "--catalogue", str(catalogue), "--lock", str(lock), "--root", str(consumer), "--state-root", str(state), "--bootstrap-receipt", str(bootstrap), "--preparation-receipt", str(prepare), "--environment", "native", "--producer", "f7-disposable-consumer", "--receipt", str(complete))
    assert checked.returncode == 0, checked.stdout + checked.stderr
    changed_result = invoke(cli, consumer, "check", "--declaration", str(declaration), "--catalogue", str(catalogue), "--lock", str(lock), "--root", str(consumer), "--state-root", str(state), "--bootstrap-receipt", str(bootstrap), "--preparation-receipt", str(prepare), "--environment", "native", "--producer", "f7-disposable-consumer", "--changed", str(spec["changed"]), "--receipt", str(affected))
    assert changed_result.returncode == 0, changed_result.stdout + changed_result.stderr
    if not shadow:
        assert not (consumer / ".venv").exists() and not (consumer / "node_modules").exists(), "consumer dependency state must not be retained"
    return consumer, {"complete": json.loads(complete.read_text()), "affected": json.loads(affected.read_text())}


@pytest.mark.parametrize("spec", CONSUMERS, ids=lambda spec: str(spec["id"]))
def test_packed_cli_executes_locked_disposable_consumers(tmp_path: Path, packed_cli: Path, spec: dict[str, object]) -> None:
    consumer, receipts = exercise(tmp_path, packed_cli, spec)
    assert (consumer / "tc-sdlc.lock").is_file()
    complete_expected = set(spec["complete_tasks"])
    assert {task["key"] for task in receipts["complete"]["tasks"]} == complete_expected
    assert {task["key"] for task in receipts["affected"]["tasks"]} == set(spec["affected_tasks"])


def test_packed_cli_prefers_locked_state_over_local_node_shadowing(tmp_path: Path, packed_cli: Path) -> None:
    spec = next(spec for spec in CONSUMERS if spec["id"] == "pnpm")
    exercise(tmp_path, packed_cli, spec, shadow=True)
