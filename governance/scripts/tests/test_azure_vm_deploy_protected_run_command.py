"""Contract tests for the protected Managed Run Command apply transport."""

from __future__ import annotations

import base64
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
README = REPO_ROOT / "README.md"
SNAPSHOT_STANDARD = REPO_ROOT / "governance" / "standards" / "snapshot-before-apply.md"
DEVELOPMENT_WORKFLOW = (
    REPO_ROOT / "governance" / "standards" / "development-workflow.md"
)


class GithubActionsLoader(yaml.SafeLoader):
    """Keep the YAML 1.1 parser from coercing the GitHub Actions `on` key."""


GithubActionsLoader.yaml_implicit_resolvers = {
    key: [
        (tag, pattern) for tag, pattern in resolvers if tag != "tag:yaml.org,2002:bool"
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


def _validation_step() -> dict:
    return next(
        step
        for step in _workflow()["jobs"]["deploy"]["steps"]
        if step.get("name") == "Validate deployment policy and protected input"
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


def test_hermes_runtime_secret_is_caller_mapped_and_optional() -> None:
    """The caller maps one repository secret without adding an Environment gate."""

    workflow = _workflow()
    secrets = workflow["on"]["workflow_call"]["secrets"]
    deploy = workflow["jobs"]["deploy"]
    validation = _validation_step()
    apply = _apply_step()

    assert secrets["hermes-runtime-secrets-b64"]["required"] in {False, "false"}
    assert "environment" not in deploy
    expected_secret = "${{ secrets.hermes-runtime-secrets-b64 }}"
    assert validation["env"]["HERMES_RUNTIME_SECRETS_B64"] == expected_secret
    assert apply["env"]["HERMES_RUNTIME_SECRETS_B64"] == expected_secret


def test_opted_in_apply_output_crosses_the_reusable_workflow_boundary() -> None:
    """Callers can consume the bounded result emitted by the deploy job."""

    workflow = _workflow()
    output = workflow["on"]["workflow_call"]["outputs"]["apply-output"]

    assert output["value"] == "${{ jobs.deploy.outputs.apply-output }}"
    assert "surface-apply-output" in output["description"]


def test_protected_parameter_contract_is_fail_closed_and_bounded() -> None:
    """The fixed-name runtime bundle is optional but strictly bounded when set."""

    inputs = _workflow()["on"]["workflow_call"]["inputs"]
    script = _validation_step()["run"]

    assert inputs["snapshot-policy"]["default"] == "allowed"
    assert inputs["container-rollback-receipt-digest"]["default"] == ""
    assert "Hermes runtime secret must be canonical Base64" in script
    assert "49152" in script
    assert "36864" in script
    assert "base64.b64decode" in script
    assert "validate=True" in script
    assert "SNAPSHOT_POLICY" in script
    assert "snapshot-policy=forbidden requires skip-snapshot=true" in script
    assert (
        "snapshot-policy=forbidden requires a verified container rollback receipt"
        in script
    )
    assert "protected-diagnostic-prefix must be an uppercase ASCII prefix" in _apply_step()["run"]
    steps = _workflow()["jobs"]["deploy"]["steps"]
    assert steps.index(_validation_step()) < next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "WIF Azure login"
    )


def test_reusable_inherits_permissions_so_legacy_callers_need_no_package_write() -> (
    None
):
    """The caller grants package access only when opting into token transport."""

    workflow = _workflow()
    migration = MIGRATION.read_text(encoding="utf-8")

    assert "permissions" not in workflow
    assert "permissions" not in workflow["jobs"]["deploy"]
    assert "contents: read" in migration
    assert "id-token: write" in migration
    assert "packages: write" not in migration


def test_opt_in_examples_map_the_job_token_to_the_declared_secret() -> None:
    """Documented callers must map the configuration-time job token."""

    mapping = "secrets:\n      ghcr-actions-token: ${{ secrets.GITHUB_TOKEN }}"
    workflow_example = WORKFLOW.read_text(encoding="utf-8")
    implementation = IMPLEMENTATION.read_text(encoding="utf-8")

    assert (
        "#       secrets:\n#         ghcr-actions-token: ${{ secrets.GITHUB_TOKEN }}"
        in workflow_example
    )
    assert mapping in implementation
    assert "ghcr-actions-token: ${{ github.token }}" not in workflow_example
    assert "ghcr-actions-token: ${{ github.token }}" not in implementation


def test_runtime_secret_example_maps_repository_secret_to_declared_secret() -> None:
    workflow_example = WORKFLOW.read_text(encoding="utf-8")

    assert (
        "#         hermes-runtime-secrets-b64: "
        "${{ secrets.HERMES_RUNTIME_SECRETS_B64 }}" in workflow_example
    )


def test_apply_requires_a_unique_remote_exit_token() -> None:
    """Invoke must fail closed when Azure hides the remote shell exit code."""

    apply = _apply_step()["run"]

    sentinel = "TC_APPLY_REMOTE_EXIT_${GITHUB_RUN_ID}_${GITHUB_RUN_ATTEMPT}_${i}_"
    assert sentinel in apply
    assert "remote apply did not prove an exact exit status on" in apply
    assert 'gate_run_command_output "$VM" "$REMOTE_EXIT_SENTINEL" "$MSG_FILE"' in apply
    assert '--scripts "$REMOTE_SCRIPT"' in apply
    assert 'managed_apply_create "$VM" "$RUN_COMMAND_NAME" "$REMOTE_SCRIPT"' in apply
    assert "remote_rc=\\$?" in apply
    assert any("exit" in line and "remote_rc" in line for line in apply.splitlines())
    assert "classified remote exit {remote_exit}" in apply


def test_protected_apply_can_surface_only_a_bounded_safe_diagnostic() -> None:
    """Secret-bearing Run Commands retain one validated diagnostic code."""

    workflow = _workflow()
    protected_input = workflow["on"]["workflow_call"]["inputs"][
        "protected-diagnostic-prefix"
    ]
    apply = _apply_step()["run"]

    assert protected_input["default"] == ""
    assert "PROTECTED_DIAGNOSTIC_PREFIX" in _apply_step()["env"]
    assert "^[A-Z][A-Z0-9_]{2,63}=$" in apply
    assert "[a-z0-9][a-z0-9-]{0,79}" in apply
    assert 'remote_log=\\$(mktemp /run/tc-pipelines-apply-output.XXXXXXXX)' in apply
    assert "trap 'rm -f -- \\\"\\$remote_log\\\"' EXIT" in apply
    assert "MANAGED_DIAGNOSTICS" in apply
    assert "sort -u" in apply


def test_token_apply_uses_unique_managed_command_with_separate_protected_parameters() -> (
    None
):
    """The protected token reaches the VM only through Azure's protected field."""

    apply = _apply_step()["run"]

    assert "az vm run-command create" in apply
    assert "az vm run-command show" in apply
    assert "az vm run-command delete" in apply
    assert "--protected-parameters" in apply
    assert 'HERMES_GHCR_ACTIONS_TOKEN="$GHCR_ACTIONS_TOKEN"' not in apply
    assert '--protected-parameters "${protected_parameters[@]}"' in apply
    assert "printf 'HERMES_GHCR_ACTIONS_TOKEN=%s'" in apply
    assert "printf 'HERMES_RUNTIME_SECRETS_B64=%s'" in apply
    assert (
        "apply-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}-${INVOCATION_SUFFIX}-${i}"
        in apply
    )
    assert "secrets.token_hex" in apply
    assert apply.count("--protected-parameters") == 1
    assert "--timeout-in-seconds 5400" in apply
    assert "--instance-view" in apply
    assert "--expand instanceView" not in apply


def test_runtime_secret_uses_a_separate_fd_only_managed_transport() -> None:
    """Each protected value is one Azure CLI item and never enters Azure argv."""

    apply = _apply_step()
    script = apply["run"]
    create_argv = script[
        script.index("az vm run-command create") : script.index(
            "--query 'provisioningState'"
        )
    ]

    assert "HERMES_RUNTIME_SECRETS_B64" in apply["env"]
    assert "HERMES_RUNTIME_SECRETS_B64" not in create_argv
    assert 'protected_parameters+=("@/dev/fd/${runtime_secret_fd}")' in script
    assert 'protected_parameters+=("@/dev/fd/${ghcr_token_fd}")' in script
    assert (
        'if [[ -z "$GHCR_ACTIONS_TOKEN$HERMES_RUNTIME_SECRETS_B64" ]]; then' in script
    )
    assert 'line="${line//"$HERMES_RUNTIME_SECRETS_B64"/***}"' in script


def test_both_apply_paths_share_a_vm_local_serialization_lock() -> None:
    """Unique managed resources must not bypass per-VM deploy serialization."""

    apply = _apply_step()["run"]
    lock = "exec 9>/run/lock/tc-pipelines-azure-vm-deploy.lock"

    assert apply.count(lock) == 1
    remote_start = apply.index("REMOTE_SCRIPT=$(")
    remote_script = apply[
        remote_start : apply.index(
            'if [[ -n "$GHCR_ACTIONS_TOKEN$HERMES_RUNTIME_SECRETS_B64" ]]',
            remote_start,
        )
    ]
    assert lock in remote_script
    assert '--scripts "$REMOTE_SCRIPT"' in apply
    assert 'managed_apply_create "$VM" "$RUN_COMMAND_NAME" "$REMOTE_SCRIPT"' in apply


def test_token_path_keeps_legacy_invoke_for_callers_without_a_token() -> None:
    """Existing consumers with neither secret retain direct invoke semantics."""

    apply = _apply_step()["run"]

    assert 'if [[ -z "$GHCR_ACTIONS_TOKEN$HERMES_RUNTIME_SECRETS_B64" ]]; then' in apply
    assert "az vm run-command invoke" in apply
    assert 'else\n    MSG=$(run_with_retry "managed apply on ${VM}"' in apply


def test_token_is_not_written_to_targets_scripts_or_outputs() -> None:
    """The secret is neither interpolated into caller-controlled data nor surfaced."""

    apply = _apply_step()
    script = apply["run"]

    assert apply["env"]["TARGETS_YAML"] == "${{ inputs.targets }}"
    assert "GHCR_ACTIONS_TOKEN" not in apply["env"]["TARGETS_YAML"]
    create_argv = script[
        script.index("az vm run-command create") : script.index(
            "--query 'provisioningState'"
        )
    ]
    assert "--protected-parameters" in create_argv
    assert "$GHCR_ACTIONS_TOKEN" not in create_argv
    output_block = script[
        script.index('if [[ "${SURFACE_OUTPUT:-false}" == "true" ]]; then') :
    ]
    assert "GHCR_ACTIONS_TOKEN" not in output_block
    assert "HERMES_GHCR_ACTIONS_TOKEN" not in output_block


def test_token_is_unexported_before_any_apply_child_process() -> None:
    """Only the protected create command receives the token."""

    script = _apply_step()["run"]
    unset = script.index("unset GHCR_ACTIONS_TOKEN")
    redeclare = script.index(
        'declare GHCR_ACTIONS_TOKEN="$PROTECTED_GHCR_ACTIONS_TOKEN"'
    )
    first_apply_child = script.index('APPLY_ACC="$(mktemp)"')
    show_block = script[
        script.index("az vm run-command show") : script.index("MANAGED_STATE=")
    ]
    delete_block = script[
        script.index("az vm run-command delete") : script.index(
            "trap cleanup_managed_command"
        )
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
    show = script.index(
        'MANAGED_RESULT=$(run_with_retry "managed apply result on ${VM}"'
    )

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
    assert (
        "2>&1"
        not in script[
            script.index("run_with_retry()") : script.index("gate_run_command_output()")
        ]
    )


def test_managed_failure_preserves_apply_output_gate_and_legacy_output_order() -> None:
    """Managed failures are reported through the same output contract as invoke."""

    script = _apply_step()["run"]
    output = script.index('echo "----- BEGIN ${VM} apply output -----"')
    accumulate = script.index("printf '=== %s ===\\n%s\\n'", output)
    gate = script.index(
        'gate_run_command_output "$VM" "$REMOTE_EXIT_SENTINEL" "$MSG_FILE"',
        output,
    )
    managed_failure = script.index('if [[ -n "$MANAGED_FAILURE" ]]', output)
    smoke = script.index('echo "=== Smoke ${VM} (${UNITS}) ==="', output)
    cleanup = script.index("if ! cleanup_managed_command; then")

    assert output < accumulate < gate < managed_failure < smoke
    assert cleanup < output
    assert "exit 1" not in script[cleanup:output]
    assert 'MANAGED_FAILURE="managed command cleanup failed' in script[cleanup:output]


def test_managed_output_keeps_only_validated_diagnostics_and_exit_proof() -> None:
    """Protected runs never surface arbitrary instanceView output."""

    script = _apply_step()["run"]
    extract = script.index("mapfile -t MANAGED_SENTINELS")
    reduce = script.index('MSG="${REMOTE_EXIT_SENTINEL}=${MANAGED_EXIT_CODE}"')
    output = script.index('echo "----- BEGIN ${VM} apply output -----"')

    assert extract < reduce < output
    assert "instanceView.output" in script[extract:reduce]
    assert "instanceView.error" in script[extract:reduce]
    assert 'REMOTE_GROUP_END=") >\\"\\$remote_log\\" 2>&1"' in script
    assert "REMOTE_DIAGNOSTIC_PREFIX" in script
    assert "MANAGED_DIAGNOSTICS" in script
    assert "MSG=$(jq -r" not in script


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
  '.[0].apply-script') printf '%s\n' "${FAKE_YQ_SCRIPT:-true}" ;;
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
protected_values() {
  local joined="" parameter value separator=""
  while IFS= read -r parameter || [[ -n "$parameter" ]]; do
    value="${parameter#*=}"
    joined+="${separator}${value}"
    separator="|"
  done <"$FAKE_AZ_STATE_DIR/protected.txt"
  printf '%s' "$joined"
}
case "$op" in
  create)
    marker=$(grep -oE 'TC_APPLY_REMOTE_EXIT_[A-Za-z0-9_]+' <<<"$*")
    printf '%s' "$marker" >"$FAKE_AZ_STATE_DIR/remote-exit-marker"
    : >"$FAKE_AZ_STATE_DIR/protected.txt"
    collecting=false
    while [[ $# -gt 0 ]]; do
      if [[ "$1" == "--protected-parameters" ]]; then
        collecting=true
      elif [[ "$collecting" == true && "$1" == --* ]]; then
        break
      elif [[ "$collecting" == true ]]; then
        protected_path="${1#@}"
        cat "$protected_path" >>"$FAKE_AZ_STATE_DIR/protected.txt"
        printf '\n' >>"$FAKE_AZ_STATE_DIR/protected.txt"
      fi
      shift
    done
    if [[ "$count" -eq 1 ]]; then
      token=$(protected_values)
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
    token=$(protected_values)
    marker=$(<"$FAKE_AZ_STATE_DIR/remote-exit-marker")
    diagnostic=""
    if [[ -n "${PROTECTED_DIAGNOSTIC_PREFIX:-}" ]]; then
      diagnostic="\n${PROTECTED_DIAGNOSTIC_PREFIX}stage-input-invalid"
    fi
    echo 'benign show warning' >&2
    jq -cn --arg token "$token" --arg marker "$marker" --arg diagnostic "$diagnostic" '{instanceView:{executionState:"Succeeded",exitCode:0,output:("result-" + $token + "\n" + $marker + "=0" + $diagnostic),error:""}}'
    ;;
  delete)
    echo deleted
    ;;
  invoke)
    echo legacy-result
    while [[ $# -gt 0 ]]; do
      if [[ "$1" == "--scripts" ]]; then
        printf '%s' "$2" >"$FAKE_AZ_STATE_DIR/remote-script"
        break
      fi
      shift
    done
    marker=$(grep -oE 'TC_APPLY_REMOTE_EXIT_[A-Za-z0-9_]+' <<<"$*")
    if [[ "${FAKE_AZ_LEGACY_EXIT:-0}" == "missing" ]]; then
      echo 'remote shell exited before success marker' >&2
    else
      echo "${marker}=${FAKE_AZ_LEGACY_EXIT:-0}"
    fi
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
    runtime_secret: str = "",
    diagnostic_prefix: str = "",
    apply_script: str = "true",
    legacy_exit: str = "0",
) -> subprocess.CompletedProcess[str]:
    bin_dir, state_dir = fake_apply_tools
    script = tmp_path / "apply.sh"
    script.write_text(_apply_step()["run"], encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "FAKE_AZ_STATE_DIR": str(state_dir),
            "FAKE_AZ_LEGACY_EXIT": legacy_exit,
            "GHCR_ACTIONS_TOKEN": token,
            "HERMES_RUNTIME_SECRETS_B64": runtime_secret,
            "PROTECTED_DIAGNOSTIC_PREFIX": diagnostic_prefix,
            "FAKE_YQ_SCRIPT": apply_script,
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


def _run_validation(
    tmp_path: Path,
    *,
    runtime_secret: str = "",
    skip_snapshot: str = "false",
    snapshot_policy: str = "allowed",
    rollback_receipt_digest: str = "",
) -> subprocess.CompletedProcess[str]:
    script = tmp_path / "validate.sh"
    script.write_text(_validation_step()["run"], encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "HERMES_RUNTIME_SECRETS_B64": runtime_secret,
            "SKIP_SNAPSHOT": skip_snapshot,
            "SNAPSHOT_POLICY": snapshot_policy,
            "CONTAINER_ROLLBACK_RECEIPT_DIGEST": rollback_receipt_digest,
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
    assert "result-" not in result.stdout
    assert "TC_APPLY_REMOTE_EXIT_123456_2_0_" in result.stdout
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


def test_fake_azure_runtime_secret_alone_uses_managed_transport_without_exposure(
    tmp_path: Path, fake_apply_tools: tuple[Path, Path]
) -> None:
    """The runtime bundle opts in without requiring a GHCR token."""

    secret = "dGVzdC1ydW50aW1lLXNlY3JldA=="
    result = _run_apply(
        tmp_path,
        fake_apply_tools,
        token="",
        runtime_secret=secret,
    )
    _, state_dir = fake_apply_tools
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    argv_log = (state_dir / "argv.log").read_text(encoding="utf-8")
    protected = (state_dir / "protected.txt").read_text(encoding="utf-8")
    workflow_output = (tmp_path / "github-output").read_text(encoding="utf-8")

    assert "vm run-command create" in argv_log
    assert "vm run-command invoke" not in argv_log
    assert protected.strip() == f"HERMES_RUNTIME_SECRETS_B64={secret}"
    assert secret not in argv_log
    assert secret not in result.stdout
    assert secret not in result.stderr
    assert secret not in workflow_output
    assert "result-" not in result.stdout
    assert "TC_APPLY_REMOTE_EXIT_123456_2_0_" in result.stdout


def test_fake_azure_surfaces_only_a_validated_protected_diagnostic(
    tmp_path: Path, fake_apply_tools: tuple[Path, Path]
) -> None:
    """The explicit diagnostic is retained while the secret-bearing output is not."""

    token = "test-ghcr-diagnostic-token"
    result = _run_apply(
        tmp_path,
        fake_apply_tools,
        token=token,
        diagnostic_prefix="TC_HERMES_STAGE_DIAGNOSTIC=",
    )

    assert result.returncode == 0, result.stderr
    assert "TC_HERMES_STAGE_DIAGNOSTIC=stage-input-invalid" in result.stdout
    assert token not in result.stdout
    assert token not in result.stderr


def test_fake_azure_combines_both_protected_values_and_redacts_cleanup_output(
    tmp_path: Path, fake_apply_tools: tuple[Path, Path]
) -> None:
    token = "test-ghcr-combined-token"
    runtime_secret = "cnVudGltZS1jb21iaW5lZC1zZWNyZXQ="

    result = _run_apply(
        tmp_path,
        fake_apply_tools,
        token=token,
        runtime_secret=runtime_secret,
    )
    _, state_dir = fake_apply_tools
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    protected = (state_dir / "protected.txt").read_text(encoding="utf-8")
    argv_log = (state_dir / "argv.log").read_text(encoding="utf-8")
    workflow_output = (tmp_path / "github-output").read_text(encoding="utf-8")

    assert protected.splitlines() == [
        f"HERMES_GHCR_ACTIONS_TOKEN={token}",
        f"HERMES_RUNTIME_SECRETS_B64={runtime_secret}",
    ]
    for protected_value in (token, runtime_secret):
        assert protected_value not in argv_log
        assert protected_value not in result.stdout
        assert protected_value not in result.stderr
        assert protected_value not in workflow_output
    assert "synthetic ***|***" in result.stderr
    assert "result-" not in result.stdout
    assert "TC_APPLY_REMOTE_EXIT_123456_2_0_" in result.stdout
    assert "vm run-command delete" in argv_log
    assert (state_dir / "delete.count").read_text(encoding="utf-8") == "1"


def test_truncated_secret_fragments_never_reach_logs_or_apply_output(
    tmp_path: Path, fake_apply_tools: tuple[Path, Path]
) -> None:
    """The last 4 KiB may start inside either secret, so managed output is suppressed."""

    token = "token-prefix-unique-secret-suffix"
    runtime_secret = "cnVudGltZS1wcmVmaXgtdW5pcXVlLXNlY3JldC1zdWZmaXg="
    result = _run_apply(
        tmp_path,
        fake_apply_tools,
        token=token,
        runtime_secret=runtime_secret,
    )
    workflow_output = (tmp_path / "github-output").read_text(encoding="utf-8")

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    for fragment in (token[-13:], runtime_secret[-17:]):
        assert fragment not in result.stdout
        assert fragment not in result.stderr
        assert fragment not in workflow_output
    assert "result-" not in result.stdout


@pytest.mark.parametrize(
    "value",
    [
        "has space",
        "line1\nline2",
        "not-base64!",
        "Zg=",
        "Zg===",
        "Zh==",
        "YWJjZA",
        "w6k=\N{SNOWMAN}",
    ],
)
def test_validation_rejects_non_ascii_malformed_or_noncanonical_base64(
    tmp_path: Path, value: str
) -> None:
    result = _run_validation(tmp_path, runtime_secret=value)

    assert result.returncode != 0
    assert value not in result.stdout
    assert value not in result.stderr


@pytest.mark.parametrize("decoded_size", [1, 2, 3, 36864])
def test_validation_accepts_canonical_base64_through_decoded_size_boundary(
    tmp_path: Path, decoded_size: int
) -> None:
    value = base64.b64encode(b"x" * decoded_size).decode("ascii")

    result = _run_validation(tmp_path, runtime_secret=value)

    assert result.returncode == 0, result.stderr
    assert value not in result.stdout
    assert value not in result.stderr


def test_validation_rejects_payload_beyond_encoded_and_decoded_byte_boundary(
    tmp_path: Path,
) -> None:
    value = base64.b64encode(b"x" * 36865).decode("ascii")
    assert len(value.encode("ascii")) == 49156

    result = _run_validation(tmp_path, runtime_secret=value)

    assert result.returncode != 0
    assert value not in result.stdout
    assert value not in result.stderr


def test_snapshot_policy_forbidden_requires_skip_snapshot(tmp_path: Path) -> None:
    rejected = _run_validation(
        tmp_path,
        snapshot_policy="forbidden",
        skip_snapshot="false",
        rollback_receipt_digest=f"sha256:{'a' * 64}",
    )
    admitted = _run_validation(
        tmp_path,
        snapshot_policy="forbidden",
        skip_snapshot="true",
        rollback_receipt_digest=f"sha256:{'a' * 64}",
    )

    assert rejected.returncode != 0
    assert "snapshot-policy=forbidden requires skip-snapshot=true" in rejected.stderr
    assert admitted.returncode == 0, admitted.stderr


def test_empty_skip_snapshot_is_normalized_to_false(tmp_path: Path) -> None:
    result = _run_validation(tmp_path, skip_snapshot="")

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("digest", ["", "sha256:abc", f"sha256:{'A' * 64}"])
def test_forbidden_policy_requires_exact_container_rollback_receipt(
    tmp_path: Path, digest: str
) -> None:
    result = _run_validation(
        tmp_path,
        snapshot_policy="forbidden",
        skip_snapshot="true",
        rollback_receipt_digest=digest,
    )

    assert result.returncode != 0
    assert (
        "snapshot-policy=forbidden requires a verified container rollback receipt"
        in result.stderr
    )


def test_forbidden_policy_accepts_content_addressed_container_rollback_receipt(
    tmp_path: Path,
) -> None:
    digest = f"sha256:{'b' * 64}"
    result = _run_validation(
        tmp_path,
        snapshot_policy="forbidden",
        skip_snapshot="true",
        rollback_receipt_digest=digest,
    )

    assert result.returncode == 0, result.stderr


def test_forbidden_policy_skips_snapshot_action_and_runs_only_a_notice() -> None:
    steps = _workflow()["jobs"]["deploy"]["steps"]
    snapshot = next(step for step in steps if step.get("name") == "Snapshot all VMs")
    notice = next(
        step
        for step in steps
        if step.get("name") == "Verify host snapshots are forbidden"
    )

    assert snapshot["if"] == "${{ inputs.snapshot-policy != 'forbidden' }}"
    assert notice["if"] == "${{ inputs.snapshot-policy == 'forbidden' }}"
    assert "uses" not in notice
    assert "az " not in notice["run"]
    assert "snapshot" not in notice["run"].lower()


def test_container_only_exception_is_tied_to_canonical_governance() -> None:
    workflow = _workflow()
    snapshot_input = workflow["on"]["workflow_call"]["inputs"]["snapshot-policy"]
    standard = " ".join(SNAPSHOT_STANDARD.read_text(encoding="utf-8").split())
    development = " ".join(DEVELOPMENT_WORKFLOW.read_text(encoding="utf-8").split())
    readme = " ".join(README.read_text(encoding="utf-8").split())

    assert (
        "container-only deployment exception" in snapshot_input["description"].lower()
    )
    for required in (
        "Container-only deployment exception",
        "`snapshot-policy=forbidden`",
        "protected path and configuration backup",
        "immutable predecessor container image",
        "`container-rollback-receipt-digest`",
        "archive and manifest digests",
        "no Azure storage command",
        "Host disaster recovery remains a separate manual operation",
        "`snapshot-policy=forbidden` without `skip-snapshot=true` fails admission",
        "`snapshot-policy=allowed` with `skip-snapshot=true` remains",
    ):
        assert required in standard
    assert "container-only exception" in development.lower()
    assert "snapshot-before-apply.md" in development
    assert "container-only exception" in readme.lower()
    assert "snapshot-before-apply.md" in readme


@pytest.mark.parametrize("remote_exit", ["missing", "23", "-1", "256", "invalid"])
def test_fake_azure_no_token_fails_without_exact_zero_remote_exit(
    tmp_path: Path,
    fake_apply_tools: tuple[Path, Path],
    remote_exit: str,
) -> None:
    """A zero Azure CLI status cannot hide a failed remote shell."""

    result = _run_apply(
        tmp_path,
        fake_apply_tools,
        token="",
        legacy_exit=remote_exit,
    )

    assert result.returncode != 0
    assert "remote apply did not prove an exact exit status on vm-test" in result.stderr


def test_remote_wrapper_reports_exit_from_exec_based_caller(
    tmp_path: Path, fake_apply_tools: tuple[Path, Path]
) -> None:
    """A caller exec cannot replace the parent that reports remote status."""

    result = _run_apply(
        tmp_path,
        fake_apply_tools,
        token="",
        apply_script="exec bash -c 'exit 23'",
    )
    _, state_dir = fake_apply_tools
    assert result.returncode == 0, result.stderr
    remote_script = (state_dir / "remote-script").read_text(encoding="utf-8")
    remote_script = remote_script.replace(
        "exec 9>/run/lock/tc-pipelines-azure-vm-deploy.lock",
        f"exec 9>{tmp_path / 'deploy.lock'}",
    )
    remote_script = remote_script.replace("  flock 9", "  true")

    remote = subprocess.run(
        ["bash", "-c", remote_script],
        text=True,
        capture_output=True,
        check=False,
    )

    assert remote.returncode == 23
    assert "TC_APPLY_REMOTE_EXIT_123456_2_0_" in remote.stdout
    assert remote.stdout.rstrip().endswith("=23")


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
    first_command = yaml.safe_load(Path(manifests[0]).read_text(encoding="utf-8"))[
        "command"
    ]
    second_command = yaml.safe_load(Path(manifests[1]).read_text(encoding="utf-8"))[
        "command"
    ]
    assert first_command != second_command
