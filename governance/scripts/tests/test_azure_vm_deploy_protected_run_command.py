"""Contract tests for the protected Managed Run Command apply transport."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "azure-vm-deploy.yml"
IMPLEMENTATION = REPO_ROOT / "docs" / "IMPLEMENTATION.md"
MIGRATION = REPO_ROOT / "docs" / "MIGRATION.md"


class GithubActionsLoader(yaml.SafeLoader):
    """Keep the YAML 1.1 parser from coercing the GitHub Actions `on` key."""


GithubActionsLoader.yaml_implicit_resolvers = {
    key: [
        (tag, pattern)
        for tag, pattern in resolvers
        if tag != "tag:yaml.org,2002:bool"
    ]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def _workflow() -> dict:
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=GithubActionsLoader)


def _apply_step() -> dict:
    return next(
        step
        for step in _workflow()["jobs"]["deploy"]["steps"]
        if step.get("name") == "Apply on each target + smoke"
    )


def _managed_cleanup_step() -> dict:
    return next(
        step
        for step in _workflow()["jobs"]["deploy"]["steps"]
        if step.get("name") == "Ensure managed apply commands are deleted"
    )


def test_ghcr_token_is_a_closed_optional_job_scoped_secret() -> None:
    """A caller must opt in; the token is scoped to apply, not the whole job."""

    workflow = _workflow()
    secret = workflow["on"]["workflow_call"]["secrets"]["ghcr-actions-token"]
    apply = _apply_step()

    assert secret["required"] in {False, "false"}
    assert "GHCR_ACTIONS_TOKEN" not in workflow["jobs"]["deploy"].get("env", {})
    assert apply["env"]["GHCR_ACTIONS_TOKEN"] == "${{ secrets.ghcr-actions-token }}"


def test_reusable_inherits_permissions_so_legacy_callers_need_no_package_write() -> None:
    """The caller grants package access only when opting into token transport."""

    workflow = _workflow()
    migration = MIGRATION.read_text(encoding="utf-8")

    assert "permissions" not in workflow
    assert "permissions" not in workflow["jobs"]["deploy"]
    assert "contents: read" in migration
    assert "id-token: write" in migration
    assert "packages: write" not in migration


def test_opt_in_examples_map_the_job_token_to_the_declared_secret() -> None:
    """Documented callers must opt in with both permission and secret mapping."""

    mapping = "secrets:\n      ghcr-actions-token: ${{ github.token }}"
    workflow_example = WORKFLOW.read_text(encoding="utf-8")
    implementation = IMPLEMENTATION.read_text(encoding="utf-8")

    assert "#       secrets:\n#         ghcr-actions-token: ${{ github.token }}" in workflow_example
    assert mapping in implementation


def test_token_apply_uses_unique_managed_command_with_one_protected_parameter() -> None:
    """The protected token reaches the VM only through Azure's protected field."""

    apply = _apply_step()["run"]

    assert "az vm run-command create" in apply
    assert "az vm run-command show" in apply
    assert "az vm run-command delete" in apply
    assert "--protected-parameters" in apply
    assert 'HERMES_GHCR_ACTIONS_TOKEN="$GHCR_ACTIONS_TOKEN"' not in apply
    assert '--protected-parameters "@/dev/fd/${protected_fd}"' in apply
    assert "printf 'HERMES_GHCR_ACTIONS_TOKEN=%s'" in apply
    assert "apply-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}-${INVOCATION_SUFFIX}-${i}" in apply
    assert "secrets.token_hex" in apply
    assert apply.count("--protected-parameters") == 1
    assert "--timeout-in-seconds 5400" in apply
    assert "--instance-view" in apply
    assert "--expand instanceView" not in apply


def test_both_apply_paths_share_a_vm_local_serialization_lock() -> None:
    """Unique managed resources must not bypass per-VM deploy serialization."""

    apply = _apply_step()["run"]
    lock = "exec 9>/run/lock/tc-pipelines-azure-vm-deploy.lock; flock 9;"

    assert apply.count(lock) == 2
    managed = apply[
        apply.index("az vm run-command create") : apply.index("--protected-parameters")
    ]
    legacy = apply[
        apply.index("az vm run-command invoke") : apply.index("--query 'value[0].message'")
    ]
    assert lock in managed
    assert lock in legacy


