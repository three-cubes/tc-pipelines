"""Public, packed-package disposable consumer assurance for Task 6/F7."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
CONSUMERS = yaml.safe_load((ROOT / "assurance/fixtures/sdlc/consumers.yaml").read_text())["consumers"]
PACKAGE_VERSION = json.loads((ROOT / "packages/tc-sdlc/package.json").read_text())["version"]
FITNESS_VERSION = next(
    package["version"]
    for package in tomllib.loads((ROOT / "assurance/fixtures/sdlc/python/uv.lock").read_text())["package"]
    if package["name"] == "three-cubes-fitness"
)


def command(
    argv: list[str], cwd: Path, *, env: dict[str, str] | None = None, timeout: int = 300
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, cwd=cwd, env=env, text=True, capture_output=True, check=False, timeout=timeout
    )


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
    store = root / "runner-pnpm-store"
    runner_home = root / "runner-home"
    environment = {
        **os.environ,
        "HOME": str(runner_home),
        "XDG_CONFIG_HOME": str(runner_home / "config"),
        "XDG_CACHE_HOME": str(runner_home / "cache"),
        "XDG_DATA_HOME": str(runner_home / "data"),
        "XDG_STATE_HOME": str(runner_home / "state"),
        "PNPM_HOME": str(runner_home / "pnpm"),
    }
    installed = command(
        ["pnpm", "add", "--store-dir", str(store), f"file:{tarball}"], runner, env=environment
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    runner_lock = (runner / "pnpm-lock.yaml").read_text()
    assert "@three-cubes/tc-sdlc" in runner_lock
    assert tarball.name in runner_lock
    assert "ajv@8.20.0" in runner_lock
    assert "yaml@2.9.1" in runner_lock
    assert store.is_dir()
    shutil.rmtree(runner / "node_modules")
    replayed = command(
        ["pnpm", "install", "--offline", "--frozen-lockfile", "--store-dir", str(store)],
        runner,
        env=environment,
    )
    assert replayed.returncode == 0, replayed.stdout + replayed.stderr
    cli = runner / "node_modules/.bin/tc-sdlc"
    assert cli.is_file()
    return cli


def invoke(
    cli: Path, consumer: Path, *arguments: str, env: dict[str, str] | None = None, timeout: int = 300
) -> subprocess.CompletedProcess[str]:
    return command([str(cli), *arguments], consumer, env=env, timeout=timeout)


def exercise(
    tmp_path: Path,
    packed_cli: Path,
    spec: dict[str, object],
    *,
    shadow: bool = False,
    fitness_version: str = FITNESS_VERSION,
    run_checks: bool = True,
) -> tuple[Path, dict[str, object]]:
    consumer = tmp_path / "consumer"
    source = ROOT / "assurance/fixtures/sdlc" / str(spec["fixture"])
    assert not (source / ".venv").exists() and not (source / "node_modules").exists(), (
        "fixtures must not carry dependency state"
    )
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
    catalogued = invoke(
        cli,
        consumer,
        "catalogue",
        "--version",
        PACKAGE_VERSION,
        "--fitness-version",
        fitness_version,
        "--workflow-commit",
        "0" * 40,
        "--image-digest",
        "sha256:" + "0" * 64,
        "--output",
        str(catalogue),
    )
    assert catalogued.returncode == 0, catalogued.stdout + catalogued.stderr
    locked = invoke(
        cli,
        consumer,
        "lock",
        "--declaration",
        str(declaration),
        "--catalogue",
        str(catalogue),
        "--output",
        str(lock),
    )
    assert locked.returncode == 0, locked.stdout + locked.stderr
    bootstrapped = invoke(
        cli,
        consumer,
        "bootstrap",
        "--declaration",
        str(declaration),
        "--catalogue",
        str(catalogue),
        "--lock",
        str(lock),
        "--root",
        str(consumer),
        "--state-root",
        str(state),
        "--receipt",
        str(bootstrap),
        timeout=900,
    )
    assert bootstrapped.returncode == 0, bootstrapped.stdout + bootstrapped.stderr
    if not run_checks:
        return consumer, {}
    if shadow:
        package = consumer / "node_modules/kleur"
        package.mkdir(parents=True)
        (package / "package.json").write_text(
            '{"name":"kleur","version":"0.0.0","type":"module","exports":"./index.js"}\n'
        )
        (package / "index.js").write_text("export default { bold(value) { return `shadow:${value}`; } };\n")
    prepared = invoke(
        cli,
        consumer,
        "prepare",
        "--declaration",
        str(declaration),
        "--catalogue",
        str(catalogue),
        "--lock",
        str(lock),
        "--root",
        str(consumer),
        "--state-root",
        str(state),
        "--bootstrap-receipt",
        str(bootstrap),
        "--receipt",
        str(prepare),
    )
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    checked = invoke(
        cli,
        consumer,
        "check-all",
        "--declaration",
        str(declaration),
        "--catalogue",
        str(catalogue),
        "--lock",
        str(lock),
        "--root",
        str(consumer),
        "--state-root",
        str(state),
        "--bootstrap-receipt",
        str(bootstrap),
        "--preparation-receipt",
        str(prepare),
        "--environment",
        "native",
        "--producer",
        "f7-disposable-consumer",
        "--receipt",
        str(complete),
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    changed_result = invoke(
        cli,
        consumer,
        "check",
        "--declaration",
        str(declaration),
        "--catalogue",
        str(catalogue),
        "--lock",
        str(lock),
        "--root",
        str(consumer),
        "--state-root",
        str(state),
        "--bootstrap-receipt",
        str(bootstrap),
        "--preparation-receipt",
        str(prepare),
        "--environment",
        "native",
        "--producer",
        "f7-disposable-consumer",
        "--changed",
        str(spec["changed"]),
        "--receipt",
        str(affected),
    )
    assert changed_result.returncode == 0, changed_result.stdout + changed_result.stderr
    if not shadow:
        assert not (consumer / ".venv").exists() and not (consumer / "node_modules").exists(), (
            "consumer dependency state must not be retained"
        )
    return consumer, {
        "complete": json.loads(complete.read_text()),
        "affected": json.loads(affected.read_text()),
    }


@pytest.mark.parametrize("spec", CONSUMERS, ids=lambda spec: str(spec["id"]))
def test_packed_cli_executes_locked_disposable_consumers(
    tmp_path: Path, packed_cli: Path, spec: dict[str, object]
) -> None:
    consumer, receipts = exercise(tmp_path, packed_cli, spec)
    assert (consumer / "tc-sdlc.lock").is_file()
    complete_expected = set(spec["complete_tasks"])
    assert {task["key"] for task in receipts["complete"]["tasks"]} == complete_expected
    assert {task["key"] for task in receipts["affected"]["tasks"]} == set(spec["affected_tasks"])


def test_packed_cli_prefers_locked_state_over_local_node_shadowing(tmp_path: Path, packed_cli: Path) -> None:
    spec = next(spec for spec in CONSUMERS if spec["id"] == "pnpm")
    exercise(tmp_path, packed_cli, spec, shadow=True)


def test_packed_cli_executes_the_repository_scoped_fitness_target_with_real_engine_evidence(
    tmp_path: Path,
    packed_cli: Path,
) -> None:
    spec = next(spec for spec in CONSUMERS if spec["id"] == "python")

    consumer, _receipts = exercise(tmp_path, packed_cli, spec, run_checks=False)
    cli = tmp_path / "runner/node_modules/.bin/tc-sdlc"
    receipt = tmp_path / "fitness.json"
    hostile_bin = tmp_path / "hostile-bin"
    hostile_bin.mkdir()
    hostile = hostile_bin / "tc-fitness"
    hostile.write_text("#!/bin/sh\necho hostile-fitness >&2\nexit 23\n")
    hostile.chmod(0o700)
    result = invoke(
        cli,
        consumer,
        "fitness",
        "--declaration",
        str(consumer / "sdlc.yaml"),
        "--catalogue",
        str(consumer / "release-catalogue.json"),
        "--lock",
        str(consumer / "tc-sdlc.lock"),
        "--root",
        str(consumer),
        "--state-root",
        str(tmp_path / "state"),
        "--bootstrap-receipt",
        str(tmp_path / "bootstrap.json"),
        "--receipt",
        str(receipt),
        env={**os.environ, "PATH": f"{hostile_bin}:{os.environ.get('PATH', '')}"},
    )
    assert result.returncode == 0, result.stdout + result.stderr

    observed = json.loads(receipt.read_text())
    locked = json.loads((consumer / "tc-sdlc.lock").read_text())["fitness"]
    assert observed["schema"] == "tc.sdlc/fitness-receipt/v1"
    assert observed["engine"]["distribution"] == locked["package"]
    assert observed["engine"]["observedVersion"] == locked["version"]
    assert observed["status"] == "succeeded"
    assert observed["declarationDigest"].startswith("sha256:")
    assert observed["catalogueDigest"].startswith("sha256:")
    assert observed["lockDigest"].startswith("sha256:")
    assert observed["bootstrapContextDigest"].startswith("sha256:")
    assert observed["engine"]["executableDigest"].startswith("sha256:")
    assert observed["engine"]["environmentDigest"].startswith("sha256:")
    assert observed["runReceiptDigest"].startswith("sha256:")
    assert observed["gateOutcome"] == "passed"


def test_packed_cli_rejects_a_state_owned_fitness_distribution_version_that_differs_from_the_lock(
    tmp_path: Path,
    packed_cli: Path,
) -> None:
    spec = next(spec for spec in CONSUMERS if spec["id"] == "python")

    consumer, _receipts = exercise(
        tmp_path,
        packed_cli,
        spec,
        fitness_version="0.0.1",
        run_checks=False,
    )
    receipt = tmp_path / "fitness-version-mismatch.json"
    result = invoke(
        tmp_path / "runner/node_modules/.bin/tc-sdlc",
        consumer,
        "fitness",
        "--declaration",
        str(consumer / "sdlc.yaml"),
        "--catalogue",
        str(consumer / "release-catalogue.json"),
        "--lock",
        str(consumer / "tc-sdlc.lock"),
        "--root",
        str(consumer),
        "--state-root",
        str(tmp_path / "state"),
        "--bootstrap-receipt",
        str(tmp_path / "bootstrap.json"),
        "--receipt",
        str(receipt),
    )

    assert result.returncode != 0
    observed = json.loads(receipt.read_text())
    locked = json.loads((consumer / "tc-sdlc.lock").read_text())["fitness"]
    assert observed["engine"]["expectedVersion"] == locked["version"]
    assert observed["engine"]["observedVersion"] != locked["version"]
    assert observed["gateOutcome"] == "versionMismatch"


@pytest.mark.parametrize(
    "sabotage",
    ["missing-metadata", "ambiguous-metadata", "missing-executable", "changed-executable"],
)
def test_packed_cli_writes_a_terminal_fitness_receipt_when_managed_engine_state_is_tampered(
    tmp_path: Path,
    packed_cli: Path,
    sabotage: str,
) -> None:
    spec = next(spec for spec in CONSUMERS if spec["id"] == "python")
    consumer, _receipts = exercise(tmp_path, packed_cli, spec, run_checks=False)
    bootstrap = json.loads((tmp_path / "bootstrap.json").read_text())
    environment = tmp_path / "state" / bootstrap["stateKey"] / "dependencies/python"
    site_packages = next(environment.glob("lib/python*/site-packages"))
    metadata = next(site_packages.glob("three_cubes_fitness-*.dist-info"))
    executable = environment / "bin/tc-fitness"
    if sabotage == "missing-metadata":
        shutil.rmtree(metadata)
    elif sabotage == "ambiguous-metadata":
        shutil.copytree(metadata, site_packages / "three_cubes_fitness-duplicate.dist-info")
    elif sabotage == "missing-executable":
        executable.unlink()
    else:
        executable.write_text("#!/bin/sh\nexit 99\n")
        executable.chmod(0o700)

    receipt = tmp_path / f"fitness-{sabotage}.json"
    result = invoke(
        tmp_path / "runner/node_modules/.bin/tc-sdlc",
        consumer,
        "fitness",
        "--declaration",
        str(consumer / "sdlc.yaml"),
        "--catalogue",
        str(consumer / "release-catalogue.json"),
        "--lock",
        str(consumer / "tc-sdlc.lock"),
        "--root",
        str(consumer),
        "--state-root",
        str(tmp_path / "state"),
        "--bootstrap-receipt",
        str(tmp_path / "bootstrap.json"),
        "--receipt",
        str(receipt),
    )
    assert result.returncode != 0
    observed = json.loads(receipt.read_text())
    assert observed["schema"] == "tc.sdlc/fitness-receipt/v1"
    assert observed["status"] == "failed"
    assert observed["reason"] == "fitness_bootstrap_context_invalid"
    assert observed["engine"]["observedVersion"] is None


@pytest.mark.parametrize("broken_input", ["declaration", "catalogue", "lock"])
def test_packed_cli_writes_a_preflight_fitness_receipt_for_unreadable_inputs(
    tmp_path: Path,
    packed_cli: Path,
    broken_input: str,
) -> None:
    spec = next(spec for spec in CONSUMERS if spec["id"] == "python")
    consumer, _receipts = exercise(tmp_path, packed_cli, spec, run_checks=False)
    paths = {
        "declaration": consumer / "missing-sdlc.yaml",
        "catalogue": tmp_path / "malformed-catalogue.json",
        "lock": tmp_path / "malformed-lock.json",
    }
    if broken_input != "declaration":
        paths[broken_input].write_text("{ not JSON\n")
    receipt = tmp_path / f"fitness-input-{broken_input}.json"
    result = invoke(
        tmp_path / "runner/node_modules/.bin/tc-sdlc",
        consumer,
        "fitness",
        "--declaration",
        str(paths["declaration"] if broken_input == "declaration" else consumer / "sdlc.yaml"),
        "--catalogue",
        str(paths["catalogue"] if broken_input == "catalogue" else consumer / "release-catalogue.json"),
        "--lock",
        str(paths["lock"] if broken_input == "lock" else consumer / "tc-sdlc.lock"),
        "--root",
        str(consumer),
        "--state-root",
        str(tmp_path / "state"),
        "--bootstrap-receipt",
        str(tmp_path / "bootstrap.json"),
        "--receipt",
        str(receipt),
    )
    assert result.returncode != 0
    observed = json.loads(receipt.read_text())
    assert observed == {
        "schema": "tc.sdlc/fitness-receipt/v1",
        "status": "failed",
        "reason": "fitness_input_invalid",
        "declarationDigest": None,
        "catalogueDigest": None,
        "lockDigest": None,
        "bootstrapContextDigest": None,
        "task": {"key": None, "identity": None},
        "engine": {
            "distribution": None,
            "expectedVersion": None,
            "observedVersion": None,
            "executableDigest": None,
            "environmentDigest": None,
        },
        "config": {"path": None, "digest": None},
        "profile": {"name": None, "tier": None},
        "gateOutcome": "notRun",
        "exitCode": None,
        "runReceiptDigest": None,
    }


def test_packed_cli_clears_hostile_outer_node_preload(tmp_path: Path, packed_cli: Path) -> None:
    cli = installed_cli(packed_cli, tmp_path)
    marker = tmp_path / "hostile-preload-ran"
    preload = tmp_path / "hostile-preload.cjs"
    preload.write_text(f"require('node:fs').writeFileSync({marker.as_posix()!r}, 'executed');\n")
    catalogue = tmp_path / "release-catalogue.json"
    environment = {**os.environ, "NODE_OPTIONS": f"--require={preload}"}
    result = invoke(
        cli,
        tmp_path,
        "catalogue",
        "--version",
        PACKAGE_VERSION,
        "--fitness-version",
        FITNESS_VERSION,
        "--workflow-commit",
        "0" * 40,
        "--image-digest",
        "sha256:" + "0" * 64,
        "--output",
        str(catalogue),
        env=environment,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert catalogue.is_file()
    assert not marker.exists(), "ambient NODE_OPTIONS preload executed before the public CLI"
