#!/usr/bin/env bash
# Local and hosted callers use the same implementation and pass environment
# adapters explicitly. No GitHub-only variables are required by the provisioner.
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python3 "$script_dir/provision_scanners.py" "$@"
