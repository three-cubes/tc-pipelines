"""Contract and real-process tests for the pinned cloudflared installer."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTION = REPO_ROOT / "actions" / "setup-cloudflared" / "action.yml"
INSTALLER = REPO_ROOT / "actions" / "setup-cloudflared" / "install.py"
UPDATER = REPO_ROOT / "actions" / "setup-cloudflared" / "update_catalogue.py"
CATALOGUE = REPO_ROOT / "actions" / "setup-cloudflared" / "release-catalogue.json"


class _AssetServer(ThreadingHTTPServer):
    asset: bytes


class _AssetHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        server = self.server
        assert isinstance(server, _AssetServer)
        if self.path == "/cloudflared-linux-amd64":
            self.send_response(200)
            self.send_header("Content-Length", str(len(server.asset)))
            self.end_headers()
            self.wfile.write(server.asset)
            return
        self.send_error(404)

    def log_message(self, _format: str, *_args: object) -> None:
        return


@pytest.fixture
def asset_server():
    server = _AssetServer(("127.0.0.1", 0), _AssetHandler)
    server.asset = (
        b"#!/bin/sh\n"
        b'[ -z "${INSTALLER_AMBIENT_SECRET:-}" ] || exit 99\n'
        b"echo 'cloudflared version 2026.8.3 (built fixture)'\n"
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def _catalogue(tmp_path: Path, server: _AssetServer, **updates: str) -> Path:
    digest = hashlib.sha256(server.asset).hexdigest()
    asset = {
        "name": "cloudflared-linux-amd64",
        "archived": False,
        "asset_sha256": f"sha256:{digest}",
        "executable_sha256": f"sha256:{digest}",
    }
    asset.update(updates)
    document = {
        "schema_version": "tc.cloudflared.release.v1",
        "version": "2026.8.3",
        "source": "https://github.com/cloudflare/cloudflared/releases/tag/2026.8.3",
        "assets": {"linux-amd64": asset},
    }
    path = tmp_path / "catalogue.json"
    path.write_text(json.dumps(document))
    return path


def _run_installer(tmp_path: Path, server: _AssetServer, catalogue: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["INSTALLER_AMBIENT_SECRET"] = "fixture-must-not-leak"  # pragma: allowlist secret
    return subprocess.run(
        [
            sys.executable,
            str(INSTALLER),
            "--catalogue",
            str(catalogue),
            "--download-base-url",
            f"http://127.0.0.1:{server.server_port}",
            "--system",
            "linux",
            "--machine",
            "x86_64",
            "--install-dir",
            str(tmp_path / "bin"),
            "--github-output",
            str(tmp_path / "github-output"),
        ],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )


def test_installs_only_catalogued_release_and_verifies_both_digests_and_version(
    tmp_path: Path, asset_server: _AssetServer
) -> None:
    catalogue = _catalogue(tmp_path, asset_server)
    result = _run_installer(tmp_path, asset_server, catalogue)
    assert result.returncode == 0, result.stderr
    installed = tmp_path / "bin" / "cloudflared"
    observed = hashlib.sha256(asset_server.asset).hexdigest()
    assert installed.read_bytes() == asset_server.asset
    assert installed.stat().st_mode & 0o777 == 0o755
    outputs = (tmp_path / "github-output").read_text()
    assert "version=2026.8.3\n" in outputs
    assert f"asset-digest=sha256:{observed}\n" in outputs
    assert f"executable-digest=sha256:{observed}\n" in outputs
    assert f"path={installed}\n" in outputs


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("asset_sha256", "asset digest mismatch"),
        ("executable_sha256", "executable digest mismatch"),
    ],
)
def test_rejects_each_digest_mismatch(
    tmp_path: Path, asset_server: _AssetServer, field: str, message: str
) -> None:
    catalogue = _catalogue(tmp_path, asset_server, **{field: "sha256:" + "0" * 64})
    result = _run_installer(tmp_path, asset_server, catalogue)
    assert result.returncode != 0
    assert message in result.stderr.lower()
    assert not (tmp_path / "bin" / "cloudflared").exists()


def test_rejects_executable_reporting_another_version(tmp_path: Path, asset_server: _AssetServer) -> None:
    asset_server.asset = b"#!/bin/sh\necho 'cloudflared version 2026.8.2'\n"
    result = _run_installer(tmp_path, asset_server, _catalogue(tmp_path, asset_server))
    assert result.returncode != 0
    assert "reported version" in result.stderr.lower()
    assert not (tmp_path / "bin" / "cloudflared").exists()


def test_reviewed_catalogue_pins_current_release_and_all_supported_platforms() -> None:
    document = json.loads(CATALOGUE.read_text())
    assert document["version"] == "2026.8.3"
    assert document["source"] == ("https://github.com/cloudflare/cloudflared/releases/tag/2026.8.3")
    assert set(document["assets"]) == {
        "darwin-amd64",
        "darwin-arm64",
        "linux-amd64",
        "linux-arm64",
    }
    for asset in document["assets"].values():
        assert len(asset["asset_sha256"]) == 71
        assert len(asset["executable_sha256"]) == 71


def test_rejects_catalogue_source_that_does_not_bind_the_version(
    tmp_path: Path, asset_server: _AssetServer
) -> None:
    catalogue = _catalogue(tmp_path, asset_server)
    document = json.loads(catalogue.read_text())
    document["source"] = "https://github.com/cloudflare/cloudflared/releases/tag/2026.8.2"
    catalogue.write_text(json.dumps(document))

    result = _run_installer(tmp_path, asset_server, catalogue)

    assert result.returncode != 0
    assert "catalogue source" in result.stderr.lower()
    assert not (tmp_path / "bin" / "cloudflared").exists()


def test_latest_resolution_is_separate_dependency_check_not_setup_action() -> None:
    document = yaml.safe_load(ACTION.read_text())
    assert set(document["outputs"]) == {
        "version",
        "asset-digest",
        "executable-digest",
        "path",
    }
    assert "releases/latest" not in document["runs"]["steps"][0]["run"]
    assert "release-catalogue.json" in INSTALLER.read_text()
    assert "releases/latest" in UPDATER.read_text()
