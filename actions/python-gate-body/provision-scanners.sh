#!/usr/bin/env bash
# Canonical hosted scanner provisioner.  Reusable gates and protected scanner
# qualification both call this file; neither is allowed to grow a second
# installer with subtly different version or integrity behaviour.
set -euo pipefail

install_osv_scanner() {
  [[ "${INSTALL_OSV_SCANNER:-false}" == "true" ]] || return 0
  [[ "${OSV_SCANNER_VERSION:-}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
    echo "::error::OSV scanner version must be an exact x.y.z pin" >&2
    exit 1
  }
  case "$(uname -m)" in
    x86_64) arch=amd64 ;;
    arm64|aarch64) arch=arm64 ;;
    *) echo "::error::unsupported OSV scanner architecture: $(uname -m)" >&2; exit 1 ;;
  esac
  os="$(uname -s | tr '[:upper:]' '[:lower:]')"
  asset="osv-scanner_${os}_${arch}"
  release="https://github.com/google/osv-scanner/releases/download/v${OSV_SCANNER_VERSION}"
  workdir="$(mktemp -d)"
  curl --fail --silent --show-error --location "$release/$asset" --output "$workdir/$asset"
  curl --fail --silent --show-error --location "$release/osv-scanner_SHA256SUMS" --output "$workdir/osv-scanner_SHA256SUMS"
  checksum_line="$(grep -E "[[:space:]]${asset}$" "$workdir/osv-scanner_SHA256SUMS")"
  [[ -n "$checksum_line" ]] || { echo "::error::release checksum does not list $asset" >&2; exit 1; }
  printf '%s\n' "$checksum_line" | (cd "$workdir" && shasum -a 256 --check -)
  install_dir="$RUNNER_TEMP/osv-scanner-${OSV_SCANNER_VERSION}"
  mkdir -p "$install_dir"
  install -m 0755 "$workdir/$asset" "$install_dir/osv-scanner"
  reported="$("$install_dir/osv-scanner" --version 2>&1)"
  expected_regex="(^|[^0-9])${OSV_SCANNER_VERSION//./\\.}([^0-9]|$)"
  [[ "$reported" =~ $expected_regex ]] || { echo "::error::expected osv-scanner $OSV_SCANNER_VERSION, got: $reported" >&2; exit 1; }
  echo "$install_dir" >> "$GITHUB_PATH"
  echo "Installed $reported from the verified v${OSV_SCANNER_VERSION} release asset."
  rm -rf "$workdir"
}

install_checkov() {
  [[ "${INSTALL_CHECKOV_SCANNER:-false}" == "true" ]] || return 0
  [[ "${CHECKOV_VERSION:-}" == "3.2.531" ]] || {
    echo "::error::Checkov qualification requires pinned version 3.2.531" >&2
    exit 1
  }
  tool_python="$(uv run --no-sync python -c 'import sys; print(sys.executable)')"
  uv pip install --python "$tool_python" "checkov==${CHECKOV_VERSION}"
  install_dir="$(dirname "$tool_python")"
  reported="$("$install_dir/checkov" --version 2>&1)"
  expected_regex="(^|[^0-9])${CHECKOV_VERSION//./\\.}([^0-9]|$)"
  [[ "$reported" =~ $expected_regex ]] || { echo "::error::expected checkov $CHECKOV_VERSION, got: $reported" >&2; exit 1; }
  echo "$install_dir" >> "$GITHUB_PATH"
  echo "Installed $reported into the locked Python environment."
}

install_osv_scanner
install_checkov
