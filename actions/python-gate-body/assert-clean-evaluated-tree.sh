#!/usr/bin/env bash
set -euo pipefail

status="$(git status --porcelain=v1 --untracked-files=all)"
if [[ -n "$status" ]]; then
  echo "::error::pre-evaluation-normalize changed the candidate; evaluation withheld until those exact bytes are committed." >&2
  printf '%s\n' "$status" >&2
  echo "next: the unprivileged preparation producer must emit an identity-bound patch for trusted bot writeback." >&2
  exit 1
fi

echo "evaluated-tree: clean; every evaluator will inspect the committed checkout tree."
