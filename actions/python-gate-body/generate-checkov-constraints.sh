#!/usr/bin/env bash
# Regenerate checkov-constraints.txt from scanner-versions.json (PLA-471).
#
# The compiled resolution of the catalogued Checkov, with the asteval override the
# provisioner applies, is written to this directory's checkov-constraints.txt and to
# the copy the tc-fitness wheel ships (when the monorepo layout is present), so the
# provisioner and `tc-fitness-install-checkov` install the same exact environment.
# A Checkov bump is: edit scanner-versions.json, run this script, review the diff, commit.
# The committed pins are preferences, so a rerun at the same Checkov changes nothing;
# set UPGRADE=1 to refresh the transitive pins as well.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
packaged="$here/../../../../assurance/fitness/src/tc_fitness/checkov-constraints.txt"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["checkov"]["version"])' "$here/scanner-versions.json")"
printf 'checkov==%s\n' "$version" >"$work/in.txt"
printf 'asteval>=1.0.9,<1.1\n' >"$work/overrides.txt"

grep -v '^#' "$here/checkov-constraints.txt" >"$work/pins.txt"

cat >"$work/out.txt" <<'HEADER'
# The complete Checkov tool environment: every distribution `uv tool install`
# may place beside checkov, pinned to an exact version (PLA-471). The provisioner
# and `tc-fitness-install-checkov` install with `--constraints` on this file; the
# provisioner then fails if the installed environment holds a distribution outside
# it or at another version.
# Generated: do not edit. When scanner-versions.json moves Checkov, run
#   bash execution/pipelines/actions/python-gate-body/generate-checkov-constraints.sh
# review the diff and commit both copies.
HEADER
uv pip compile "$work/in.txt" --overrides "$work/overrides.txt" --python-version 3.12 --universal \
  --no-header --no-annotate ${UPGRADE:+--upgrade} --output-file "$work/pins.txt" >/dev/null
cat "$work/pins.txt" >>"$work/out.txt"

cp "$work/out.txt" "$here/checkov-constraints.txt"
if [ -d "$(dirname "$packaged")" ]; then
  cp "$work/out.txt" "$packaged"
fi