def test_token_path_keeps_legacy_invoke_for_callers_without_a_token() -> None:
    """Existing consumers continue to invoke the target script directly."""

    apply = _apply_step()["run"]

    assert 'if [[ -z "$GHCR_ACTIONS_TOKEN" ]]; then' in apply
    assert 'az vm run-command invoke' in apply
    assert 'else\n    MSG=$(run_with_retry "managed apply on ${VM}"' in apply


def test_token_is_not_written_to_targets_scripts_or_outputs() -> None:
    """The secret is neither interpolated into caller-controlled data nor surfaced."""

    apply = _apply_step()
    script = apply["run"]

    assert apply["env"]["TARGETS_YAML"] == "${{ inputs.targets }}"
    assert "GHCR_ACTIONS_TOKEN" not in apply["env"]["TARGETS_YAML"]
    create_argv = script[
        script.index("az vm run-command create") : script.index("--query 'provisioningState'")
    ]
    assert "--protected-parameters" in create_argv
    assert "$GHCR_ACTIONS_TOKEN" not in create_argv
    output_block = script[script.index('if [[ "${SURFACE_OUTPUT:-false}" == "true" ]]; then') :]
    assert "GHCR_ACTIONS_TOKEN" not in output_block
    assert "HERMES_GHCR_ACTIONS_TOKEN" not in output_block


def test_token_is_unexported_before_any_apply_child_process() -> None:
    """Only the protected create command receives the token."""

    script = _apply_step()["run"]
    unset = script.index("unset GHCR_ACTIONS_TOKEN")
    redeclare = script.index('declare GHCR_ACTIONS_TOKEN="$PROTECTED_GHCR_ACTIONS_TOKEN"')
    first_apply_child = script.index('APPLY_ACC="$(mktemp)"')
    show_block = script[script.index("az vm run-command show") : script.index("MANAGED_STATE=")]
    delete_block = script[
        script.index("az vm run-command delete") : script.index("trap cleanup_managed_command")
    ]

    assert unset < redeclare < first_apply_child
    assert "export GHCR_ACTIONS_TOKEN" not in script
    assert "GHCR_ACTIONS_TOKEN" not in show_block
    assert "GHCR_ACTIONS_TOKEN" not in delete_block


def test_managed_command_cleanup_covers_create_show_delete_and_signals() -> None:
    """A pending command survives failed deletion and EXIT retries cleanup."""

    script = _apply_step()["run"]
    delete = script.index("az vm run-command delete")
    delete_retry = script.rfind("run_with_retry", 0, delete)
    clear_vm = script.index('PENDING_MANAGED_VM=""', delete)
    clear_command = script.index('PENDING_MANAGED_COMMAND=""', delete)
    pending = script.index('PENDING_MANAGED_VM="$VM"')
    create = script.index('MSG=$(run_with_retry "managed apply on ${VM}"')
    show = script.index('MANAGED_RESULT=$(run_with_retry "managed apply result on ${VM}"')

    assert "trap cleanup_managed_command EXIT" in script
    assert "trap 'exit 130' INT" in script
    assert "trap 'exit 143' TERM" in script
    assert pending < create < show
    assert delete_retry != -1
    assert "delete managed apply command" in script[delete_retry:delete]
    assert delete < clear_vm
    assert delete < clear_command


def test_always_cleanup_uses_only_the_non_secret_manifest() -> None:
    """Cancellation gets an independent, credential-free cleanup attempt."""

    apply = _apply_step()["run"]
    cleanup = _managed_cleanup_step()

    assert "always()" in cleanup["if"]
    assert cleanup["env"]["MANAGED_COMMAND_MANIFEST"] == (
        "${{ steps.apply.outputs.managed-command-manifest }}"
    )
    assert "GHCR" not in str(cleanup)
    assert "az vm run-command delete" in cleanup["run"]
    assert "run_with_retry" in cleanup["run"]
    assert "jq -r" in cleanup["run"]
    assert "managed-command-manifest=" in apply
    assert "{vm: $vm, command: $command}" in apply


def test_retry_separates_and_redacts_diagnostics_from_structured_stdout() -> None:
    """Warnings cannot corrupt the JSON stdout consumed by jq."""

    script = _apply_step()["run"]

    assert "redact_stream" in script
    assert 'redact_stream <"$stdout_pipe" >"$stdout_file" &' in script
    assert 'redact_stream <"$stderr_pipe" >"$stderr_file" &' in script
    assert 'mkfifo "$stdout_pipe" "$stderr_pipe"' in script
    assert 'cat "$stderr_file" >&2' in script
    assert 'cat "$stdout_file"' in script
    assert 'hit (Conflict); retrying in ${wait_seconds}s" >&2' in script
    assert "2>&1" not in script[script.index("run_with_retry()") : script.index("gate_run_command_output()")]


