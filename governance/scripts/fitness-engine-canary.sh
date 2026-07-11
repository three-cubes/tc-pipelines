#!/usr/bin/env bash
# fitness-engine-canary.sh — pre-release consumer canary for the fitness engine.
#
# The missing step between "engine PR merged" and "tag + fleet repin": run a
# REAL consumer's fitness gate against the CANDIDATE engine — a git ref to the
# fix branch/SHA, NEVER a tag — and block the release if that gate reds. The
# v0.13.0 empty-roots regression escaped because nothing ran a consumer's gate
# against the candidate before the tag went out; every consumer then repinned to
# a broken engine.
#
# Contract: the canary EXITS WITH THE CONSUMER GATE'S EXIT CODE. A red consumer
# gate (non-zero) → the canary exits non-zero → the release is blocked. A green
# gate (0) → the canary exits 0 → the tag + repin may proceed. It repins the
# consumer's three-cubes-fitness pin to the candidate ref, then runs the gate in
# the consumer dir; the gate command is injectable so the core is unit-testable
# without a live engine or network.
#
# Usage:
#   scripts/fitness-engine-canary.sh \
#     --candidate-ref <branch-or-sha> \
#     ( --consumer-dir <path> | --consumer-repo three-cubes/<name> [--consumer-ref <ref>] ) \
#     [--gate-cmd "uv run tc-fitness run"]
#
# Inputs:
#   --candidate-ref  git ref of the fitness-engine FIX (branch or SHA, not a tag)
#                    the consumer's pin is rewritten to. REQUIRED.
#   --consumer-dir   path to a consumer checkout carrying a three-cubes-fitness
#                    pin in pyproject.toml. Mutually exclusive with --consumer-repo.
#   --consumer-repo  three-cubes/<name> to clone when no --consumer-dir is given.
#   --consumer-ref   ref to check out for --consumer-repo (default: the repo default).
#   --gate-cmd       the consumer gate command run in the consumer dir
#                    (default: "uv run tc-fitness run"). Injectable so a test can
#                    stub it — the canary reflects whatever exit code it returns.
#
# Requires: git (only for --consumer-repo), plus whatever the gate command needs.
# No live release ops: this RUNS a gate and reports its verdict; it never tags,
# pushes, or repins the fleet.

set -euo pipefail

CANDIDATE_REF=""
CONSUMER_DIR=""
CONSUMER_REPO=""
CONSUMER_REF=""
GATE_CMD="uv run tc-fitness run"

# Canonical engine coordinates the consumer pin is rewritten against.
ENGINE_PKG="three-cubes-fitness"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --candidate-ref) CANDIDATE_REF="$2"; shift 2 ;;
    --consumer-dir) CONSUMER_DIR="$2"; shift 2 ;;
    --consumer-repo) CONSUMER_REPO="$2"; shift 2 ;;
    --consumer-ref) CONSUMER_REF="$2"; shift 2 ;;
    --gate-cmd) GATE_CMD="$2"; shift 2 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *)
      echo "fix: unknown flag '$1'" >&2
      echo "next: scripts/fitness-engine-canary.sh --help" >&2
      exit 2 ;;
  esac
done

if [[ -z "$CANDIDATE_REF" ]]; then
  echo "fix: --candidate-ref <branch-or-sha> is required (the engine FIX ref to canary, never a tag)" >&2
  echo "next: scripts/fitness-engine-canary.sh --candidate-ref <ref> --consumer-dir <path>" >&2
  exit 2
fi

# ── resolve the consumer checkout ────────────────────────────────────────────
if [[ -n "$CONSUMER_DIR" && -n "$CONSUMER_REPO" ]]; then
  echo "fix: pass either --consumer-dir OR --consumer-repo, not both" >&2
  echo "next: drop one of them" >&2
  exit 2
fi

