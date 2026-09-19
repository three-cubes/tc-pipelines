"""Install the reviewed cloudflared release and verify the executable identity."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

CATALOGUE = Path(__file__).with_name("release-catalogue.json")
OFFICIAL_BASE = "https://github.com/cloudflare/cloudflared/releases/download"
VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){2}")
DIGEST = re.compile(r"sha256:([0-9a-f]{64})")
PLATFORMS = {
    ("linux", "x86_64"): "linux-amd64",
    ("linux", "amd64"): "linux-amd64",
    ("linux", "aarch64"): "linux-arm64",
    ("linux", "arm64"): "linux-arm64",
    ("darwin", "x86_64"): "darwin-amd64",
    ("darwin", "amd64"): "darwin-amd64",
    ("darwin", "arm64"): "darwin-arm64",
    ("darwin", "aarch64"): "darwin-arm64",
}
MAX_ASSET_BYTES = 128 * 1024 * 1024


class InstallError(RuntimeError):
    """A bounded, operator-actionable installation failure."""


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _request_bytes(url: str) -> bytes:
    parsed = urlparse(url)
    loopback = parsed.scheme == "http" and parsed.hostname in {
        "127.0.0.1",
        "::1",
        "localhost",
    }
    if parsed.scheme != "https" and not loopback:
        raise InstallError("download URL must use HTTPS or loopback HTTP")
    request = Request(url, headers={"User-Agent": "three-cubes-tc-pipelines"})
    with urlopen(request, timeout=30) as response:  # nosec B310 -- scheme constrained above
        declared = response.headers.get("Content-Length")
        if declared is not None and int(declared) > MAX_ASSET_BYTES:
            raise InstallError("download exceeds the asset size limit")
        body = response.read(MAX_ASSET_BYTES + 1)
    if len(body) > MAX_ASSET_BYTES:
        raise InstallError("download exceeds the asset size limit")
    return body


def _read_catalogue(path: Path, platform_key: str) -> tuple[str, dict[str, object]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallError("release catalogue is not valid JSON") from exc
    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "version",
        "source",
        "assets",
    }:
        raise InstallError("release catalogue has an invalid schema")
    version = document["version"]
    if (
        document["schema_version"] != "tc.cloudflared.release.v1"
        or not isinstance(version, str)
        or VERSION.fullmatch(version) is None
    ):
        raise InstallError("release catalogue version is invalid")
    expected_source = (
        f"https://github.com/cloudflare/cloudflared/releases/tag/{version}"
    )
    if document["source"] != expected_source:
        raise InstallError("release catalogue source does not bind the version")
    assets = document["assets"]
    if (
        not isinstance(assets, dict)
        or platform_key not in assets
        or not isinstance(assets[platform_key], dict)
    ):
        raise InstallError(f"release catalogue has no {platform_key} asset")
    asset = assets[platform_key]
    if set(asset) != {"name", "archived", "asset_sha256", "executable_sha256"}:
        raise InstallError("release catalogue asset has an invalid schema")
    if (
        not isinstance(asset["name"], str)
        or not asset["name"].startswith("cloudflared-")
        or "/" in asset["name"]
    ):
        raise InstallError("release catalogue asset name is invalid")
    if not isinstance(asset["archived"], bool):
        raise InstallError("release catalogue archive flag is invalid")
    for field in ("asset_sha256", "executable_sha256"):
        if not isinstance(asset[field], str) or DIGEST.fullmatch(asset[field]) is None:
            raise InstallError(f"release catalogue {field} is invalid")
    return version, asset


def _binary_bytes(download: bytes, archived: bool) -> bytes:
    if not archived:
        return download
    try:
        with tarfile.open(fileobj=io.BytesIO(download), mode="r:gz") as archive:
            members = [
                member
                for member in archive.getmembers()
                if member.name in {"cloudflared", "./cloudflared"}
                and member.isfile()
                and not member.issym()
                and not member.islnk()
            ]
            if len(members) != 1:
                raise InstallError(
                    "cloudflared archive must contain one regular binary"
                )
            handle = archive.extractfile(members[0])
            if handle is None:
                raise InstallError("cloudflared archive binary cannot be read")
            binary = handle.read(MAX_ASSET_BYTES + 1)
    except (tarfile.TarError, OSError) as exc:
        raise InstallError("cloudflared archive is invalid") from exc
    if not binary or len(binary) > MAX_ASSET_BYTES:
        raise InstallError("cloudflared archive binary has an invalid size")
    return binary


def _verify_version(binary: Path, version: str) -> None:
    try:
        result = subprocess.run(
            [str(binary), "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env={"PATH": os.environ.get("PATH", os.defpath), "LANG": "C"},
        )
    except subprocess.TimeoutExpired as exc:
        raise InstallError("cloudflared --version exceeded 5 seconds") from exc
    first_line = result.stdout.splitlines()[0] if result.stdout.splitlines() else ""
    if (
        result.returncode != 0
        or re.match(rf"^cloudflared version {re.escape(version)}(?:\s|$)", first_line)
        is None
    ):
        raise InstallError(f"cloudflared reported version does not match {version}")


def install(args: argparse.Namespace) -> tuple[str, str, str, Path]:
    platform_key = PLATFORMS.get((args.system.lower(), args.machine.lower()))
    if platform_key is None:
        raise InstallError(f"unsupported runner platform: {args.system}/{args.machine}")
    version, asset = _read_catalogue(args.catalogue, platform_key)
    base = args.download_base_url.rstrip("/")
    if args.catalogue.resolve() == CATALOGUE.resolve() and base != OFFICIAL_BASE:
        raise InstallError("reviewed catalogue must use the official download origin")
    if base == OFFICIAL_BASE:
        url = f"{base}/{version}/{asset['name']}"
    else:
        parsed = urlparse(base)
        if parsed.scheme != "http" or parsed.hostname not in {
            "127.0.0.1",
            "::1",
            "localhost",
        }:
            raise InstallError("test download origin must be loopback HTTP")
        url = f"{base}/{asset['name']}"
    download = _request_bytes(url)
    observed_asset = _sha256(download)
    expected_asset = DIGEST.fullmatch(str(asset["asset_sha256"])).group(1)  # type: ignore[union-attr]
    if observed_asset != expected_asset:
        raise InstallError(
            f"cloudflared asset digest mismatch: expected {expected_asset}, observed {observed_asset}"
        )
    binary_bytes = _binary_bytes(download, bool(asset["archived"]))
    observed_executable = _sha256(binary_bytes)
    expected_executable = DIGEST.fullmatch(str(asset["executable_sha256"])).group(1)  # type: ignore[union-attr]
    if observed_executable != expected_executable:
        raise InstallError(
            f"cloudflared executable digest mismatch: expected {expected_executable}, observed {observed_executable}"
        )
    install_dir = args.install_dir.resolve()
    install_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    install_dir.chmod(0o700)
    destination = install_dir / "cloudflared"
    descriptor, name = tempfile.mkstemp(prefix=".cloudflared-", dir=install_dir)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(binary_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(
            stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH
        )
        _verify_version(temporary, version)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return version, expected_asset, expected_executable, destination


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalogue", type=Path, default=CATALOGUE)
    parser.add_argument("--download-base-url", default=OFFICIAL_BASE)
    parser.add_argument("--system", default=platform.system())
    parser.add_argument("--machine", default=platform.machine())
    parser.add_argument("--install-dir", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    try:
        args = _arguments()
        version, asset_digest, executable_digest, binary = install(args)
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(
                f"version={version}\nasset-digest=sha256:{asset_digest}\nexecutable-digest=sha256:{executable_digest}\npath={binary}\n"
            )
        print(
            f"Installed cloudflared {version} (executable sha256:{executable_digest})"
        )
        return 0
    except (InstallError, HTTPError, URLError, OSError, ValueError) as exc:
        print(f"setup-cloudflared: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