def test_managed_failure_preserves_apply_output_gate_and_legacy_output_order() -> None:
    """Managed failures are reported through the same output contract as invoke."""

    script = _apply_step()["run"]
    output = script.index('echo "----- BEGIN ${VM} apply output -----"')
    accumulate = script.index("printf '=== %s ===\\n%s\\n'", output)
    gate = script.index('gate_run_command_output "$VM" "$MSG_FILE"', output)
    managed_failure = script.index('if [[ -n "$MANAGED_FAILURE" ]]', output)
    smoke = script.index('echo "=== Smoke ${VM} (${UNITS}) ==="', output)
    cleanup = script.index("if ! cleanup_managed_command; then")

    assert output < accumulate < gate < managed_failure < smoke
    assert cleanup < output
    assert "exit 1" not in script[cleanup:output]
    assert 'MANAGED_FAILURE="managed command cleanup failed' in script[cleanup:output]


def test_remote_output_cannot_surface_the_protected_token_value() -> None:
    """A misbehaving apply script cannot echo the protected value into logs/outputs."""

    script = _apply_step()["run"]
    extract = script.index("MSG=$(jq -r")
    redact = script.index('MSG="${MSG//"$GHCR_ACTIONS_TOKEN"/***}"')
    output = script.index('echo "----- BEGIN ${VM} apply output -----"')

    assert extract < redact < output


@pytest.fixture
def fake_apply_tools(tmp_path: Path) -> tuple[Path, Path]:
    """Fake Azure/yq/sleep commands for executing the real embedded apply script."""

    bin_dir = tmp_path / "bin"
    state_dir = tmp_path / "state"
    bin_dir.mkdir()
    state_dir.mkdir()

    yq = bin_dir / "yq"
    yq.write_text(
        """#!/usr/bin/env bash
case "$1" in
  length) echo 1 ;;
  '.[0].vm-name') echo vm-test ;;
  '.[0].apply-script') echo true ;;
  '.[0].smoke-units') echo '' ;;
  *) echo "unexpected yq expression: $1" >&2; exit 2 ;;
esac
""",
        encoding="utf-8",
    )
    sleep = bin_dir / "sleep"
    sleep.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    az = bin_dir / "az"
    az.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
op="$3"
printf '%s\n' "$*" >>"$FAKE_AZ_STATE_DIR/argv.log"
count_file="$FAKE_AZ_STATE_DIR/${op}.count"
count=0
[[ -f "$count_file" ]] && count=$(<"$count_file")
count=$((count + 1))
printf '%s' "$count" >"$count_file"
case "$op" in
  create)
    while [[ $# -gt 0 ]]; do
      if [[ "$1" == "--protected-parameters" ]]; then
        protected_path="${2#@}"
        cat "$protected_path" >"$FAKE_AZ_STATE_DIR/protected.txt"
        break
      fi
      shift
    done
    if [[ "$count" -eq 1 ]]; then
      token=$(sed 's/^HERMES_GHCR_ACTIONS_TOKEN=//' "$FAKE_AZ_STATE_DIR/protected.txt")
      echo "(Conflict) synthetic $token" >&2
      exit 1
    fi
    echo Succeeded
    ;;
  show)
    if [[ "$count" -eq 1 ]]; then
      echo '(Conflict) synthetic show retry' >&2
      exit 1
    fi
    token=$(sed 's/^HERMES_GHCR_ACTIONS_TOKEN=//' "$FAKE_AZ_STATE_DIR/protected.txt")
    echo 'benign show warning' >&2
    jq -cn --arg token "$token" '{instanceView:{executionState:"Succeeded",exitCode:0,output:("result-" + $token),error:""}}'
    ;;
  delete)
    echo deleted
    ;;
  invoke)
    echo legacy-result
    ;;
  *) echo "unexpected az operation: $op" >&2; exit 2 ;;
