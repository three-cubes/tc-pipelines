#!/usr/bin/env python3
"""Resolve the latest cloudflared release for a reviewed dependency PR."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from install import (
    CATALOGUE,
    DIGEST,
    InstallError,
    _binary_bytes,
    _request_bytes,
    _sha256,
)

LATEST_URL = "https://api.github.com/repos/cloudflare/cloudflared/releases/latest"
ASSETS = {
    "linux-amd64": ("cloudflared-linux-amd64", False),
    "linux-arm64": ("cloudflared-linux-arm64", False),
    "darwin-amd64": ("cloudflared-darwin-amd64.tgz", True),
    "darwin-arm64": ("cloudflared-darwin-arm64.tgz", True),
}


def resolve_latest() -> dict[str, object]:
    request = Request(
        LATEST_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "three-cubes-tc-pipelines",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urlopen(request, timeout=30) as response:  # nosec B310 -- fixed official URL
        document = json.loads(response.read(4 * 1024 * 1024))
    version = document.get("tag_name")
    if (
        not isinstance(version, str)
        or re.fullmatch(r"[0-9]+(?:\.[0-9]+){2}", version) is None
        or document.get("draft") is not False
        or document.get("prerelease") is not False
    ):
        raise InstallError("latest release is not a stable semantic version")
    release_assets = {
        item.get("name"): item
        for item in document.get("assets", [])
        if isinstance(item, dict)
    }
    result_assets: dict[str, object] = {}
    for platform_key, (name, archived) in ASSETS.items():
        item = release_assets.get(name)
        if (
            not isinstance(item, dict)
            or DIGEST.fullmatch(str(item.get("digest", ""))) is None
        ):
            raise InstallError(f"latest release has no published digest for {name}")
        url = f"https://github.com/cloudflare/cloudflared/releases/download/{version}/{name}"
        if item.get("browser_download_url") != url:
            raise InstallError(f"latest release URL is not canonical for {name}")
        expected = str(item["digest"])
        download = _request_bytes(url)
        observed = f"sha256:{_sha256(download)}"
        if observed != expected:
            raise InstallError(f"published digest does not match {name}")
        result_assets[platform_key] = {
            "name": name,
            "archived": archived,
            "asset_sha256": expected,
            "executable_sha256": f"sha256:{_sha256(_binary_bytes(download, archived))}",
        }
    return {
        "schema_version": "tc.cloudflared.release.v1",
        "version": version,
        "source": f"https://github.com/cloudflare/cloudflared/releases/tag/{version}",
        "assets": result_assets,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalogue", type=Path, default=CATALOGUE)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        proposed = json.dumps(resolve_latest(), indent=2, sort_keys=True) + "\n"
        if args.check:
            if json.loads(args.catalogue.read_text()) != json.loads(proposed):
                print("cloudflared catalogue is not current", file=sys.stderr)
                return 1
        else:
            sys.stdout.write(proposed)
        return 0
    except (
        InstallError,
        HTTPError,
        URLError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(f"update-cloudflared-catalogue: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
