"""Stream a bounded deployment request through Cloudflare Access SSH."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = "tc.deploy.request.v1"
REQUEST_FIELDS = {
    "baseline_mode",
    "cluster",
    "deployment_id",
    "held_scope",
    "hold_action",
    "new_deployment_id",
    "schema_version",
    "request_id",
    "repository",
    "release_sha",
    "release_tag",
    "tc_pipelines_pin",
    "validation_run_id",
    "workflow_sha",
    "run_id",
    "run_attempt",
    "environment",
    "operation",
}
OPERATIONS = {
    "canary",
    "cleanup",
    "fleet",
    "readiness",
    "resolve-hold",
    "stage",
    "status",
    "verify",
}
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
REPOSITORY = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,38})/[A-Za-z0-9_.-]{1,100}")
SHA = re.compile(r"[0-9a-f]{40}")
LOWER_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
RELEASE_TAG = re.compile(r"v[0-9]{4}\.[0-9]{1,2}\.[0-9]{1,2}(?:[a-z][0-9]+|\.[0-9]+)?")
RECEIPT_ID = re.compile(r"sha256:[0-9a-f]{64}")
CLOUDFLARED_RELEASE = re.compile(r"[0-9]+(?:\.[0-9]+){2}")
HOSTNAME = re.compile(r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")
USERNAME = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
SAFE_PATH = re.compile(r"/[A-Za-z0-9._/-]+")
OPENSSH_FORMAT = "OPENSSH " + "PRIVATE KEY"
OPENSSH_BEGIN = f"-----BEGIN {OPENSSH_FORMAT}-----\n"
OPENSSH_END = f"-----END {OPENSSH_FORMAT}-----"
MAX_REQUEST_BYTES = 16 * 1024
MAX_PRIVATE_KEY_BYTES = 32 * 1024
MAX_LINE_BYTES = 16 * 1024
MAX_STDOUT_BYTES = 4 * 1024 * 1024
MAX_STDERR_BYTES = 1024 * 1024
MAX_STDERR_TAIL_BYTES = 64 * 1024
TERM_GRACE_SECONDS = 1
OPERATION_TIMEOUT_SECONDS = {
    "status": 60,
    "readiness": 120,
    "verify": 300,
    "cleanup": 300,
    "stage": 900,
    "canary": 900,
    "fleet": 900,
    "resolve-hold": 900,
}
MUTATING_OPERATIONS = {"stage", "canary", "fleet", "resolve-hold", "cleanup"}


class TransportError(RuntimeError):
    """A safe transport validation error."""


@dataclass(frozen=True)
class ProcessResult:
    return_code: int
    final_line: str
    stdout_bytes: int
    stderr_bytes: int
    stderr_tail: str
    elapsed_seconds: float
    reason_code: str | None


def _required_env(name: str, maximum: int) -> str:
    value = os.environ.get(name, "")
    if not value or len(value.encode()) > maximum:
        raise TransportError(f"{name} is missing or too large")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise TransportError(f"request contains duplicate field: {key}")
        result[key] = value
    return result


def _validated_request(raw: str) -> tuple[bytes, dict[str, object]]:
    encoded = raw.encode()
    if len(encoded) > MAX_REQUEST_BYTES:
        raise TransportError("request envelope is too large")
    try:
        request = json.loads(raw, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TransportError("request envelope is not valid JSON") from exc
    if not isinstance(request, dict):
        raise TransportError("request envelope must be an object")
    unknown = sorted(set(request) - REQUEST_FIELDS)
    missing = sorted(REQUEST_FIELDS - set(request))
    if unknown:
        raise TransportError(f"request contains unknown field(s): {', '.join(unknown)}")
    if missing:
        raise TransportError(f"request is missing field(s): {', '.join(missing)}")
    if request["schema_version"] != SCHEMA:
        raise TransportError(f"schema_version must be {SCHEMA}")
    if not isinstance(request["request_id"], str) or IDENTIFIER.fullmatch(request["request_id"]) is None:
        raise TransportError("request_id has an invalid shape")
    if not isinstance(request["repository"], str) or REPOSITORY.fullmatch(request["repository"]) is None:
        raise TransportError("repository has an invalid shape")
    for field in ("release_sha", "workflow_sha"):
        if not isinstance(request[field], str) or SHA.fullmatch(request[field]) is None:
            raise TransportError(f"{field} must be a 40-character lowercase commit SHA")
    for field in ("run_id", "run_attempt"):
        if isinstance(request[field], bool) or not isinstance(request[field], int) or request[field] < 1:
            raise TransportError(f"{field} must be a positive integer")
    if request["environment"] != "production":
        raise TransportError("environment must be production")
    operation = request["operation"]
    if not isinstance(operation, str) or operation not in OPERATIONS:
        raise TransportError("operation is outside the deployment operation allowlist")
    if not isinstance(request["cluster"], str) or LOWER_IDENTIFIER.fullmatch(request["cluster"]) is None:
        raise TransportError("cluster has an invalid shape")
    if (
        not isinstance(request["deployment_id"], str)
        or IDENTIFIER.fullmatch(request["deployment_id"]) is None
    ):
        raise TransportError("deployment_id has an invalid shape")
    if not isinstance(request["tc_pipelines_pin"], str) or SHA.fullmatch(request["tc_pipelines_pin"]) is None:
        raise TransportError("tc_pipelines_pin must be a 40-character lowercase commit SHA")
    baseline_mode = request["baseline_mode"]
    if not isinstance(baseline_mode, str) or baseline_mode not in {
        "auto",
        "ordinary",
        "canonical-cutover",
    }:
        raise TransportError("baseline_mode is outside the allowlist")
    release_tag = request["release_tag"]
    if release_tag is not None and (
        not isinstance(release_tag, str) or RELEASE_TAG.fullmatch(release_tag) is None
    ):
        raise TransportError("release_tag must be null or a CalVer tag")
    validation_run_id = request["validation_run_id"]
    if validation_run_id is not None and (
        isinstance(validation_run_id, bool) or not isinstance(validation_run_id, int) or validation_run_id < 1
    ):
        raise TransportError("validation_run_id must be null or a positive integer")
    if operation == "stage":
        if release_tag is None or validation_run_id is None:
            raise TransportError("stage requires release_tag and validation_run_id")
    elif release_tag is not None or validation_run_id is not None:
        raise TransportError("release_tag and validation_run_id are stage-only")
    held_scope = request["held_scope"]
    hold_action = request["hold_action"]
    new_deployment_id = request["new_deployment_id"]
    if operation == "resolve-hold":
        if not isinstance(held_scope, str) or held_scope not in {"canary", "fleet"}:
            raise TransportError("resolve-hold requires held_scope canary or fleet")
        if not isinstance(hold_action, str) or hold_action not in {
            "rollback",
            "fix-forward",
        }:
            raise TransportError("resolve-hold requires hold_action rollback or fix-forward")
        if hold_action == "fix-forward":
            if (
                not isinstance(new_deployment_id, str)
                or IDENTIFIER.fullmatch(new_deployment_id) is None
                or new_deployment_id == request["deployment_id"]
            ):
                raise TransportError("fix-forward requires a distinct valid new_deployment_id")
        elif new_deployment_id is not None:
            raise TransportError("rollback requires new_deployment_id to be null")
        if baseline_mode != "ordinary":
            raise TransportError("resolve-hold requires baseline_mode ordinary")
    elif any(value is not None for value in (held_scope, hold_action, new_deployment_id)):
        raise TransportError("hold fields are valid only for resolve-hold")
    canonical = (json.dumps(request, separators=(",", ":"), sort_keys=True) + "\n").encode()
    return canonical, request


def _validate_response(raw: str, request: dict[str, object]) -> dict[str, object]:
    try:
        response = json.loads(raw, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TransportError("final response line is not valid JSON") from exc
    fields = {
        "schema_version",
        "request_id",
        "operation",
        "release_sha",
        "status",
        "receipt_id",
    }
    if not isinstance(response, dict) or set(response) != fields:
        raise TransportError("final response line has the wrong response fields")
    if response["schema_version"] != "tc.deploy.response.v1":
        raise TransportError("final response line has the wrong schema_version")
    for field in ("request_id", "operation", "release_sha"):
        if response[field] != request[field]:
            raise TransportError(f"response {field} does not match the request")
    if response["status"] != "succeeded":
        raise TransportError("response status is not succeeded")
    if not isinstance(response["receipt_id"], str) or RECEIPT_ID.fullmatch(response["receipt_id"]) is None:
        raise TransportError("response receipt_id is not a SHA-256 identity")
    receipt_payload = {
        field: response[field]
        for field in (
            "schema_version",
            "request_id",
            "operation",
            "release_sha",
            "status",
        )
    }
    canonical = json.dumps(receipt_payload, separators=(",", ":"), sort_keys=True).encode()
    expected_receipt = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    if not hmac.compare_digest(response["receipt_id"], expected_receipt):
        raise TransportError("response receipt_id does not match the canonical response")
    return response


def _write_result(
    response: dict[str, object],
    *,
    request_id: str,
    cloudflared_version: str,
    cloudflared_sha256: str,
) -> None:
    runner_temp = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir())
    response_root = runner_temp / "tc-deploy-responses"
    response_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    response_root.chmod(0o700)
    descriptor, name = tempfile.mkstemp(prefix=f"{request_id}-", suffix=".json", dir=response_root)
    response_path = Path(name)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        json.dump(response, handle, separators=(",", ":"), sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    output_file = Path(_required_env("TRANSPORT_OUTPUT_FILE", 4096))
    if output_file.exists() or output_file.is_symlink():
        raise TransportError("TRANSPORT_OUTPUT_FILE must not already exist")
    metadata = (
        f"receipt-id={response['receipt_id']}\n"
        f"cloudflared-version={cloudflared_version}\n"
        f"cloudflared-sha256={cloudflared_sha256}\n"
        f"response-path={response_path}\n"
    )
    _write_private(output_file, metadata.encode())


def _validated_cloudflared(raw: str) -> Path:
    if SAFE_PATH.fullmatch(raw) is None:
        raise TransportError("CLOUDFLARED_PATH must be a safe absolute path")
    path = Path(raw)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise TransportError("CLOUDFLARED_PATH does not exist") from exc
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode) or not os.access(path, os.X_OK):
        raise TransportError("CLOUDFLARED_PATH must be a regular executable, not a symlink")
    return path


def _validated_known_host(raw: str, hostname: str) -> str:
    if "\r" in raw or "\n" in raw:
        raise TransportError("SSH known host must contain exactly one line")
    fields = raw.split()
    if len(fields) != 3 or fields[0] != hostname or fields[1] != "ssh-ed25519":
        raise TransportError("SSH known host must pin this hostname to one ssh-ed25519 key")
    try:
        decoded = base64.b64decode(fields[2], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise TransportError("SSH known host public key is not valid Base64") from exc
    if len(decoded) < 32:
        raise TransportError("SSH known host public key is too short")
    return " ".join(fields) + "\n"


def _write_private(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _child_environment() -> dict[str, str]:
    """Return the small non-secret environment allowed into child processes."""
    return {
        "PATH": os.environ.get("PATH", os.defpath),
        "LANG": "C",
    }


def _validate_private_key(path: Path) -> None:
    keygen = shutil.which("ssh-keygen")
    if keygen is None:
        raise TransportError("ssh-keygen is required")
    result = subprocess.run(
        [keygen, "-y", "-P", "", "-f", str(path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        env=_child_environment(),
    )
    if result.returncode != 0:
        raise TransportError("SSH_PRIVATE_KEY must be a valid unencrypted OpenSSH private key")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _verify_cloudflared_version(path: Path, version: str) -> None:
    try:
        result = subprocess.run(
            [str(path), "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=_child_environment(),
        )
    except subprocess.TimeoutExpired as exc:
        raise TransportError("cloudflared --version exceeded 5 seconds") from exc
    first_line = result.stdout.splitlines()[0] if result.stdout.splitlines() else ""
    if (
        result.returncode != 0
        or re.match(rf"^cloudflared version {re.escape(version)}(?:\s|$)", first_line) is None
    ):
        raise TransportError("cloudflared executable version does not match metadata")


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + TERM_GRACE_SECONDS
    while time.monotonic() < deadline:
        # Reap an exited leader before probing the process group. On Linux an
        # unreaped zombie keeps its process group observable until the full
        # grace period expires, even when no descendant remains.
        process.poll()
        try:
            os.killpg(process.pid, 0)
        except (ProcessLookupError, PermissionError):
            break
        time.sleep(0.01)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    if process.poll() is None:
        process.wait(timeout=TERM_GRACE_SECONDS)


def _redact(raw: bytes, values: tuple[str, ...]) -> str:
    text = raw.decode("utf-8", errors="replace")
    for value in values:
        if value:
            text = text.replace(value, "[REDACTED]")
            # A bounded tail can begin inside a secret. Remove that boundary
            # fragment as well; fragments shorter than eight bytes are not
            # useful credentials and avoiding them prevents over-redaction.
            for offset in range(1, max(1, len(value) - 7)):
                suffix = value[offset:]
                if text.startswith(suffix):
                    text = "[REDACTED]" + text[len(suffix) :]
                    break
    return text


def _bounded_utf8_tail(text: str, maximum: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= maximum:
        return text
    return encoded[-maximum:].decode("utf-8", errors="ignore")


def _run_streamed(
    command: list[str],
    environment: dict[str, str],
    stdin_path: Path,
    *,
    timeout_seconds: float,
    redactions: tuple[str, ...] = (),
) -> ProcessResult:
    """Run one process group with fixed time/output bounds and streamed output."""
    started = time.monotonic()
    token = f"tc-{secrets.token_hex(16)}"
    print(f"::stop-commands::{token}", flush=True)
    process: subprocess.Popen[bytes] | None = None
    stdout_bytes = 0
    stderr_bytes = 0
    final_line = ""
    reason: str | None = None
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    stderr_tail = bytearray()
    try:
        with stdin_path.open("rb") as standard_input:
            process = subprocess.Popen(
                command,
                env=environment,
                stdin=standard_input,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            if process.stdout is None or process.stderr is None:
                raise TransportError("SSH process did not expose output streams")
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map():
                remaining = timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    reason = "operation_timeout"
                    break
                events = selector.select(min(remaining, 0.25))
                if not events and process.poll() is not None:
                    # Pipes may still carry buffered data; continue until EOF.
                    continue
                for key, _mask in events:
                    stream = key.fileobj
                    chunk = os.read(stream.fileno(), 8192)
                    name = str(key.data)
                    if not chunk:
                        selector.unregister(stream)
                        continue
                    if name == "stdout":
                        stdout_bytes += len(chunk)
                        if stdout_bytes > MAX_STDOUT_BYTES:
                            reason = "stdout_total_limit"
                    else:
                        stderr_bytes += len(chunk)
                        if stderr_bytes > MAX_STDERR_BYTES:
                            reason = "stderr_total_limit"
                        stderr_tail.extend(chunk)
                        if len(stderr_tail) > MAX_STDERR_TAIL_BYTES:
                            del stderr_tail[:-MAX_STDERR_TAIL_BYTES]
                    if reason is not None:
                        break
                    buffer = buffers[name]
                    buffer.extend(chunk)
                    if b"\n" not in buffer and len(buffer) > MAX_LINE_BYTES:
                        reason = f"{name}_line_limit"
                    if reason is None and b"\n" in buffer:
                        boundary = buffer.rfind(b"\n") + 1
                        complete = bytes(buffer[:boundary])
                        del buffer[:boundary]
                        lines = complete.splitlines()
                        if any(len(raw_line) > MAX_LINE_BYTES for raw_line in lines):
                            reason = f"{name}_line_limit"
                        else:
                            rendered = _redact(complete, redactions)
                            target = sys.stdout if name == "stdout" else sys.stderr
                            target.write(rendered)
                            target.flush()
                            if name == "stdout":
                                nonempty = [line.strip() for line in rendered.splitlines() if line.strip()]
                                if nonempty:
                                    final_line = nonempty[-1]
                    if reason is not None:
                        break
                if reason is not None:
                    break
            if reason is not None:
                _terminate_process_group(process)
            else:
                for name, buffer in buffers.items():
                    if buffer:
                        if len(buffer) > MAX_LINE_BYTES:
                            reason = f"{name}_line_limit"
                            _terminate_process_group(process)
                            break
                        rendered = _redact(bytes(buffer), redactions)
                        target = sys.stdout if name == "stdout" else sys.stderr
                        target.write(rendered)
                        target.flush()
                        if name == "stdout" and rendered.strip():
                            final_line = rendered.strip()
                if reason is None:
                    remaining = timeout_seconds - (time.monotonic() - started)
                    if remaining <= 0:
                        reason = "operation_timeout"
                        _terminate_process_group(process)
                    else:
                        try:
                            process.wait(timeout=remaining)
                        except subprocess.TimeoutExpired:
                            reason = "operation_timeout"
                            _terminate_process_group(process)
            return ProcessResult(
                return_code=process.returncode if process.returncode is not None else 124,
                final_line=final_line,
                stdout_bytes=min(stdout_bytes, MAX_STDOUT_BYTES + 8192),
                stderr_bytes=min(stderr_bytes, MAX_STDERR_BYTES + 8192),
                stderr_tail=_redact(bytes(stderr_tail), redactions),
                elapsed_seconds=time.monotonic() - started,
                reason_code=reason,
            )
    finally:
        if process is not None and process.poll() is None:
            _terminate_process_group(process)
        print(f"::{token}::", flush=True)


def _status_request(request: dict[str, object]) -> tuple[bytes, dict[str, object]]:
    status = dict(request)
    status["operation"] = "status"
    status["release_tag"] = None
    status["validation_run_id"] = None
    identity = hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]
    status["request_id"] = f"headless-status-{identity}"
    status["held_scope"] = None
    status["hold_action"] = None
    status["new_deployment_id"] = None
    encoded = json.dumps(status, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    return encoded, status


def _write_diagnostic(request: dict[str, object], result: ProcessResult, reason: str) -> Path:
    root = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()) / "tc-deploy-diagnostics"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f"{request['request_id']}-{request['operation']}-",
        suffix=".json",
        dir=root,
    )
    path = Path(raw_path)
    try:
        payload = {
            "schema_version": "tc.deploy.diagnostic.v1",
            "request_id": request["request_id"],
            "operation": request["operation"],
            "status": "failed",
            "reason_code": reason,
            "message": "Cloudflare Access SSH did not return a validated successful receipt",
            "elapsed_seconds": round(result.elapsed_seconds, 3),
            "return_code": result.return_code,
            "stdout_bytes": result.stdout_bytes,
            "stderr_bytes": result.stderr_bytes,
            "stderr_tail": _bounded_utf8_tail(result.stderr_tail, MAX_STDERR_TAIL_BYTES),
            "fix": "Restore the headless Access route or forced deployment controller before retrying",
            "next": "Run the non-mutating status operation and inspect this diagnostic",
            "run": f"inspect {path}",
        }
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write((json.dumps(payload, sort_keys=True) + "\n").encode())
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def run() -> int:
    hostname = _required_env("SSH_HOST", 253).lower()
    username = _required_env("SSH_USER", 32)
    if HOSTNAME.fullmatch(hostname) is None:
        raise TransportError("SSH_HOST must be a DNS hostname")
    if USERNAME.fullmatch(username) is None:
        raise TransportError("SSH_USER has an invalid shape")
    cloudflared = _validated_cloudflared(_required_env("CLOUDFLARED_PATH", 4096))
    cloudflared_version = _required_env("CLOUDFLARED_VERSION", 64)
    cloudflared_sha256 = _required_env("CLOUDFLARED_SHA256", 71)
    if CLOUDFLARED_RELEASE.fullmatch(cloudflared_version) is None:
        raise TransportError("CLOUDFLARED_VERSION has an invalid shape")
    if RECEIPT_ID.fullmatch(cloudflared_sha256) is None:
        raise TransportError("CLOUDFLARED_SHA256 must be a SHA-256 identity")
    request_bytes, request = _validated_request(_required_env("REQUEST_ENVELOPE", MAX_REQUEST_BYTES))
    known_host = _validated_known_host(_required_env("SSH_KNOWN_HOST", 4096), hostname)
    private_key = _required_env("SSH_PRIVATE_KEY", MAX_PRIVATE_KEY_BYTES)
    if (
        "\r" in private_key
        or not private_key.startswith(OPENSSH_BEGIN)
        or not private_key.rstrip().endswith(OPENSSH_END)
    ):
        raise TransportError("SSH_PRIVATE_KEY must be an OpenSSH private key")
    observed_cloudflared_sha256 = _file_sha256(cloudflared)
    if observed_cloudflared_sha256 != cloudflared_sha256:
        raise TransportError("cloudflared executable digest mismatch immediately before use")
    _verify_cloudflared_version(cloudflared, cloudflared_version)
    token_id = _required_env("TUNNEL_SERVICE_TOKEN_ID", 4096)
    token_secret = _required_env("TUNNEL_SERVICE_TOKEN_SECRET", 16384)
    if any(character in token_id + token_secret for character in "\r\n\0"):
        raise TransportError("Cloudflare service-token credentials have an invalid shape")
    ssh = shutil.which("ssh")
    if ssh is None:
        raise TransportError("ssh is required")
    temporary_root = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir())
    proxy = f"ProxyCommand={cloudflared} access ssh --hostname %h"
    with tempfile.TemporaryDirectory(prefix="tc-deploy-ssh-", dir=temporary_root) as work:
        directory = Path(work)
        directory.chmod(0o700)
        child_home = directory / "home"
        child_home.mkdir(mode=0o700)
        key_file = directory / "id_ed25519"
        known_hosts_file = directory / "known_hosts"
        _write_private(key_file, private_key.encode())
        _write_private(known_hosts_file, known_host.encode())
        _validate_private_key(key_file)
        command = [
            ssh,
            "-F",
            "/dev/null",
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            f"IdentityFile={key_file}",
            "-o",
            f"UserKnownHostsFile={known_hosts_file}",
            "-o",
            "GlobalKnownHostsFile=/dev/null",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "CheckHostIP=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "RequestTTY=no",
            "-o",
            "ConnectTimeout=30",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=4",
            "-o",
            "LogLevel=ERROR",
            "-o",
            proxy,
            f"{username}@{hostname}",
        ]
        environment = _child_environment()
        environment["HOME"] = str(child_home)
        environment["TMPDIR"] = str(directory)
        environment["TUNNEL_SERVICE_TOKEN_ID"] = token_id
        environment["TUNNEL_SERVICE_TOKEN_SECRET"] = token_secret

        def invoke(encoded: bytes, invocation: dict[str, object], label: str) -> dict[str, object]:
            request_file = directory / f"request-{label}.json"
            _write_private(request_file, encoded)
            operation = str(invocation["operation"])
            result = _run_streamed(
                command,
                environment,
                request_file,
                timeout_seconds=OPERATION_TIMEOUT_SECONDS[operation],
                redactions=(token_id, token_secret),
            )
            if result.reason_code is not None or result.return_code != 0:
                reason = result.reason_code or "ssh_exit_nonzero"
                diagnostic = _write_diagnostic(invocation, result, reason)
                print(f"cloudflare-access-ssh: {reason}", file=sys.stderr)
                print(
                    "fix: validate the Cloudflare Access service-token policy and forced-command service",
                    file=sys.stderr,
                )
                print(
                    "next: run the non-mutating status journey after correcting the reported cause",
                    file=sys.stderr,
                )
                print(f"run: inspect {diagnostic}", file=sys.stderr)
                raise TransportError(f"SSH operation failed; diagnostic: {diagnostic}")
            if not result.final_line:
                diagnostic = _write_diagnostic(invocation, result, "response_missing")
                raise TransportError(
                    f"SSH exited zero without a deployment response; diagnostic: {diagnostic}"
                )
            if len(result.final_line.encode()) > MAX_REQUEST_BYTES:
                raise TransportError("final response line is too large")
            try:
                return _validate_response(result.final_line, invocation)
            except TransportError as exc:
                diagnostic = _write_diagnostic(invocation, result, "response_invalid")
                raise TransportError(f"{exc}; diagnostic: {diagnostic}") from exc

        if request["operation"] in MUTATING_OPERATIONS:
            status_bytes, status_request = _status_request(request)
            invoke(status_bytes, status_request, "headless-status")
        response = invoke(request_bytes, request, "requested-operation")
        _write_result(
            response,
            request_id=str(request["request_id"]),
            cloudflared_version=cloudflared_version,
            cloudflared_sha256=cloudflared_sha256,
        )
        return 0


def main() -> int:
    try:
        return run()
    except (TransportError, OSError, ValueError) as exc:
        print(f"cloudflare-access-ssh: {exc}", file=sys.stderr)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
