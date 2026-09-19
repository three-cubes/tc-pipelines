"""Local published-surface inventory and disposable consumer assurance.

Compatibility terminal evidence is deliberately not a release admission receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LEVELS = ("structural", "hermetic", "hosted", "live")
IDENTITY = "295831460+three-cubes-agent[bot]@users.noreply.github.com"


class AssuranceError(Exception):
    """A required assurance obligation was not demonstrated."""


def read_yaml(path):
    return yaml.safe_load(path.read_text())


def discover(root):
    rows = []
    for path in sorted((root / ".github/workflows").glob("*.y*ml")):
        data = read_yaml(path)
        events = data.get("on", data.get(True, {}))
        if events == "workflow_call" or (isinstance(events, (dict, list)) and "workflow_call" in events):
            rows.append(
                {
                    "id": "workflow." + path.stem,
                    "path": path.relative_to(root).as_posix(),
                }
            )
    for home in ("actions", ".github/actions"):
        for path in sorted((root / home).rglob("action.y*ml")):
            if read_yaml(path).get("runs", {}).get("using") == "composite":
                name = path.parent.relative_to(root).as_posix().replace("/", ".").lstrip(".")
                rows.append({"id": "action." + name, "path": path.relative_to(root).as_posix()})
    return rows


def inventory(root):
    data = read_yaml(root / "assurance/surfaces.yaml")
    if data.get("schema") != "tc.sdlc/surface-assurance/v1":
        raise AssuranceError("inventory: unsupported schema")
    entries = data.get("surfaces", [])
    actual = {row["path"]: row["id"] for row in discover(root)}
    declared = {row["path"]: row["id"] for row in entries}
    if len(declared) != len(entries) or len({r["id"] for r in entries}) != len(entries):
        raise AssuranceError("inventory: duplicate path or id")
    if declared != actual:
        raise AssuranceError(f"inventory: public surface mismatch; discovered={actual}, declared={declared}")
    for row in entries:
        # Every public adapter controls a GitHub boundary. None may declare a
        # structural-only PR obligation or omit hosted release qualification.
        if row.get("risk") not in {"control-plane", "deployment"}:
            raise AssuranceError(f"inventory: invalid risk for {row['id']}")
        for lane, minimum in (("pr", 2), ("release", 3)):
            levels = row.get("required", {}).get(lane, [])
            if len(levels) < minimum or levels != list(LEVELS[: len(levels)]):
                raise AssuranceError(f"inventory: {row['id']} requires cumulative {lane} evidence")
        if not row.get("sabotage") or not all(isinstance(s, str) and s.strip() for s in row["sabotage"]):
            raise AssuranceError(f"inventory: missing sabotage for {row['id']}")
        evidence = row.get("evidence", {})
        if not isinstance(evidence, dict) or not set(evidence) <= set(LEVELS):
            raise AssuranceError(f"inventory: invalid evidence levels for {row['id']}")
        for refs in evidence.values():
            if not isinstance(refs, list):
                raise AssuranceError("inventory: evidence references must be lists")
            for ref in refs:
                target = (root / ref).resolve()
                if not target.is_relative_to(root.resolve()) or not target.is_file():
                    raise AssuranceError(f"inventory: missing or unsafe evidence reference {ref}")
    return {
        "surfaces": len(entries),
        "evidence_produced": ["structural"],
        "note": "Required levels are obligations, not execution claims; hosted/live evidence is not produced here.",
    }


def command(argv, cwd, *, env=None, log=None):
    env = dict(os.environ if env is None else env)
    for inherited in ("VIRTUAL_ENV", "PYTHONPATH", "PYTEST_ADDOPTS"):
        env.pop(inherited, None)
    result = subprocess.run(
        list(map(str, argv)),
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=300,
        check=False,
    )
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(result.stdout)
    return result


def require_command(argv, cwd, **kwargs):
    result = command(argv, cwd, **kwargs)
    if result.returncode:
        raise AssuranceError(f"command failed ({result.returncode}): {argv}\n{result.stdout[-8000:]}")
    return result


def tree(root, *, prepared=False):
    ignored = (
        {".git", ".venv", "node_modules", "__pycache__", ".ruff_cache", ".pytest_cache"}
        if prepared
        else set()
    )
    return {
        p.relative_to(root).as_posix(): (
            hashlib.sha256(p.read_bytes()).hexdigest(),
            p.stat().st_mode & 0o777,
        )
        for p in sorted(root.rglob("*"))
        if p.is_file() and not any(part in ignored for part in p.relative_to(root).parts)
    }


def render(root, destination):
    context = read_yaml(root / "assurance/consumers.yaml")["render"]
    env = {**os.environ, "LC_ALL": "C"}
    require_command(
        [
            "/bin/bash",
            root / "governance/scripts/bootstrap-repo-governance.sh",
            "--repo",
            context["repository"],
            "--template-dir",
            root,
            "--fitness-tag",
            context["fitness_tag"],
            "--pipelines-sha",
            context["pipelines_sha"],
            "--out-dir",
            destination,
            "--render-only",
        ],
        root,
        env=env,
    )


def prepare_generated_fixture(root):
    """Refresh the checked-in bootstrap fixture from the canonical renderer."""
    destination = root / "assurance/fixtures/generated/rendered"
    with tempfile.TemporaryDirectory(prefix="tc-render-prepare-") as scratch:
        rendered = Path(scratch) / "rendered"
        render(root, rendered)
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(rendered, destination)
    return {"rendered_files": sum(path.is_file() for path in destination.rglob("*"))}


def initialise(root):
    require_command(["git", "init", "-q", "-b", "main"], root)
    require_command(["git", "config", "user.name", "three-cubes-agent[bot]"], root)
    require_command(["git", "config", "user.email", IDENTITY], root)


def checkpoint(root):
    require_command(["git", "add", "--all"], root)
    require_command(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-qm",
            "test: prepared assurance consumer",
        ],
        root,
    )


def output_evidence(root, destination, expected, *, workspace=False):
    junit = root / "artifacts/junit.xml"
    coverage = root / "artifacts/coverage.xml"
    if not junit.is_file() or not coverage.is_file():
        raise AssuranceError(
            "missing-required-output: JUnit and coverage must be produced by this evaluation"
        )
    suites = ET.parse(junit).getroot()
    suites = [suites] if suites.tag == "testsuite" else list(suites.iter("testsuite"))
    counts = {
        key: sum(int(s.get(key, 0)) for s in suites) for key in ("tests", "failures", "errors", "skipped")
    }
    if counts["tests"] < 1 or counts["errors"] or counts["skipped"]:
        raise AssuranceError(f"unexpected-test-result: {counts}")
    if counts["failures"] != (1 if expected == "test-failure" else 0):
        raise AssuranceError(f"unexpected-test-failure: {counts}")
    cov = ET.parse(coverage).getroot()
    if int(cov.get("lines-valid", 0)) < 1 or float(cov.get("line-rate", 0)) != 1.0:
        raise AssuranceError("coverage-output: consumer code did not execute completely")
    destination.mkdir(parents=True, exist_ok=True)
    sources = [junit, coverage]
    if workspace:
        tap = root / "artifacts/workspace.tap"
        if not tap.is_file():
            raise AssuranceError("missing-required-output: workspace TAP")
        text = tap.read_text()
        failures = 1 if expected == "workspace-failure" else 0
        expected_counts = {
            "tests": 1,
            "suites": 0,
            "pass": 1 - failures,
            "fail": failures,
            "cancelled": 0,
            "skipped": 0,
            "todo": 0,
        }
        counts = re.findall(
            r"^# (tests|suites|pass|fail|cancelled|skipped|todo) ([0-9]+)$",
            text,
            re.MULTILINE,
        )
        points = re.findall(r"^(ok|not ok) ([0-9]+) - (.+)$", text, re.MULTILINE)
        expected_point = ("not ok" if failures else "ok", "1", "generated-total")
        if (
            len(counts) != len(expected_counts)
            or {name: int(value) for name, value in counts} != expected_counts
            or points != [expected_point]
            or re.findall(r"^[0-9]+\.\.[0-9]+.*$", text, re.MULTILINE) != ["1..1"]
        ):
            raise AssuranceError("unexpected-workspace-result: " + text)
        sources.append(tap)
    for source in sources:
        shutil.copy2(source, destination / source.name)
    return [destination / source.name for source in sources]


def lab(root, output, wheel=None):
    if output.exists():
        raise AssuranceError("output directory already exists; choose a fresh path to retain each attempt")
    if wheel is not None and (not wheel.is_file() or wheel.suffix != ".whl"):
        raise AssuranceError("fitness-wheel must name an existing wheel")
    output.mkdir(parents=True)
    manifest = read_yaml(root / "assurance/consumers.yaml")
    summary = {
        "evidence_mode": "compatibility-terminal",
        "mode": "compatibility",
        "fitness_input": str(wheel) if wheel else "locked-dependency",
        "fitness_digest": hashlib.sha256(wheel.read_bytes()).hexdigest() if wheel else None,
        "generated_render_equal": False,
        "cases": [],
    }
    try:
        if (
            manifest.get("schema") != "tc.sdlc/disposable-consumers/v1"
            or manifest.get("mode") != "compatibility"
            or len(manifest.get("consumers", [])) != 3
            or {s["id"] for s in manifest["consumers"]} != {"python", "mixed", "generated"}
        ):
            raise AssuranceError("consumer-manifest: exactly python, mixed and generated are required")
        with tempfile.TemporaryDirectory(prefix="tc-consumer-lab-") as scratch:
            scratch = Path(scratch)
            fresh = scratch / "fresh"
            render(root, fresh)
            if tree(fresh) != tree(root / "assurance/fixtures/generated/rendered"):
                raise AssuranceError(
                    "generated-render-drift: fresh bootstrap output differs from checked-in fixture"
                )
            summary["generated_render_equal"] = True
            for spec in manifest["consumers"]:
                for variant in ("compliant", "sabotage"):
                    consumer = scratch / f"{spec['id']}-{variant}"
                    consumer.mkdir()
                    shutil.copytree(
                        root / "assurance/fixtures/python/project",
                        consumer,
                        dirs_exist_ok=True,
                    )
                    shutil.copy2(fresh / "Makefile", consumer / "Makefile")
                    if spec["id"] == "generated":
                        shutil.copytree(fresh, consumer, dirs_exist_ok=True)
                    shutil.copytree(
                        root / "assurance/fixtures" / spec["id"] / "project",
                        consumer,
                        dirs_exist_ok=True,
                    )
                    if spec["id"] == "mixed":
                        with (consumer / "pyproject.toml").open("a") as target:
                            target.write("\n" + (consumer / "gate.toml").read_text())
                    if spec["id"] == "generated":
                        with (consumer / "pyproject.toml").open("a") as target:
                            target.write("\n" + (consumer / "pyproject.tc_fitness.toml").read_text())
                    if wheel:
                        # uv sources overrides resolution without weakening the
                        # skeleton's catalogue or declared engine floor.
                        with (consumer / "pyproject.toml").open("a") as target:
                            target.write(
                                "\n[tool.uv.sources]\nthree-cubes-fitness = {path = "
                                + json.dumps(str(wheel))
                                + "}\n"
                            )
                    initialise(consumer)
                    logs = output / spec["id"] / variant
                    logs.mkdir(parents=True)
                    for index, argv in enumerate(spec["install"]):
                        require_command(argv, consumer, log=logs / f"install-{index}.log")
                    for iteration in (1, 2):
                        for index, argv in enumerate(spec["prepare"]):
                            require_command(
                                argv,
                                consumer,
                                log=logs / f"prepare-{iteration}-{index}.log",
                            )
                        after = tree(consumer, prepared=True)
                        if iteration == 1:
                            before = after
                        elif before != after:
                            raise AssuranceError(f"preparation-not-fixed-point: {spec['id']}/{variant}")
                    checkpoint(consumer)
                    shutil.copy2(consumer / "uv.lock", logs / "uv.lock")
                    gate_steps = []
                    for step in tomllib.loads((consumer / "pyproject.toml").read_text())["tool"][
                        "tc_fitness"
                    ]["steps"]:
                        # Catalogue results complete inside their declared step,
                        # before the enclosing step's terminal result.
                        if "catalogue" in step:
                            gate_steps.extend(spec.get("catalogue_checks", []))
                        gate_steps.append(step["id"])
                    if variant == "sabotage":
                        sabotage = spec["sabotage"]
                        target = consumer / sabotage["path"]
                        if "replace" in sabotage:
                            old, new = sabotage["replace"]
                            content = target.read_text()
                            if content.count(old) != 1:
                                raise AssuranceError("sabotage target must match exactly once")
                            target.write_text(content.replace(old, new))
                        else:
                            target.unlink()
                    row = {
                        "consumer": spec["id"],
                        "variant": variant,
                        "preparation_fixed_point": True,
                        "prepared_tree_digest": hashlib.sha256(
                            json.dumps(after, sort_keys=True).encode()
                        ).hexdigest(),
                        "evaluations": [],
                    }
                    summary["cases"].append(row)
                    # The changed-file list names all fixture sources in this
                    # compatibility lane: affected selection still uses the
                    # engine's public flag, without another task definition.
                    changed = consumer / ".assurance-changed-files"
                    changed.write_text("\n".join(tree(consumer, prepared=True)) + "\n")
                    for phase in ("affected", "complete"):
                        artifact_dir = consumer / "artifacts"
                        if artifact_dir.exists():
                            shutil.rmtree(artifact_dir)
                        env = {
                            **os.environ,
                            "NO_COLOR": "1",
                            "PYTHONDONTWRITEBYTECODE": "1",
                        }
                        argv = spec["evaluate"][phase]
                        result = command(argv, consumer, env=env, log=logs / f"{phase}.log")
                        terminal = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
                        expected_rc = 0 if variant == "compliant" else 1
                        if result.returncode != expected_rc:
                            raise AssuranceError(
                                f"unexpected-exit: {spec['id']}/{variant}/{phase}: {result.returncode}\n{terminal[-7000:]}"
                            )
                        records = re.findall(
                            r"^(PASS|FAIL|SKIP) \[([^]\n]+)\](.*)$",
                            terminal,
                            re.MULTILINE,
                        )
                        if any(status == "SKIP" for status, _, _ in records):
                            raise AssuranceError("unexpected-terminal-result: SKIP is not an executed result")
                        # A CORE check can print its own FAIL diagnostic before
                        # the dispatcher emits the terminal record with an exit
                        # code. Only the latter is the execution result. Retain
                        # all result records so duplicates cannot disappear.
                        statuses = [
                            (status, name)
                            for status, name, detail in records
                            if status != "FAIL" or re.search(r" \(exit [1-9][0-9]*\)$", detail)
                        ]
                        expected_failures = {spec["sabotage"]["step"]} if variant == "sabotage" else set()
                        if variant == "sabotage" and spec["sabotage"].get("rule"):
                            expected_failures.add(spec["sabotage"]["rule"])
                        expected_statuses = [
                            ("FAIL" if name in expected_failures else "PASS", name) for name in gate_steps
                        ]
                        if statuses != expected_statuses:
                            raise AssuranceError(
                                f"unexpected-terminal-result: expected {expected_statuses}, got {statuses}"
                            )
                        if variant == "sabotage":
                            for fragment in spec["sabotage"]["diagnostics"]:
                                if fragment not in terminal:
                                    raise AssuranceError(
                                        f"unexpected-sabotage: missing {fragment!r}\n{terminal[-7000:]}"
                                    )
                            for path, fragments in spec["sabotage"].get("output_diagnostics", {}).items():
                                content = (consumer / path).read_text()
                                if not all(fragment in content for fragment in fragments):
                                    raise AssuranceError(
                                        f"unexpected-sabotage: {path} lacks expected finding"
                                    )
                        expected = spec["sabotage"]["output_result"] if variant == "sabotage" else "pass"
                        outputs = output_evidence(
                            consumer,
                            logs / phase,
                            expected,
                            workspace=spec["id"] == "mixed",
                        )
                        row["evaluations"].append(
                            {
                                "phase": phase,
                                "command": argv,
                                "exit_code": result.returncode,
                                "outputs": [p.relative_to(output).as_posix() for p in outputs],
                            }
                        )
            summary["status"] = "pass"
    except (AssuranceError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        summary["status"] = "fail"
        summary["error"] = str(exc)
        raise
    finally:
        (output / "results.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["discover", "inventory", "prepare", "render", "lab", "all"])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fitness-wheel", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command == "discover":
            result = discover(root)
        elif args.command == "inventory":
            result = inventory(root)
        elif args.command == "prepare":
            result = prepare_generated_fixture(root)
        elif args.command == "render":
            if args.output is None or args.output.exists():
                raise AssuranceError("render requires a new --output directory")
            render(root, args.output.resolve())
            result = {"rendered": str(args.output)}
        else:
            if args.output is None:
                args.output = Path(tempfile.mkdtemp(prefix="tc-assurance-")) / "evidence"
            if args.command == "all":
                inventory(root)
            result = lab(
                root,
                args.output.resolve(),
                args.fitness_wheel.resolve() if args.fitness_wheel else None,
            )
            result["evidence_directory"] = str(args.output.resolve())
        print(json.dumps(result, indent=2))
        return 0
    except (
        AssuranceError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        yaml.YAMLError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
