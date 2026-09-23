#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
registry_path="${TC_WORKSPACE_CLEANUP_REGISTRY:-${HOME}/.config/tc-pipelines/workspace-cleanup.json}"
launch_agents="${HOME}/Library/LaunchAgents"
log_dir="${HOME}/Library/Logs/tc-pipelines"
label="com.three-cubes.tc-pipelines.workspace-cleanup"
template="${repo_root}/governance/workspace/${label}.plist"
target="${launch_agents}/${label}.plist"

if [[ ! -f "${registry_path}" ]]; then
  printf 'registry does not exist: %s\n' "${registry_path}" >&2
  printf 'copy governance/workspace/local-workspace-cleanup.example.json and edit exact paths first.\n' >&2
  exit 2
fi
python3_path="$(command -v python3 || true)"
git_path="$(command -v git || true)"
gh_path="$(command -v gh || true)"
lsof_path="$(command -v lsof || true)"
for required in python3_path git_path gh_path lsof_path; do
  value="${!required}"
  if [[ -z "${value}" || "${value}" != /* || ! -x "${value}" ]]; then
    printf 'required executable is unavailable: %s\n' "${required}" >&2
    exit 2
  fi
done
mkdir -p "${launch_agents}" "${log_dir}"
"${python3_path}" - "${template}" "${target}" "${repo_root}" "${registry_path}" "${log_dir}" "${python3_path}" "${git_path}" "${gh_path}" "${lsof_path}" <<'PY'
import json
import plistlib
import sys
from pathlib import Path

template, target, repo_root, registry, log_dir = map(Path, sys.argv[1:6])
python3_path, git_path, gh_path, lsof_path = map(Path, sys.argv[6:])
try:
    payload = json.loads(registry.read_text(encoding="utf-8"))
    repositories = payload.get("repositories") if isinstance(payload, dict) else None
    if not isinstance(repositories, list) or not repositories or any(
        not isinstance(value, str) or not Path(value).expanduser().is_absolute() for value in repositories
    ):
        raise ValueError("registry repositories must contain at least one absolute path")
    document = plistlib.loads(template.read_bytes())
except (OSError, json.JSONDecodeError, plistlib.InvalidFileException, ValueError) as exc:
    raise SystemExit(f"cannot validate or render workspace cleanup configuration: {exc}") from exc

replacements = {
    "__REPO_ROOT__": str(repo_root),
    "__REGISTRY_PATH__": str(registry),
    "__LOG_DIR__": str(log_dir),
    "__PYTHON3__": str(python3_path),
    "__GIT_DIR__": str(git_path.parent),
    "__GH_DIR__": str(gh_path.parent),
    "__LSOF_DIR__": str(lsof_path.parent),
}

def render(value):
    if isinstance(value, str):
        for marker, replacement in replacements.items():
            value = value.replace(marker, replacement)
        return value
    if isinstance(value, list):
        return [render(item) for item in value]
    if isinstance(value, dict):
        return {key: render(item) for key, item in value.items()}
    return value

target.write_bytes(plistlib.dumps(render(document), sort_keys=False))
PY
launchctl bootout "gui/${UID}/${label}" 2>/dev/null || true
launchctl bootstrap "gui/${UID}" "${target}"
printf 'installed report-only workspace cleanup: %s\n' "${target}"
