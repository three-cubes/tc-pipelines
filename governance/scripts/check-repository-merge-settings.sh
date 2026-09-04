#!/usr/bin/env bash
# Verify the merge topology required by immutable internal self-pins.

set -euo pipefail

REPOSITORY="${1:-${GITHUB_REPOSITORY:-}}"
if [[ ! "$REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo "usage: $0 owner/repository" >&2
  exit 2
fi

actual="$({
  gh api "repos/${REPOSITORY}" \
    --jq '{allow_merge_commit,allow_squash_merge,allow_rebase_merge}'
} | tr -d '[:space:]')"
expected='{"allow_merge_commit":true,"allow_squash_merge":false,"allow_rebase_merge":false}'

if [[ "$actual" != "$expected" ]]; then
  echo "error: ${REPOSITORY} merge settings are ${actual}; expected ${expected}" >&2
  echo "fix: a repository administrator must enable merge commits and disable squash/rebase merges" >&2
  exit 1
fi

echo "ok: ${REPOSITORY} preserves merge ancestry"
