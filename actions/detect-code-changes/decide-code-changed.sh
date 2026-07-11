#!/usr/bin/env bash
# decide-code-changed.sh — the PURE change-gate decision for python-quality-gate.yml.
#
# Given a repo-relative changed-file list and a consumer-supplied extended-regex
# filter, answer whether the PR touched CODE (`true`) or is docs/config-only
# (`false`). The reusable gates the pytest shard fan-out on this answer: `false`
# skips the shards, `true` runs them.
#
# Contract (kept small so it is unit-testable off a real runner — see
# governance/scripts/tests/test_detect_code_changed.py):
#   --filter <ere>          extended-regex; ANY changed path matching it = code changed
#   --changed-files <path>  newline-delimited repo-relative paths
#
#   * empty filter            -> "true"  (detection DISABLED — backward-compatible
#                                         default; the shard matrix runs as today)
#   * no/empty changed list   -> "true"  (fail OPEN — never wrongly SKIP the tests)
#   * a path matches filter   -> "true"
#   * no path matches filter  -> "false" (docs/config-only — skip the shards)
#
# Prints exactly `true` or `false` to stdout and exits 0. Fail-open is deliberate:
# a detection glitch costs a redundant test run, never a skipped one.

set -euo pipefail

filter=""
changed_files=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --filter)
      filter="${2-}"
      shift 2
      ;;
    --changed-files)
      changed_files="${2-}"
      shift 2
      ;;
    -h | --help)
      grep -E '^# ' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "decide-code-changed: unknown flag '$1'. fix: use --filter <ere> --changed-files <path>." >&2
      exit 2
      ;;
  esac
done

# Detection disabled (no filter) -> run everything. Backward-compatible default.
if [[ -z "$filter" ]]; then
  echo "true"
  exit 0
fi

# Ambiguity (no list, missing file, or empty file) -> fail OPEN to run everything.
if [[ -z "$changed_files" || ! -s "$changed_files" ]]; then
  echo "true"
  exit 0
fi

# Any changed path matching the code filter means code changed.
if grep -qE -- "$filter" "$changed_files"; then
  echo "true"
else
  echo "false"
fi
