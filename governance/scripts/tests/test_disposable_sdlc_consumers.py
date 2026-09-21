"""Public, packed-package disposable consumer assurance for Task 6/F7."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]


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
    cli = runner / "node_modules/.bin/tc-sdlc"
    assert cli.is_file()
    return cli


def invoke(cli: Path, consumer: Path, *arguments: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return command([str(cli), *arguments], consumer, timeout=timeout)


def exercise(tmp_path: Path, packed_cli: Path, fixture: str, changed: str) -> tuple[Path, dict[str, object]]:
    consumer = tmp_path / "consumer"
    source = ROOT / "assurance/fixtures/sdlc" / fixture
    assert not (source / ".venv").exists(), "fixtures must not carry a consumer virtual environment"
    shutil.copytree(source, consumer)
    shutil.copy2(ROOT / "release/catalogue.json", consumer / "release-catalogue.json")
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
    locked = invoke(cli, consumer, "lock", "--declaration", str(declaration), "--catalogue", str(catalogue), "--output", str(lock))
    assert locked.returncode == 0, locked.stdout + locked.stderr
    bootstrapped = invoke(cli, consumer, "bootstrap", "--declaration", str(declaration), "--catalogue", str(catalogue), "--lock", str(lock), "--root", str(consumer), "--state-root", str(state), "--receipt", str(bootstrap), timeout=900)
    assert bootstrapped.returncode == 0, bootstrapped.stdout + bootstrapped.stderr
    prepared = invoke(cli, consumer, "prepare", "--declaration", str(declaration), "--catalogue", str(catalogue), "--lock", str(lock), "--root", str(consumer), "--state-root", str(state), "--bootstrap-receipt", str(bootstrap), "--receipt", str(prepare))
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    checked = invoke(cli, consumer, "check-all", "--declaration", str(declaration), "--catalogue", str(catalogue), "--lock", str(lock), "--root", str(consumer), "--state-root", str(state), "--bootstrap-receipt", str(bootstrap), "--preparation-receipt", str(prepare), "--environment", "native", "--producer", "f7-disposable-consumer", "--receipt", str(complete))
    assert checked.returncode == 0, checked.stdout + checked.stderr
    changed_result = invoke(cli, consumer, "check", "--declaration", str(declaration), "--catalogue", str(catalogue), "--lock", str(lock), "--root", str(consumer), "--state-root", str(state), "--bootstrap-receipt", str(bootstrap), "--preparation-receipt", str(prepare), "--environment", "native", "--producer", "f7-disposable-consumer", "--changed", changed, "--receipt", str(affected))
    assert changed_result.returncode == 0, changed_result.stdout + changed_result.stderr
    assert not (consumer / ".venv").exists(), "consumer-local virtualenv must not be required or retained"
    return consumer, {"complete": json.loads(complete.read_text()), "affected": json.loads(affected.read_text())}


@pytest.mark.parametrize(("fixture", "changed", "expected"), [
    ("python", "src/input.txt", {"python-service:check"}),
    ("pnpm", "src/input.txt", {"node-service:check"}),
    ("mixed", "python/src/input.txt", {"python-service:check", "node-service:check"}),
])
def test_packed_cli_executes_locked_disposable_consumers(tmp_path: Path, packed_cli: Path, fixture: str, changed: str, expected: set[str]) -> None:
    consumer, receipts = exercise(tmp_path, packed_cli, fixture, changed)
    assert (consumer / "tc-sdlc.lock").is_file()
    complete_expected = expected if fixture != "mixed" else {"python-service:check", "node-service:check"}
    assert {task["key"] for task in receipts["complete"]["tasks"]} == complete_expected
    assert {task["key"] for task in receipts["affected"]["tasks"]} == expected