if [[ -z "$CONSUMER_DIR" ]]; then
  if [[ -z "$CONSUMER_REPO" ]]; then
    echo "fix: name the consumer — pass --consumer-dir <path> or --consumer-repo three-cubes/<name>" >&2
    echo "next: scripts/fitness-engine-canary.sh --candidate-ref ${CANDIDATE_REF} --consumer-dir <path>" >&2
    exit 2
  fi
  CONSUMER_DIR="$(mktemp -d)"
  echo "-- cloning ${CONSUMER_REPO}${CONSUMER_REF:+@${CONSUMER_REF}} into ${CONSUMER_DIR} --" >&2
  if [[ -n "$CONSUMER_REF" ]]; then
    git clone --depth 1 --branch "$CONSUMER_REF" "https://github.com/${CONSUMER_REPO}.git" "$CONSUMER_DIR"
  else
    git clone --depth 1 "https://github.com/${CONSUMER_REPO}.git" "$CONSUMER_DIR"
  fi
fi

if [[ ! -d "$CONSUMER_DIR" ]]; then
  echo "fix: consumer dir '${CONSUMER_DIR}' does not exist" >&2
  echo "next: pass a real checkout via --consumer-dir, or --consumer-repo to clone one" >&2
  exit 2
fi

PYPROJECT="${CONSUMER_DIR}/pyproject.toml"
if [[ ! -f "$PYPROJECT" ]]; then
  echo "fix: no pyproject.toml in '${CONSUMER_DIR}' — the canary repins the engine there" >&2
  echo "next: point --consumer-dir at the consumer repo root (the dir holding pyproject.toml)" >&2
  exit 2
fi

if ! grep -q "$ENGINE_PKG" "$PYPROJECT"; then
  echo "fix: '${PYPROJECT}' carries no ${ENGINE_PKG} pin — nothing to repin to the candidate" >&2
  echo "next: canary a consumer that pins ${ENGINE_PKG} (the gate engine) in pyproject.toml" >&2
  exit 2
fi

# ── repin the consumer to the CANDIDATE engine ref ───────────────────────────
# Rewrite the ref that follows `tc-fitness(.git)@` to the candidate ref, in
# place (render-to-temp then move — portable across BSD/GNU sed). The candidate
# is a branch or SHA (no sed-special chars), so the `|`-delimited substitution
# is safe; the URL slashes are literal because `|` is the delimiter.
echo "-- repinning ${ENGINE_PKG} -> ${CANDIDATE_REF} in ${PYPROJECT} --" >&2
_repinned="$(mktemp)"
sed -E "s|(tc-fitness(\.git)?@)[^\"', ]+|\1${CANDIDATE_REF}|" "$PYPROJECT" > "$_repinned"
mv "$_repinned" "$PYPROJECT"

if ! grep -qF "@${CANDIDATE_REF}" "$PYPROJECT"; then
  echo "fix: repin did not take — '${PYPROJECT}' has no '@${CANDIDATE_REF}' after rewrite" >&2
  echo "next: check the ${ENGINE_PKG} pin format (expected '...tc-fitness.git@<ref>')" >&2
  exit 2
fi

# ── run the consumer gate against the candidate, and MIRROR its exit code ─────
# The whole point: the canary's verdict IS the consumer gate's verdict. Capture
# the code without `set -e` aborting, then exit with it. Never mask a red gate.
echo "-- running consumer gate against candidate ${CANDIDATE_REF}: ${GATE_CMD} --" >&2
rc=0
( cd "$CONSUMER_DIR" && bash -c "$GATE_CMD" ) || rc=$?

if [[ "$rc" -eq 0 ]]; then
  echo "canary: PASS — consumer gate is green against ${CANDIDATE_REF}; the release may proceed."
else
  echo "::error::canary: BLOCK — consumer gate RED (exit ${rc}) against candidate ${CANDIDATE_REF}." >&2
  echo "fix: do NOT tag/repin the fleet — resolve the consumer gate failure in the engine FIX first" >&2
  echo "next: re-run the canary against the corrected candidate ref" >&2
fi
exit "$rc"