esac
""",
        encoding="utf-8",
    )
    for executable in (yq, sleep, az):
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return bin_dir, state_dir


def _run_apply(
    tmp_path: Path,
    fake_apply_tools: tuple[Path, Path],
    *,
    token: str,
) -> subprocess.CompletedProcess[str]:
    bin_dir, state_dir = fake_apply_tools
    script = tmp_path / "apply.sh"
    script.write_text(_apply_step()["run"], encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "FAKE_AZ_STATE_DIR": str(state_dir),
            "GHCR_ACTIONS_TOKEN": token,
            "GITHUB_ENV": str(tmp_path / "github-env"),
            "GITHUB_OUTPUT": str(tmp_path / "github-output"),
            "GITHUB_RUN_ATTEMPT": "2",
            "GITHUB_RUN_ID": "123456",
            "PATH": f"{bin_dir}:{env['PATH']}",
            "RG": "rg-test",
            "RUNNER_TEMP": str(tmp_path),
            "SURFACE_OUTPUT": "true",
            "TARGETS_YAML": "ignored-by-fake-yq",
        }
    )
    return subprocess.run(
        ["bash", str(script)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_fake_azure_conflict_then_warning_keeps_json_and_token_private(
    tmp_path: Path, fake_apply_tools: tuple[Path, Path]
) -> None:
    """Retries succeed without argv, diagnostic, log, or output token exposure."""

    token = "test-ghcr-token-value"
    result = _run_apply(tmp_path, fake_apply_tools, token=token)
    _, state_dir = fake_apply_tools
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    argv_log = (state_dir / "argv.log").read_text(encoding="utf-8")
    workflow_output = (tmp_path / "github-output").read_text(encoding="utf-8")

    assert token not in argv_log
    assert token not in result.stdout
    assert token not in result.stderr
    assert token not in workflow_output
    assert "result-***" in result.stdout
    assert "synthetic show retry" in result.stderr
    assert "benign show warning" in result.stderr
    assert "JSON" not in result.stderr


def test_fake_azure_no_token_keeps_legacy_invoke_semantics(
    tmp_path: Path, fake_apply_tools: tuple[Path, Path]
) -> None:
    """The optional transport has no effect on existing no-secret callers."""

    result = _run_apply(tmp_path, fake_apply_tools, token="")
    _, state_dir = fake_apply_tools
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    argv_log = (state_dir / "argv.log").read_text(encoding="utf-8")

    assert "vm run-command invoke" in argv_log
    assert "vm run-command create" not in argv_log
    assert "legacy-result" in result.stdout


def test_fake_azure_always_cleanup_deletes_manifest_commands(
    tmp_path: Path, fake_apply_tools: tuple[Path, Path]
) -> None:
    """The independent cleanup step deletes a manifested command and its manifest."""

    bin_dir, state_dir = fake_apply_tools
    manifest = tmp_path / "managed.jsonl"
    manifest.write_text(
        '{"vm":"vm-test","command":"apply-123-1-nonce-0"}\n',
        encoding="utf-8",
    )
    script = tmp_path / "cleanup.sh"
    script.write_text(_managed_cleanup_step()["run"], encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "FAKE_AZ_STATE_DIR": str(state_dir),
            "MANAGED_COMMAND_MANIFEST": str(manifest),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "RG": "rg-test",
        }
    )

    result = subprocess.run(
        ["bash", str(script)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not manifest.exists()
    argv_log = (state_dir / "argv.log").read_text(encoding="utf-8")
    assert "vm run-command delete" in argv_log
    assert "apply-123-1-nonce-0" in argv_log


def test_two_reusable_invocations_in_one_run_use_different_command_names(
    tmp_path: Path, fake_apply_tools: tuple[Path, Path]
) -> None:
    """A runner nonce prevents same-run reusable jobs from sharing a resource."""

    first = _run_apply(tmp_path, fake_apply_tools, token="token-one")
    second = _run_apply(tmp_path, fake_apply_tools, token="token-two")
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr

    output_lines = (tmp_path / "github-output").read_text(encoding="utf-8").splitlines()
    manifests = [
        line.removeprefix("managed-command-manifest=")
        for line in output_lines
        if line.startswith("managed-command-manifest=")
    ]
    assert len(manifests) == 2
    assert manifests[0] != manifests[1]
    first_command = yaml.safe_load(Path(manifests[0]).read_text(encoding="utf-8"))["command"]
    second_command = yaml.safe_load(Path(manifests[1]).read_text(encoding="utf-8"))["command"]
    assert first_command != second_command
