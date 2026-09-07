#!/usr/bin/env bash
set -euo pipefail

status="$(git status --porcelain=v1 --untracked-files=all)"
if [[ -n "$status" ]]; then
  echo "::error::pre-evaluation-normalize changed the evaluated tree; commit the deterministic changes before CI." >&2
  printf '%s\n' "$status" >&2
  echo "fix: run the same normalizer locally, review and commit its output, then rerun the gate." >&2
  exit 1
fi

echo "evaluated-tree: clean; every evaluator will inspect the committed checkout tree."
