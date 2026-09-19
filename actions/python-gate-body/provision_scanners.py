"""Install the canonical security scanners into an isolated, owned tool cache."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, NoReturn

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10; installed by the shared gate action.
    import tomli as tomllib

HERE = Path(__file__).resolve().parent
CHECKOV_PROJECT = HERE / "checkov-tool"
SCANNER_CATALOGUE = HERE / "scanner-versions.json"
SEMVER = re.compile(r"\d+\.\d+\.\d+\Z")
MARKER = ".tc-pipelines-scanner"


class ProvisionError(RuntimeError):
    """A scanner cannot be installed or verified safely."""


def _fail(message: str) -> NoReturn:
    raise ProvisionError(message)


def _versions() -> dict[str, Any]:
    try:
        data = json.loads(SCANNER_CATALOGUE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProvisionError(f"cannot read scanner version catalogue: {error}") from error
    if not isinstance(data, dict) or set(data) != {"checkov", "osv-scanner"}:
        _fail("scanner version catalogue must declare exactly Checkov and OSV Scanner")
    for name, identity in data.items():
        if not isinstance(identity, dict):
            _fail(f"catalogued {name} identity must be an object")
        version = identity.get("version")
        if not isinstance(version, str) or SEMVER.fullmatch(version) is None:
            _fail(f"catalogued {name} version must be exact x.y.z")
    hashes = data["osv-scanner"].get("sha256")
    if (
        not isinstance(hashes, dict)
        or set(hashes) != {"darwin_amd64", "darwin_arm64", "linux_amd64", "linux_arm64"}
        or any(re.fullmatch(r"[0-9a-f]{64}", str(value)) is None for value in hashes.values())
    ):
        _fail("catalogued OSV Scanner hashes must cover macOS and Linux amd64/arm64")
    return data


def _checkov_version() -> tuple[str, str]:
    expected_version = _versions()["checkov"]["version"]
    try:
        result = subprocess.run(
            ["uv", "lock", "--project", str(CHECKOV_PROJECT), "--check"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            _fail(f"Checkov tool lock is stale or invalid: {result.stderr.strip()}")
        lock = tomllib.loads((CHECKOV_PROJECT / "uv.lock").read_text(encoding="utf-8"))
        project = tomllib.loads((CHECKOV_PROJECT / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, KeyError, ValueError) as error:
        raise ProvisionError(f"cannot read Checkov tool lock: {error}") from error
    matches = [row.get("version") for row in lock.get("package", []) if row.get("name") == "checkov"]
    if matches != [expected_version]:
        _fail("Checkov tool lock must resolve the version in scanner-versions.json")
    if project.get("project", {}).get("dependencies") != [f"checkov=={expected_version}"]:
        _fail("Checkov tool project must be regenerated from scanner-versions.json")
    asteval_versions = [row.get("version") for row in lock.get("package", []) if row.get("name") == "asteval"]
    if len(asteval_versions) != 1 or not isinstance(asteval_versions[0], str):
        _fail("Checkov tool lock must resolve exactly one asteval package")
    try:
        asteval_parts = tuple(int(part) for part in asteval_versions[0].split("."))
    except ValueError:
        _fail("Checkov tool lock has an invalid asteval version")
    if not (asteval_parts >= (1, 0, 9) and asteval_parts < (1, 1)):
        _fail("Checkov tool lock must keep asteval in the patched >=1.0.9,<1.1 range")
    if any(row.get("name") in {"ecdsa", "python-ecdsa"} for row in lock.get("package", [])):
        _fail("Checkov tool lock contains unpatched ecdsa")
    return expected_version, asteval_versions[0]


def _scanner_root() -> tuple[Path, Path]:
    configured = os.environ.get("TC_SCANNER_BIN_DIR")
    if configured:
        bin_dir = Path(configured).expanduser()
        if not bin_dir.is_absolute():
            _fail("TC_SCANNER_BIN_DIR must be absolute")
    else:
        cache_home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        bin_dir = cache_home.expanduser() / "tc-pipelines" / "scanners" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    resolved_bin = bin_dir.resolve(strict=True)
    root = resolved_bin.parent
    if resolved_bin.name != "bin":
        _fail("TC_SCANNER_BIN_DIR must name a directory called bin")
    return root, resolved_bin


def _marker_text(tool: str, version: str) -> str:
    return f"tc-pipelines-scanner-v1\ntool={tool}\nversion={version}\n"


def _is_owned(path: Path, tool: str, version: str) -> bool:
    if path.is_symlink() or not path.is_dir():
        return False
    marker = path / MARKER
    return (
        marker.is_file()
        and not marker.is_symlink()
        and marker.read_text(encoding="utf-8") == _marker_text(tool, version)
    )


def _prune_owned_versions(tool_root: Path, tool: str, active_version: str) -> None:
    """Remove only direct, versioned cache entries bearing our exact marker."""
    if not tool_root.exists():
        return
    if tool_root.is_symlink() or not tool_root.is_dir():
        _fail(f"scanner cache path is not an owned directory: {tool_root}")
    for child in tool_root.iterdir():
        if child.name == active_version or SEMVER.fullmatch(child.name) is None:
            continue
        if _is_owned(child, tool, child.name) and child.resolve().parent == tool_root.resolve():
            shutil.rmtree(child)


def _owned_target(root: Path, tool: str, version: str) -> Path:
    tool_root = root / tool
    tool_root.mkdir(parents=True, exist_ok=True)
    if tool_root.is_symlink():
        _fail(f"scanner cache path cannot be a symlink: {tool_root}")
    _prune_owned_versions(tool_root, tool, version)
    target = tool_root / version
    if target.exists() and not _is_owned(target, tool, version):
        _fail(f"refusing to replace a scanner directory without our ownership marker: {target}")
    if not target.exists():
        target.mkdir()
        (target / MARKER).write_text(_marker_text(tool, version), encoding="utf-8")
    return target


def _publish_executable(source: Path, bin_dir: Path, name: str, owned_root: Path) -> Path:
    destination = bin_dir / name
    if destination.exists() or destination.is_symlink():
        if not destination.is_symlink():
            _fail(f"refusing to replace a non-symlink scanner executable: {destination}")
        current = destination.resolve(strict=False)
        if not current.is_relative_to(owned_root.resolve()):
            _fail(f"refusing to replace scanner executable outside the owned cache: {destination}")
        destination.unlink()
    destination.symlink_to(source)
    return destination


def _register_path(bin_dir: Path) -> None:
    path_file = os.environ.get("TC_SCANNER_PATH_FILE")
    if not path_file:
        return
    target = Path(path_file).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as stream:
        stream.write(f"{bin_dir}\n")


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "tc-pipelines-scanner-provisioner"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            destination.write_bytes(response.read())
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ProvisionError(f"download failed for {url}: {error}") from error


def _cache_lock(root: Path):
    """Serialize installers that share the versioned user or hosted cache."""
    handle = (root / ".provision.lock").open("a", encoding="utf-8")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def _osv_asset() -> tuple[str, str]:
    system = platform.system().lower()
    architecture = platform.machine().lower()
    if architecture in {"x86_64", "amd64"}:
        architecture = "amd64"
    elif architecture in {"arm64", "aarch64"}:
        architecture = "arm64"
    else:
        _fail(f"unsupported OSV Scanner architecture: {architecture}")
    if system not in {"linux", "darwin"}:
        _fail(f"unsupported OSV Scanner operating system: {system}")
    return f"osv-scanner_{system}_{architecture}", f"{system}_{architecture}"


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _verify_version(executable: Path, tool: str, version: str) -> str:
    result = subprocess.run([str(executable), "--version"], check=False, capture_output=True, text=True)
    reported = (result.stdout + result.stderr).strip()
    if result.returncode or re.search(rf"(?<![0-9]){re.escape(version)}(?![0-9])", reported) is None:
        _fail(f"expected {tool} {version}, got: {reported or result.returncode}")
    return reported


def _install_osv(root: Path, bin_dir: Path) -> None:
    identity = _versions()["osv-scanner"]
    version = identity["version"]
    requested = os.environ.get("OSV_SCANNER_VERSION")
    if requested and requested != version:
        _fail(f"requested OSV Scanner {requested} differs from catalogued version {version}")
    if SEMVER.fullmatch(version) is None:
        _fail("OSV_SCANNER_VERSION must be an exact x.y.z pin")
    target = _owned_target(root, "osv-scanner", version)
    asset, platform_key = _osv_asset()
    expected = identity["sha256"].get(platform_key)
    if not expected:
        _fail(f"scanner catalogue has no published SHA-256 for {platform_key}")
    release = os.environ.get(
        "TC_OSV_RELEASE_BASE_URL",
        f"https://github.com/google/osv-scanner/releases/download/v{version}",
    ).rstrip("/")
    binary = target / "osv-scanner"
    if binary.is_symlink():
        _fail(f"refusing to replace symlinked OSV Scanner cache executable: {binary}")
    cached_valid = binary.is_file() and not binary.is_symlink() and _sha256(binary) == expected
    if not cached_valid:
        with tempfile.TemporaryDirectory(prefix="tc-pipelines-osv-") as temporary:
            downloaded = Path(temporary) / asset
            _download(f"{release}/{asset}", downloaded)
            if _sha256(downloaded) != expected:
                _fail("downloaded OSV Scanner does not match the published SHA256SUMS digest")
            staged = target / f".osv-scanner-{os.getpid()}"
            staged.write_bytes(downloaded.read_bytes())
            staged.chmod(0o755)
            staged.replace(binary)
    else:
        # A complete downloaded cache may lose mode bits during restore/copy.
        binary.chmod(0o755)
    _verify_version(binary, "osv-scanner", version)
    _publish_executable(binary, bin_dir, "osv-scanner", root)
    print(f"Installed verified OSV Scanner {version} for {platform_key} in {binary}")


def _install_checkov(root: Path, bin_dir: Path) -> None:
    version, asteval_version = _checkov_version()
    requested = os.environ.get("CHECKOV_VERSION")
    if requested and requested != version:
        _fail(f"requested Checkov {requested} differs from locked version {version}")
    target = _owned_target(root, "checkov", version)
    environment = target / ".venv"
    if environment.is_symlink():
        _fail(f"refusing to use a symlinked Checkov environment: {environment}")
    uv_env = os.environ.copy()
    uv_env["UV_PROJECT_ENVIRONMENT"] = str(environment)
    result = subprocess.run(
        [
            "uv",
            "sync",
            "--project",
            str(CHECKOV_PROJECT),
            "--locked",
            "--python",
            "3.12",
            "--no-install-project",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=uv_env,
    )
    if result.returncode:
        _fail(f"isolated Checkov environment installation failed: {result.stderr.strip()}")
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    verify = subprocess.run(
        [
            str(python),
            "-c",
            "import importlib.metadata as m; "
            "assert m.version('checkov') == '" + version + "'; "
            "assert m.version('asteval') == '" + asteval_version + "'; "
            "assert not any(d.metadata['Name'].lower() in {'ecdsa', 'python-ecdsa'} "
            "for d in m.distributions())",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if verify.returncode:
        _fail(f"isolated Checkov dependencies failed security verification: {verify.stderr.strip()}")
    executable = environment / ("Scripts/checkov.exe" if os.name == "nt" else "bin/checkov")
    _verify_version(executable, "checkov", version)
    _publish_executable(executable, bin_dir, "checkov", root)
    print(f"Installed isolated Checkov {version} with asteval {asteval_version} in {environment}")


def main() -> int:
    install_osv = os.environ.get("INSTALL_OSV_SCANNER", "false") == "true"
    install_checkov = os.environ.get("INSTALL_CHECKOV_SCANNER", "false") == "true"
    if not install_osv and not install_checkov:
        print("No security scanners requested")
        return 0
    try:
        root, bin_dir = _scanner_root()
        lock = _cache_lock(root)
        try:
            if install_osv:
                _install_osv(root, bin_dir)
            if install_checkov:
                _install_checkov(root, bin_dir)
            _register_path(bin_dir)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()
        print(f"Scanner executables are available in {bin_dir}")
    except (OSError, ProvisionError) as error:
        print(f"scanner provisioning failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
