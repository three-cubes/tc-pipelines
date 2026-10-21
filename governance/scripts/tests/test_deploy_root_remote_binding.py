"""Every remote command the pipelines advertise gets the caller's deploy root.

The host's deploy root is `TC_DEPLOY_ROOT` (execution/docs/standards/deploy-root.md,
PLA-459). The canonical examples expand `"$TC_DEPLOY_ROOT"` inside a script that
`az vm run-command` runs in a clean remote shell, so a reusable that does not bind
the variable hands that script an empty one. Each remote entry point therefore takes
a validated `deploy-root` input and exports it before the caller's script. This file
holds every entry point to that, once, as a table: a new remote entry point is a row.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
# In agent-platform the reusable workflows live at the repository root, two levels
# above execution/pipelines/; in the public tc-pipelines export the root is this
# tree's own. Resolve whichever layout this file runs in.
PLATFORM_ROOT = REPO_ROOT if (REPO_ROOT / ".github" / "workflows").is_dir() else REPO_ROOT.parents[1]
WORKFLOWS = PLATFORM_ROOT / ".github" / "workflows"
APPLY_ACTION = REPO_ROOT / ".github" / "actions" / "apply-on-vm-via-runcommand" / "action.yml"

DEPLOY_ROOT = "/srv/deploy-root"
SENTINEL = "root-seen-by-remote-script"
#: Values that must be refused before they are embedded in a remote script.
BAD_ROOTS = ("relative/root", "/srv/with space", "/srv/a;touch-x", "/srv/$(id)", "/srv/`id`", "/srv/a'b")


class _Loader(yaml.SafeLoader):
    """Keep the YAML 1.1 parser from coercing the GitHub Actions `on` key."""


_Loader.yaml_implicit_resolvers = {
    key: [(tag, pattern) for tag, pattern in resolvers if tag != "tag:yaml.org,2002:bool"]
    for key, resolvers in _Loader.yaml_implicit_resolvers.items()
}


def _load(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)


def _workflow_steps(name: str, job: str) -> list[dict]:
    return _load(WORKFLOWS / name)["jobs"][job]["steps"]


def _step(steps: list[dict], name: str) -> dict:
    return next(step for step in steps if step.get("name") == name)


@dataclass(frozen=True)
class EntryPoint:
    """One advertised way to run a script on a host, and where its `deploy-root` input is declared."""

    name: str
    inputs: dict
    validating_step: dict


def _entry_points() -> list[EntryPoint]:
    capability = _load(WORKFLOWS / "capability-health-probe.yml")
    deploy = _load(WORKFLOWS / "azure-vm-deploy.yml")
    action = _load(APPLY_ACTION)
    return [
        EntryPoint(
            "capability-health-probe",
            capability["on"]["workflow_call"]["inputs"],
            _step(
                _workflow_steps("capability-health-probe.yml", "probe"),
                "Runtime tier — probe live capability health on the VM",
            ),
        ),
        EntryPoint(
            "azure-vm-deploy",
            deploy["on"]["workflow_call"]["inputs"],
            _step(
                _workflow_steps("azure-vm-deploy.yml", "deploy"),
                "Validate deployment policy and protected input",
            ),
        ),
        EntryPoint("apply-on-vm-via-runcommand", action["inputs"], action["runs"]["steps"][0]),
    ]


ENTRY_POINTS = _entry_points()
ENTRY_IDS = [entry.name for entry in ENTRY_POINTS]


#: Where each entry point's usage example sits: a file, and the text that holds it.
EXAMPLE_FILES = (
    WORKFLOWS / "azure-vm-deploy.yml",
    WORKFLOWS / "capability-health-probe.yml",
    APPLY_ACTION,
)


@pytest.mark.parametrize(
    "path",
    EXAMPLE_FILES,
    ids=[path.parent.name if path.name == "action.yml" else path.stem for path in EXAMPLE_FILES],
)
def test_a_usage_example_showing_deploy_root_names_a_release_by_placeholder(path: Path) -> None:
    """The example cannot pin a release that predates the input it shows.

    A concrete SHA copied from an earlier release runs that release's contract, which
    neither declares nor exports `deploy-root`, so the remote script would see an empty
    `TC_DEPLOY_ROOT`. Until a release carries the input the example names it as
    `@<sha> # vX.Y.Z`; the contract tests above are what prove the input.
    """
    text = path.read_text(encoding="utf-8")
    example_pins = re.findall(r"uses: three-cubes/tc-pipelines/\S+?/(?:workflows|actions)/\S+@(\S+)", text)
    shows_input = "deploy-root:" in text.split("inputs:")[0]

    assert shows_input, f"{path.name} no longer shows the input in its example"
    assert example_pins, f"{path.name} has no usage example pin"
    assert not any(re.fullmatch(r"[0-9a-f]{40}", pin) for pin in example_pins[:1]), (
        f"the first pin in {path.name} (its usage example) is a concrete SHA"
    )


def _fake_az(bin_dir: Path, log: Path) -> None:
    """An `az` whose run-command runs the --scripts payload in a clean shell, as the VM does."""
    fake = bin_dir / "az"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        f'echo invoked >>"{log}"\n'
        "while [[ $# -gt 0 ]]; do\n"
        '  if [[ "$1" == "--scripts" ]]; then payload="$2"; shift; fi\n'
        "  shift\n"
        "done\n"
        f'exec env -i HOME="{bin_dir}" PATH=/usr/bin:/bin /bin/bash -c "$payload"\n',
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)


def _run(script: str, tmp_path: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _fake_az(bin_dir, tmp_path / "az.log")
    (tmp_path / "temp").mkdir(exist_ok=True)
    (tmp_path / "output").write_text("", encoding="utf-8")
    base = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "RUNNER_TEMP": str(tmp_path / "temp"),
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "GITHUB_ACTION_PATH": str(APPLY_ACTION.parent),
    }
    return subprocess.run(  # the step's own script under a fake az
        ["bash", "-c", script],
        env=base | env,
        capture_output=True,
        text=True,
        check=False,
    )


def _az_invoked(tmp_path: Path) -> bool:
    return (tmp_path / "az.log").exists()


@pytest.mark.parametrize("entry", ENTRY_POINTS, ids=ENTRY_IDS)
def test_deploy_root_is_an_optional_validated_input(entry: EntryPoint) -> None:
    declared = entry.inputs["deploy-root"]

    assert str(declared.get("required")).lower() == "false", (
        "an existing caller that sets nothing must keep working"
    )
    assert declared.get("default", "") == ""
    assert "TC_DEPLOY_ROOT" in declared["description"]
    assert "^/[A-Za-z0-9._/-]*$" in entry.validating_step["run"], "the input is embedded unvalidated"


def _capability_env(deploy_root: str) -> dict[str, str]:
    return {
        "RG": "rg",
        "VM": "vm",
        "PROBE_COMMAND": f'echo {SENTINEL}="$TC_DEPLOY_ROOT"',
        "RUN_AS_USER": "",
        "CONFIG_PATH": "",
        "DEPLOY_ROOT": deploy_root,
        "DEEP": "true",
    }


def _apply_env(deploy_root: str) -> dict[str, str]:
    return {
        "RG": "rg",
        "VM": "vm",
        "SCRIPT_BODY": f'echo {SENTINEL}="$TC_DEPLOY_ROOT"',
        "DEPLOY_ROOT": deploy_root,
        "FAIL_ON_ERR": "false",
    }


def _policy_env(deploy_root: str) -> dict[str, str]:
    return {
        "DEPLOY_ROOT": deploy_root,
        "HERMES_RUNTIME_SECRETS_B64": "",
        "SKIP_SNAPSHOT": "false",
        "SNAPSHOT_POLICY": "allowed",
        "CONTAINER_ROLLBACK_RECEIPT_DIGEST": "",
        "PROTECTED_DIAGNOSTIC_PREFIX": "",
        "PROTECTED_DIAGNOSTIC_RECEIPT_PREFIX": "",
    }


@pytest.mark.parametrize(("deploy_root", "expected"), [(DEPLOY_ROOT, DEPLOY_ROOT), ("", "")])
def test_the_probe_command_sees_the_deploy_root_in_a_clean_remote_shell(
    tmp_path: Path, deploy_root: str, expected: str
) -> None:
    step = _step(
        _workflow_steps("capability-health-probe.yml", "probe"),
        "Runtime tier — probe live capability health on the VM",
    )

    result = _run(step["run"], tmp_path, _capability_env(deploy_root))

    assert result.returncode == 0, result.stderr
    assert (
        f"{SENTINEL}={expected} --deep"
        in (tmp_path / "temp" / "capability-health" / "probe-output.txt").read_text()
    )


@pytest.mark.parametrize(("deploy_root", "expected"), [(DEPLOY_ROOT, DEPLOY_ROOT), ("", "")])
def test_the_apply_script_sees_the_deploy_root_in_a_clean_remote_shell(
    tmp_path: Path, deploy_root: str, expected: str
) -> None:
    step = _load(APPLY_ACTION)["runs"]["steps"][0]

    result = _run(step["run"], tmp_path, _apply_env(deploy_root))

    assert result.returncode == 0, result.stderr
    assert f"{SENTINEL}={expected}\n" in (tmp_path / "output").read_text()


@pytest.mark.parametrize("bad", BAD_ROOTS)
@pytest.mark.parametrize("entry", ENTRY_POINTS, ids=ENTRY_IDS)
def test_an_unsafe_deploy_root_is_refused_before_anything_runs_remotely(
    tmp_path: Path, entry: EntryPoint, bad: str
) -> None:
    env = {
        "capability-health-probe": _capability_env,
        "apply-on-vm-via-runcommand": _apply_env,
        "azure-vm-deploy": _policy_env,
    }[entry.name](bad)

    result = _run(entry.validating_step["run"], tmp_path, env)

    assert result.returncode != 0
    assert not _az_invoked(tmp_path)


def _composition(step: dict, marker: str) -> str:
    """The `REMOTE_SCRIPT=$( printf ... )` block of a deploy step whose payload carries `marker`."""
    lines = step["run"].splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == "REMOTE_SCRIPT=$("]
    for start in starts:
        end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == ")")
        block = "\n".join(lines[start : end + 1])
        if marker in block:
            return block
    raise AssertionError(f"no REMOTE_SCRIPT composition carries {marker}")


#: (step, the caller script variable, its sentinel-printing body) for each remote script of azure-vm-deploy.
DEPLOY_PAYLOADS = (
    ("Remote preflight", "PREFLIGHT_SCRIPT"),
    ("Apply on each target + smoke", "SCRIPT"),
    ("Failure cleanup", "CLEANUP_SCRIPT"),
)


@pytest.mark.parametrize(("step_name", "variable"), DEPLOY_PAYLOADS, ids=[row[0] for row in DEPLOY_PAYLOADS])
def test_every_azure_vm_deploy_payload_exports_the_deploy_root_before_the_caller_script(
    tmp_path: Path, step_name: str, variable: str
) -> None:
    steps = _workflow_steps("azure-vm-deploy.yml", "deploy")
    step = _step(steps, step_name)
    policy = _step(steps, "Validate deployment policy and protected input")
    assert step["env"]["DEPLOY_ROOT_EXPORT"] == f"${{{{ steps.{policy['id']}.outputs.deploy-root-export }}}}"

    exported = _run(policy["run"], tmp_path, _policy_env(DEPLOY_ROOT))
    assert exported.returncode == 0, exported.stderr
    export_line = next(
        line.partition("=")[2]
        for line in (tmp_path / "output").read_text().splitlines()
        if line.startswith("deploy-root-export=")
    )

    compose = _composition(step, f'"${variable}"')
    prelude = (
        f"DEPLOY_ROOT_EXPORT={export_line!r}\n"
        f"{variable}='echo {SENTINEL}=\"$TC_DEPLOY_ROOT\"'\n"
        "REMOTE_SUCCESS_TOKEN=ok\nREMOTE_GROUP_END=')'\nREMOTE_EXIT_CAPTURE='remote_rc=$?'\nREMOTE_EXIT_SENTINEL=exit-code\n"
    )
    payload = subprocess.run(  # composes the payload the step sends
        ["bash", "-c", prelude + compose + '\nprintf "%s" "$REMOTE_SCRIPT"'],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    payload = payload.replace("exec 9>/run/lock/tc-pipelines-azure-vm-deploy.lock", "true").replace(
        "flock 9", "true"
    )

    ran = subprocess.run(  # the payload in a clean shell, as the VM runs it
        ["env", "-i", f"HOME={tmp_path}", "PATH=/usr/bin:/bin", "/bin/bash", "-c", payload],
        capture_output=True,
        text=True,
        check=False,
    )

    assert f"{SENTINEL}={DEPLOY_ROOT}\n" in ran.stdout, ran.stderr
