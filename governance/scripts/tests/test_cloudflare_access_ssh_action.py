"""Bounded-envelope and process-contract tests for Cloudflare Access SSH."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTION = REPO_ROOT / "actions" / "cloudflare-access-ssh" / "action.yml"
TRANSPORT = REPO_ROOT / "actions" / "cloudflare-access-ssh" / "transport.py"


def _transport_module():
    spec = importlib.util.spec_from_file_location("cloudflare_transport", TRANSPORT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _request(**updates: object) -> str:
    value: dict[str, object] = {
        "schema_version": "tc.deploy.request.v1",
        "request_id": "gha-34178531045-1",
        "repository": "three-cubes/tc-agent-zone",
        "release_sha": "a" * 40,
        "workflow_sha": "b" * 40,
        "run_id": 34178531045,
        "run_attempt": 1,
        "environment": "production",
        "operation": "canary",
        "cluster": "consultant",
        "deployment_id": "gha-34178531045-1",
        "tc_pipelines_pin": "c" * 40,
        "baseline_mode": "ordinary",
        "release_tag": None,
        "validation_run_id": None,
        "held_scope": None,
        "hold_action": None,
        "new_deployment_id": None,
    }
    value.update(updates)
    return json.dumps(value)


def _expected_receipt(request_id: str, operation: str, release_sha: str) -> str:
    response = {
        "schema_version": "tc.deploy.response.v1",
        "request_id": request_id,
        "operation": operation,
        "release_sha": release_sha,
        "status": "succeeded",
    }
    canonical = json.dumps(response, separators=(",", ":"), sort_keys=True).encode()
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _write_executable(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\nset -eu\n" + body)
    path.chmod(0o755)


def _write_python_executable(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env python3\n" + body)
    path.chmod(0o755)


def _transport_env(tmp_path: Path) -> dict[str, str]:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    capture = tmp_path / "capture"
    capture.mkdir()
    cloudflared = fake_bin / "cloudflared"
    _write_executable(
        cloudflared,
        f'printf \'%s|%s|%s|%s\' "${{TUNNEL_SERVICE_TOKEN_ID:-}}" "${{TUNNEL_SERVICE_TOKEN_SECRET:-}}" "${{SSH_PRIVATE_KEY:-}}" "${{UNRELATED_SECRET:-}}" > {tmp_path / "cloudflared-env"}\n'
        'if [ "${1:-}" = "--version" ]; then echo "cloudflared version 2026.8.3"; exit 0; fi\n'
        'echo "unexpected direct invocation" >&2; exit 99\n',
    )
    key_file = tmp_path / "fixture-key"
    keygen = shutil.which("ssh-keygen")
    assert keygen is not None
    subprocess.run(
        [keygen, "-q", "-t", "ed25519", "-N", "", "-f", str(key_file)],
        check=True,
    )
    public_key = key_file.with_suffix(".pub").read_text().split()[1]
    _write_executable(
        fake_bin / "ssh-keygen",
        f'printf \'%s|%s|%s|%s\' "${{TUNNEL_SERVICE_TOKEN_ID:-}}" "${{TUNNEL_SERVICE_TOKEN_SECRET:-}}" "${{SSH_PRIVATE_KEY:-}}" "${{UNRELATED_SECRET:-}}" > {tmp_path / "keygen-env"}\n'
        f'exec "{keygen}" "$@"\n',
    )
    _write_python_executable(
        fake_bin / "ssh",
        "import json\n"
        "import hashlib\n"
        "import os\n"
        "from pathlib import Path\n"
        "import sys\n"
        f"root = Path({str(capture)!r})\n"
        "counter = root / 'counter'\n"
        "number = int(counter.read_text()) + 1 if counter.exists() else 1\n"
        "counter.write_text(str(number))\n"
        "root.joinpath('argv.json').write_text(json.dumps(sys.argv[1:]))\n"
        "root.joinpath('env.json').write_text(json.dumps({\n"
        "    'id': os.environ.get('TUNNEL_SERVICE_TOKEN_ID'),\n"
        "    'secret': os.environ.get('TUNNEL_SERVICE_TOKEN_SECRET'),\n"
        "    'private_key': os.environ.get('SSH_PRIVATE_KEY'),\n"
        "    'known_host': os.environ.get('SSH_KNOWN_HOST'),\n"
        "    'request': os.environ.get('REQUEST_ENVELOPE'),\n"
        "    'unrelated': os.environ.get('UNRELATED_SECRET'),\n"
        "}))\n"
        "identity = next(arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('IdentityFile='))\n"
        "known_hosts = next(arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('UserKnownHostsFile='))\n"
        "root.joinpath('modes.json').write_text(json.dumps({\n"
        "    'identity': oct(Path(identity).stat().st_mode & 0o777),\n"
        "    'known_hosts': oct(Path(known_hosts).stat().st_mode & 0o777),\n"
        "}))\n"
        "root.joinpath('stdin.json').write_text(sys.stdin.read())\n"
        "root.joinpath(f'stdin-{number}.json').write_text(root.joinpath('stdin.json').read_text())\n"
        "request = json.loads(root.joinpath('stdin.json').read_text())\n"
        "print('remote streamed output', flush=True)\n"
        "if root.joinpath('fail').exists():\n"
        "    print(('x' * 1000 + '\\n') * 60 + os.environ['TUNNEL_SERVICE_TOKEN_SECRET'], file=sys.stderr, flush=True)\n"
        "    raise SystemExit(42)\n"
        "if not root.joinpath('no-receipt').exists():\n"
        "    response = {\n"
        "        'schema_version': 'tc.deploy.response.v1',\n"
        "        'request_id': root.joinpath('response-id').read_text() if root.joinpath('response-id').exists() else request['request_id'],\n"
        "        'operation': request['operation'],\n"
        "        'release_sha': request['release_sha'],\n"
        "        'status': 'succeeded',\n"
        "    }\n"
        "    canonical = json.dumps(response, separators=(',', ':'), sort_keys=True).encode()\n"
        "    response['receipt_id'] = 'sha256:' + hashlib.sha256(canonical).hexdigest()\n"
        "    if root.joinpath('wrong-receipt').exists(): response['receipt_id'] = 'sha256:' + 'd' * 64\n"
        "    print(json.dumps(response), flush=True)\n",
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "CAPTURE_DIR": str(capture),
            "CLOUDFLARED_PATH": str(cloudflared),
            "CLOUDFLARED_VERSION": "2026.8.3",
            "CLOUDFLARED_SHA256": "sha256:" + hashlib.sha256(cloudflared.read_bytes()).hexdigest(),
            "SSH_HOST": "ssh.threecubes.ai",
            "SSH_USER": "tc-deploy",
            "SSH_PRIVATE_KEY": key_file.read_text(),
            "SSH_KNOWN_HOST": f"ssh.threecubes.ai ssh-ed25519 {public_key}",
            "REQUEST_ENVELOPE": _request(),
            "TUNNEL_SERVICE_TOKEN_ID": "fixture-client-id",
            "TUNNEL_SERVICE_TOKEN_SECRET": "fixture-client-secret",  # pragma: allowlist secret
            "UNRELATED_SECRET": "fixture-unrelated-secret",  # pragma: allowlist secret
            "RUNNER_TEMP": str(tmp_path),
            "TRANSPORT_OUTPUT_FILE": str(tmp_path / "transport-output"),
        }
    )
    return env


def test_streams_canonical_envelope_without_sending_a_remote_command(
    tmp_path: Path,
) -> None:
    env = _transport_env(tmp_path)

    result = subprocess.run(
        [sys.executable, str(TRANSPORT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "remote streamed output" in result.stdout
    capture = Path(env["CAPTURE_DIR"])
    argv = json.loads((capture / "argv.json").read_text())
    assert argv[-1] == "tc-deploy@ssh.threecubes.ai"
    assert argv.count("tc-deploy@ssh.threecubes.ai") == 1
    assert "StrictHostKeyChecking=yes" in argv
    assert "BatchMode=yes" in argv
    assert "RequestTTY=no" in argv
    assert not any("fixture-client" in arg for arg in argv)
    assert json.loads((capture / "env.json").read_text()) == {
        "id": "fixture-client-id",
        "secret": "fixture-client-secret",  # pragma: allowlist secret
        "private_key": None,
        "known_host": None,
        "request": None,
        "unrelated": None,
    }
    assert (tmp_path / "cloudflared-env").read_text() == "|||"
    assert (tmp_path / "keygen-env").read_text() == "|||"
    assert json.loads((capture / "modes.json").read_text()) == {
        "identity": "0o600",
        "known_hosts": "0o600",
    }
    assert json.loads((capture / "stdin.json").read_text()) == json.loads(_request())
    assert argv[:2] == ["-F", "/dev/null"]
    assert '"schema_version": "tc.deploy.response.v1"' in result.stdout
    outputs = dict(line.split("=", 1) for line in (tmp_path / "transport-output").read_text().splitlines())
    expected_receipt = _expected_receipt("gha-34178531045-1", "canary", "a" * 40)
    assert outputs["receipt-id"] == expected_receipt
    assert outputs["cloudflared-version"] == "2026.8.3"
    assert outputs["cloudflared-sha256"] == env["CLOUDFLARED_SHA256"]
    assert (capture / "counter").read_text() == "2"
    assert json.loads((capture / "stdin-1.json").read_text())["operation"] == "status"
    assert json.loads((capture / "stdin-2.json").read_text())["operation"] == "canary"
    response_path = Path(outputs["response-path"])
    assert response_path.stat().st_mode & 0o777 == 0o600
    assert json.loads(response_path.read_text()) == {
        "schema_version": "tc.deploy.response.v1",
        "request_id": "gha-34178531045-1",
        "operation": "canary",
        "release_sha": "a" * 40,
        "status": "succeeded",
        "receipt_id": expected_receipt,
    }


@pytest.mark.parametrize("forbidden", ["command", "script", "argv", "parameters"])
def test_rejects_envelope_fields_that_can_carry_remote_commands(tmp_path: Path, forbidden: str) -> None:
    env = _transport_env(tmp_path)
    env["REQUEST_ENVELOPE"] = _request(**{forbidden: "id"})

    result = subprocess.run(
        [sys.executable, str(TRANSPORT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "unknown field" in result.stderr.lower()
    assert not (Path(env["CAPTURE_DIR"]) / "argv.json").exists()


def test_key_markers_are_exact_without_scanner_signatures() -> None:
    module = _transport_module()
    label = "OPENSSH PRIVATE KEY"
    begin = f"-----BEGIN {label}-----\n"
    end = f"-----END {label}-----"

    assert module.OPENSSH_BEGIN == begin
    assert module.OPENSSH_END == end

    source = TRANSPORT.read_text(encoding="utf-8")
    assert begin.rstrip() not in source
    assert end not in source


def test_stage_accepts_same_day_release_suffix() -> None:
    module = _transport_module()
    raw = _request(
        operation="stage",
        release_tag="v2026.9.7.4",
        validation_run_id=34177650645,
    )

    _canonical, request = module._validated_request(raw)

    assert request["release_tag"] == "v2026.9.7.4"


@pytest.mark.parametrize(
    "updates",
    [
        {"operation": "stage", "release_tag": None, "validation_run_id": 1},
        {
            "operation": "stage",
            "release_tag": "v2026.9.8",
            "validation_run_id": None,
        },
        {"operation": "canary", "release_tag": "v2026.9.8"},
        {"operation": "verify", "validation_run_id": 1},
    ],
)
def test_publication_fields_are_stage_only(updates: dict[str, object]) -> None:
    module = _transport_module()

    with pytest.raises(module.TransportError, match="stage"):
        module._validated_request(_request(**updates))


@pytest.mark.parametrize(
    "updates",
    [
        {"operation": "status", "held_scope": "canary"},
        {"operation": "canary", "hold_action": "rollback"},
        {"operation": "verify", "new_deployment_id": "replacement"},
    ],
)
def test_hold_fields_are_resolve_hold_only(updates: dict[str, object]) -> None:
    module = _transport_module()

    with pytest.raises(module.TransportError, match="resolve-hold"):
        module._validated_request(_request(**updates))


def test_stage_headless_status_clears_publication_fields(tmp_path: Path) -> None:
    env = _transport_env(tmp_path)
    env["REQUEST_ENVELOPE"] = _request(
        operation="stage",
        release_tag="v2026.9.7.4",
        validation_run_id=34177650645,
    )

    result = subprocess.run(
        [sys.executable, str(TRANSPORT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    capture = Path(env["CAPTURE_DIR"])
    status = json.loads((capture / "stdin-1.json").read_text())
    stage = json.loads((capture / "stdin-2.json").read_text())
    assert status["operation"] == "status"
    assert status["release_tag"] is None
    assert status["validation_run_id"] is None
    assert stage["release_tag"] == "v2026.9.7.4"
    assert stage["validation_run_id"] == 34177650645


def test_resolve_hold_headless_status_clears_hold_fields(tmp_path: Path) -> None:
    env = _transport_env(tmp_path)
    env["REQUEST_ENVELOPE"] = _request(
        operation="resolve-hold",
        held_scope="canary",
        hold_action="rollback",
    )

    result = subprocess.run(
        [sys.executable, str(TRANSPORT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    status = json.loads((Path(env["CAPTURE_DIR"]) / "stdin-1.json").read_text())
    assert status["operation"] == "status"
    assert status["release_tag"] is None
    assert status["validation_run_id"] is None
    assert status["held_scope"] is None
    assert status["hold_action"] is None
    assert status["new_deployment_id"] is None


def test_rejects_unpinned_host_identity_before_connecting(tmp_path: Path) -> None:
    env = _transport_env(tmp_path)
    env["SSH_KNOWN_HOST"] = "other.example ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBad"

    result = subprocess.run(
        [sys.executable, str(TRANSPORT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "known host" in result.stderr.lower()
    assert not (Path(env["CAPTURE_DIR"]) / "argv.json").exists()


def test_routine_transport_rejects_manual_recovery(tmp_path: Path) -> None:
    env = _transport_env(tmp_path)
    env["REQUEST_ENVELOPE"] = _request(operation="manual-recovery")

    result = subprocess.run(
        [sys.executable, str(TRANSPORT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "operation" in result.stderr.lower()
    assert not (Path(env["CAPTURE_DIR"]) / "argv.json").exists()


def test_rejects_non_string_operation_without_a_traceback(tmp_path: Path) -> None:
    env = _transport_env(tmp_path)
    env["REQUEST_ENVELOPE"] = _request(operation=[])

    result = subprocess.run(
        [sys.executable, str(TRANSPORT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 78
    assert "operation" in result.stderr.lower()
    assert "traceback" not in result.stderr.lower()
    assert not (Path(env["CAPTURE_DIR"]) / "argv.json").exists()


def test_zero_exit_without_a_matching_receipt_fails_the_transport(
    tmp_path: Path,
) -> None:
    env = _transport_env(tmp_path)
    (Path(env["CAPTURE_DIR"]) / "response-id").write_text("another-request")

    result = subprocess.run(
        [sys.executable, str(TRANSPORT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "response request_id does not match" in result.stderr.lower()


def test_rejects_valid_looking_receipt_that_does_not_hash_response(
    tmp_path: Path,
) -> None:
    env = _transport_env(tmp_path)
    env["REQUEST_ENVELOPE"] = _request(operation="status")
    (Path(env["CAPTURE_DIR"]) / "wrong-receipt").touch()

    result = subprocess.run(
        [sys.executable, str(TRANSPORT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 78
    assert "receipt_id does not match" in result.stderr.lower()
    assert not Path(env["TRANSPORT_OUTPUT_FILE"]).exists()


def test_zero_exit_without_a_response_receipt_fails_the_transport(
    tmp_path: Path,
) -> None:
    env = _transport_env(tmp_path)
    (Path(env["CAPTURE_DIR"]) / "no-receipt").touch()

    result = subprocess.run(
        [sys.executable, str(TRANSPORT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "final response line is not valid json" in result.stderr.lower()
    assert not Path(env["TRANSPORT_OUTPUT_FILE"]).exists()


def test_action_binds_service_credentials_to_environment_not_command_line() -> None:
    document = yaml.safe_load(ACTION.read_text())
    step = document["runs"]["steps"][0]

    assert set(document["outputs"]) == {
        "receipt-id",
        "cloudflared-version",
        "cloudflared-sha256",
        "response-path",
    }
    assert step["env"]["TUNNEL_SERVICE_TOKEN_ID"] == "${{ inputs.service-token-id }}"
    assert step["env"]["TUNNEL_SERVICE_TOKEN_SECRET"] == "${{ inputs.service-token-secret }}"
    assert "service-token-id" not in step["run"]
    assert "service-token-secret" not in step["run"]
    assert "transport.py" in step["run"]
    assert "timeout" not in document["inputs"]


def test_every_operation_has_a_fixed_code_owned_deadline() -> None:
    module = _transport_module()
    assert module.OPERATION_TIMEOUT_SECONDS == {
        "status": 60,
        "readiness": 120,
        "verify": 300,
        "cleanup": 300,
        "stage": 900,
        "canary": 900,
        "fleet": 900,
        "resolve-hold": 900,
    }
    assert set(module.OPERATION_TIMEOUT_SECONDS) == module.OPERATIONS


def test_failed_headless_status_prevents_mutation(tmp_path: Path) -> None:
    env = _transport_env(tmp_path)
    (Path(env["CAPTURE_DIR"]) / "fail").touch()
    result = subprocess.run(
        [sys.executable, str(TRANSPORT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 78
    assert (Path(env["CAPTURE_DIR"]) / "counter").read_text() == "1"
    assert not Path(env["TRANSPORT_OUTPUT_FILE"]).exists()


def test_status_is_single_non_mutating_headless_journey(tmp_path: Path) -> None:
    env = _transport_env(tmp_path)
    env["REQUEST_ENVELOPE"] = _request(operation="status")
    result = subprocess.run(
        [sys.executable, str(TRANSPORT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (Path(env["CAPTURE_DIR"]) / "counter").read_text() == "1"


def test_rehashes_cloudflared_before_reading_service_credentials(
    tmp_path: Path,
) -> None:
    env = _transport_env(tmp_path)
    env["CLOUDFLARED_SHA256"] = "sha256:" + "0" * 64
    result = subprocess.run(
        [sys.executable, str(TRANSPORT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 78
    assert "digest mismatch" in result.stderr.lower()
    assert not (Path(env["CAPTURE_DIR"]) / "counter").exists()


def test_rejects_cloudflared_digest_before_executing_the_binary(
    tmp_path: Path,
) -> None:
    env = _transport_env(tmp_path)
    executed = tmp_path / "untrusted-cloudflared-executed"
    cloudflared = Path(env["CLOUDFLARED_PATH"])
    _write_executable(
        cloudflared,
        f'touch {executed}\necho "cloudflared version 2026.8.3"\n',
    )

    result = subprocess.run(
        [sys.executable, str(TRANSPORT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 78
    assert "digest mismatch" in result.stderr.lower()
    assert not executed.exists()


def test_failure_retains_bounded_redacted_actionable_diagnostic(tmp_path: Path) -> None:
    env = _transport_env(tmp_path)
    env["REQUEST_ENVELOPE"] = _request(operation="status")
    (Path(env["CAPTURE_DIR"]) / "fail").touch()
    result = subprocess.run(
        [sys.executable, str(TRANSPORT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 78
    diagnostics = list((tmp_path / "tc-deploy-diagnostics").glob("*.json"))
    assert len(diagnostics) == 1
    assert diagnostics[0].stat().st_mode & 0o777 == 0o600
    document = json.loads(diagnostics[0].read_text())
    assert document["return_code"] == 42
    assert document["reason_code"] == "ssh_exit_nonzero"
    assert len(document["stderr_tail"].encode()) <= 64 * 1024
    assert "fixture-client-secret" not in document["stderr_tail"]
    assert "[REDACTED]" in document["stderr_tail"]
    assert all(document[field] for field in ("fix", "next", "run"))


def test_retried_failure_retains_a_fresh_diagnostic(tmp_path: Path) -> None:
    env = _transport_env(tmp_path)
    env["REQUEST_ENVELOPE"] = _request(operation="status")
    (Path(env["CAPTURE_DIR"]) / "fail").touch()

    results = [
        subprocess.run(
            [sys.executable, str(TRANSPORT)],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        for _ in range(2)
    ]

    assert [result.returncode for result in results] == [78, 78]
    assert all("ssh_exit_nonzero" in result.stderr for result in results)
    diagnostics = sorted((tmp_path / "tc-deploy-diagnostics").glob("*.json"))
    assert len(diagnostics) == 2
    assert diagnostics[0] != diagnostics[1]
    for diagnostic in diagnostics:
        assert diagnostic.stat().st_mode & 0o777 == 0o600
        assert json.loads(diagnostic.read_text())["reason_code"] == "ssh_exit_nonzero"


def test_remote_workflow_commands_are_bracketed_and_cannot_control_actions(
    tmp_path: Path,
) -> None:
    env = _transport_env(tmp_path)
    env["FAKE_SSH_WORKFLOW_COMMAND"] = "1"
    fake_ssh = Path(env["PATH"].split(":", 1)[0]) / "ssh"
    body = fake_ssh.read_text().replace(
        "print('remote streamed output', flush=True)",
        "print('::error::remote text', flush=True)",
    )
    fake_ssh.write_text(body)
    result = subprocess.run(
        [sys.executable, str(TRANSPORT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    stop = next(line for line in lines if line.startswith("::stop-commands::"))
    token = stop.split("::", 2)[2]
    assert f"::{token}::" in lines
    assert lines.index(stop) < lines.index("::error::remote text") < lines.index(f"::{token}::")


def test_supervisor_enforces_deadline_and_terminates_process_group(
    tmp_path: Path,
) -> None:
    module = _transport_module()
    parent_marker = tmp_path / "parent-signal"
    child_marker = tmp_path / "child-signal"
    helper = tmp_path / "hang.py"
    _write_python_executable(
        helper,
        "import os, signal, time\n"
        f"parent_marker = {str(parent_marker)!r}\n"
        f"child_marker = {str(child_marker)!r}\n"
        "role = 'parent'\n"
        "def stopped(_sig, _frame):\n"
        "    marker = parent_marker if role == 'parent' else child_marker\n"
        "    with open(marker, 'w') as stream: stream.write(str(os.getpid()) + '\\n')\n"
        "    raise SystemExit(0)\n"
        "signal.signal(signal.SIGTERM, stopped)\n"
        "if os.fork() == 0:\n"
        "    role = 'child'\n"
        "    signal.signal(signal.SIGTERM, stopped)\n"
        "    while True: time.sleep(1)\n"
        "while True: time.sleep(1)\n",
    )
    request = tmp_path / "request"
    request.write_bytes(b"{}")
    result = module._run_streamed([str(helper)], os.environ.copy(), request, timeout_seconds=3)
    assert result.reason_code == "operation_timeout"
    assert parent_marker.read_text().strip().isdigit()
    assert child_marker.read_text().strip().isdigit()


def test_supervisor_enforces_deadline_after_output_pipes_close(
    tmp_path: Path,
) -> None:
    module = _transport_module()
    helper = tmp_path / "closed-pipes.py"
    _write_python_executable(
        helper,
        "import os, time\nos.close(1)\nos.close(2)\ntime.sleep(2)\n",
    )
    request = tmp_path / "request"
    request.write_bytes(b"{}")

    started = time.monotonic()
    result = module._run_streamed([str(helper)], os.environ.copy(), request, timeout_seconds=0.2)
    elapsed = time.monotonic() - started

    assert result.reason_code == "operation_timeout"
    assert elapsed < 1


def test_supervisor_kills_descendant_after_process_leader_exits(tmp_path: Path) -> None:
    module = _transport_module()
    ready = tmp_path / "child-ready"
    helper = tmp_path / "orphan.py"
    _write_python_executable(
        helper,
        "import os, time\n"
        f"ready = {str(ready)!r}\n"
        "child = os.fork()\n"
        "if child != 0:\n"
        "    open(ready, 'w').write(str(child))\n"
        "    raise SystemExit(0)\n"
        "while True: time.sleep(1)\n",
    )
    request = tmp_path / "request"
    request.write_bytes(b"{}")
    result = module._run_streamed([str(helper)], os.environ.copy(), request, timeout_seconds=5)
    assert result.reason_code == "operation_timeout"
    child_pid = ready.read_text().strip()
    status = subprocess.run(
        ["ps", "-p", child_pid, "-o", "stat="],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    assert not status or status.startswith("Z")


@pytest.mark.parametrize("mode", ["line", "total"])
def test_supervisor_bounds_remote_output(tmp_path: Path, mode: str) -> None:
    module = _transport_module()
    helper = tmp_path / "flood.py"
    amount = module.MAX_LINE_BYTES + 1 if mode == "line" else module.MAX_STDOUT_BYTES + 1
    separator = "" if mode == "line" else "\\n"
    _write_python_executable(
        helper,
        f"import sys\nsys.stdout.write(('x{separator}' * {amount}))\nsys.stdout.flush()\n",
    )
    request = tmp_path / "request"
    request.write_bytes(b"{}")
    result = module._run_streamed([str(helper)], os.environ.copy(), request, timeout_seconds=5)
    assert result.reason_code == f"stdout_{mode}_limit"
    assert result.stdout_bytes <= module.MAX_STDOUT_BYTES + 8192


@pytest.mark.parametrize("mode", ["line", "total"])
def test_supervisor_bounds_stderr_and_retains_only_a_tail(tmp_path: Path, mode: str) -> None:
    module = _transport_module()
    helper = tmp_path / "stderr-flood.py"
    amount = module.MAX_LINE_BYTES + 1 if mode == "line" else module.MAX_STDERR_BYTES + 1
    separator = "" if mode == "line" else "\\n"
    _write_python_executable(
        helper,
        f"import sys\nsys.stderr.write(('x{separator}' * {amount}))\nsys.stderr.flush()\n",
    )
    request = tmp_path / "request"
    request.write_bytes(b"{}")
    result = module._run_streamed([str(helper)], os.environ.copy(), request, timeout_seconds=5)
    assert result.reason_code == f"stderr_{mode}_limit"
    assert len(result.stderr_tail.encode()) <= module.MAX_STDERR_TAIL_BYTES
