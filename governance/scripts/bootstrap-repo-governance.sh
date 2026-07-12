#!/usr/bin/env bash
# bootstrap-repo-governance.sh — one-command governance onboarding for a
# three-cubes repo.
#
# Given a repo, this sets the standard repo variables, wires the standard
# secrets from Azure Key Vault, applies the canonical branch ruleset (the
# contract: the fitness catalogue's required checks — Quality gate + no-attribution
# — plus code-owner review + thread resolution), installs the pre-commit hook
# config + CODEOWNERS + dependabot.yml +
# .gitignore from the template repo, distributes the agent-affordance + harness
# payload (rendered skeletons + sonar-sqaa hook + safe-commit/preflight), RENDERS
# the quality-gate wiring (pyproject [tool.tc_fitness] + ci.yml + auto-merge.yml +
# Makefile + .secrets.baseline + CORE catalogue + repo-local git-hooks), and
# `--verify`s that the applied ruleset's required contexts match the jobs ci.yml
# emits — so a bootstrapped repo's `main` ruleset never requires a check nothing
# it installed emits.
#
# Precedence note: GitHub resolves variables/secrets repo-over-org. The
# org-level AZURE_*/SONAR_TOKEN/CODECOV_TOKEN are the default; this script only
# sets a REPO-level override when it differs from the org value. For the common
# case the org inheritance is enough and this script writes no repo variables.
#
# Usage:
#   scripts/bootstrap-repo-governance.sh \
#     --repo three-cubes/<name> \
#     [--kv-name kv-tc-agents] \
#     [--fitness-tag vX.Y.Z] [--pipelines-tag vN] \
#     [--sonar | --no-sonar] [--with-release] \
#     [--sonar-project-key three-cubes_<name>] \
#     [--out-dir <dir>] [--verify] [--verify-only] \
#     [--no-secrets] [--no-ruleset] [--no-files] [--no-affordance] [--no-wiring] \
#     [--dry-run]
#
# Requires: gh (admin:org + repo + workflow scopes), az (logged in, read on the
# KV). No clone needed — templates (incl. the ruleset + skeletons) are fetched
# from three-cubes/tc-pipelines/governance/; pass --template-dir <clone> to use a
# local copy instead. When this script runs from inside a tc-pipelines checkout
# it sources governance/skeletons/ locally (no network) for the affordance +
# quality-gate-wiring render.
#
# No live git: every section RENDERS/VERIFIES locally and PRINTS the fetch+commit
# sequence — it never pushes (subagent-orchestration: no live ops from a bootstrap).

set -euo pipefail

# ── defaults ─────────────────────────────────────────────────────────────────
REPO=""
KV_NAME="kv-tc-agents"
TEMPLATE_REPO="three-cubes/tc-pipelines"
TEMPLATE_DIR=""
DO_SECRETS=1
DO_RULESET=1
DO_FILES=1
DO_AFFORDANCE=1
DO_WIRING=1
DRY_RUN=0

# Quality-gate wiring knobs.
FITNESS_TAG="v0.12.0"        # pinned tc-fitness engine (ships ci_consumes_shared_gate)
PIPELINES_TAG="v1"           # pinned tc-pipelines reusables (floating major)
DO_SONAR=1                   # emit the SonarCloud jobs + require the Sonar contexts
DO_RELEASE=0                 # also render a release.yml caller
SONAR_PROJECT_KEY=""         # default derived from --repo
OUT_DIR=""                   # where wiring renders (default: a temp dir, reported)
DO_VERIFY=0                  # run --verify after rendering
VERIFY_ONLY=0                # verify an existing OUT_DIR, render nothing

# Canonical-homes line the affordance skeletons carry ({{CANONICAL_HOMES}}).
# shellcheck disable=SC2016  # literal backticks are intentional (markdown code spans, no expansion)
CANONICAL_HOMES='`tc-fitness` (gate engine) · `tc-pipelines` (reusable CI + governance templates)'

# The rendered affordance skeleton set (source name -> repo-root target).
AFFORDANCE_SKELETONS=(CLAUDE.md AGENTS.md CONTRIBUTING.md ETHOS.md RESOLVER.md SCORECARD.md)

# Canonical repo variables every governed repo carries. Pulled from the org (so
# this is a no-op when org inheritance already covers them).
STANDARD_VARS=(AZURE_CLIENT_ID AZURE_SUBSCRIPTION_ID AZURE_TENANT_ID)

# Canonical secrets wired from KV: secret-name -> kv-secret-name.
declare -a SECRET_MAP=(
  "SONAR_TOKEN:sonarcloud-ci-analysis-token"
  "CODECOV_TOKEN:codecov-upload-token"
)

# ── arg parse ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO="$2"; shift 2 ;;
    --kv-name) KV_NAME="$2"; shift 2 ;;
    --template-dir) TEMPLATE_DIR="$2"; shift 2 ;;
    --no-secrets) DO_SECRETS=0; shift ;;
    --no-ruleset) DO_RULESET=0; shift ;;
    --no-files) DO_FILES=0; shift ;;
    --no-affordance) DO_AFFORDANCE=0; shift ;;
    --no-wiring) DO_WIRING=0; shift ;;
    --fitness-tag) FITNESS_TAG="$2"; shift 2 ;;
    --pipelines-tag) PIPELINES_TAG="$2"; shift 2 ;;
    --sonar) DO_SONAR=1; shift ;;
    --no-sonar) DO_SONAR=0; shift ;;
    --with-release) DO_RELEASE=1; shift ;;
    --sonar-project-key) SONAR_PROJECT_KEY="$2"; shift 2 ;;
    --out-dir) OUT_DIR="$2"; shift 2 ;;
    --verify) DO_VERIFY=1; shift ;;
    --verify-only) VERIFY_ONLY=1; DO_VERIFY=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *)
      echo "fix: unknown flag '$1'" >&2
      echo "next: scripts/bootstrap-repo-governance.sh --help" >&2
      exit 2 ;;
  esac
done

if [[ -z "$REPO" ]]; then
  echo "fix: --repo three-cubes/<name> is required" >&2
  echo "next: scripts/bootstrap-repo-governance.sh --repo three-cubes/<name>" >&2
  exit 2
fi

# ── derived tokens ───────────────────────────────────────────────────────────
REPO_SLUG="${REPO##*/}"                       # <name> from three-cubes/<name>
: "${SONAR_PROJECT_KEY:=three-cubes_${REPO_SLUG}}"
FITNESS_FLOOR="${FITNESS_TAG#v}"              # engine_version_floor value (no leading v)
: "${OUT_DIR:=${TMPDIR:-/tmp}/tc-bootstrap-${REPO_SLUG}}"

run() {
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "DRY-RUN  $*"
  else
    "$@"
  fi
}

# Locate governance/skeletons/ — prefer --template-dir, else the tc-pipelines
# checkout this script lives in (governance/scripts/../skeletons), else empty
# (affordance section then prints the gh-api fetch sequence instead).
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
SKELETON_DIR=""
if [[ -n "$TEMPLATE_DIR" && -d "${TEMPLATE_DIR}/governance/skeletons" ]]; then
  SKELETON_DIR="${TEMPLATE_DIR}/governance/skeletons"
elif [[ -d "${SCRIPT_DIR}/../skeletons" ]]; then
  SKELETON_DIR="$(cd -- "${SCRIPT_DIR}/../skeletons" && pwd)"
fi

# The ONE token-substitution set. Every render (markdown skeletons + the
# quality-gate wiring templates) flows through this filter, so a token resolves
# identically everywhere and the render can never leave a `{{...}}` behind.
subst_tokens() {
  sed \
    -e "s|{{REPO}}|${REPO}|g" \
    -e "s|{{CANONICAL_HOMES}}|${CANONICAL_HOMES}|g" \
    -e "s|{{FITNESS_TAG}}|${FITNESS_TAG}|g" \
    -e "s|{{FITNESS_FLOOR}}|${FITNESS_FLOOR}|g" \
    -e "s|{{PIPELINES_TAG}}|${PIPELINES_TAG}|g" \
    -e "s|{{SONAR_PROJECT_KEY}}|${SONAR_PROJECT_KEY}|g"
}

# Render one skeleton to stdout: inline the banner INCLUDE, then resolve tokens.
# The bash twin of governance/skeletons/tests/test_render_skeletons.py — both do
# banner-inline + token substitution, so they can never drift.
render_skeleton() {
  local src="$1" banner="${SKELETON_DIR}/_canonical-standards-banner.md"
  awk -v banner="$banner" '
    /<!--[[:space:]]*INCLUDE:[[:space:]]*_canonical-standards-banner\.md[[:space:]]*-->/ {
      while ((getline line < banner) > 0) print line
      close(banner)
      next
    }
    { print }
  ' "${SKELETON_DIR}/${src}" | subst_tokens
}

# Render one quality-gate wiring template (`<name>.tmpl`) to a target path.
# ci.yml carries a SONAR-BLOCK the render KEEPS (--sonar) or STRIPS (--no-sonar),
# so the emitted jobs match the required ruleset contexts for the chosen mode.
render_wiring() {
  local src="$1" dest="$2"
  mkdir -p "$(dirname "$dest")"
  if [[ "$DO_SONAR" == "1" ]]; then
    sed -e '/# SONAR-BLOCK-START/d' -e '/# SONAR-BLOCK-END/d' "${SKELETON_DIR}/${src}" | subst_tokens > "$dest"
  else
    sed '/# SONAR-BLOCK-START/,/# SONAR-BLOCK-END/d' "${SKELETON_DIR}/${src}" | subst_tokens > "$dest"
  fi
}

# Render the canonical main ruleset to $2, trimming the two SonarCloud required
# contexts under --no-sonar so the required set matches what ci.yml emits.
render_ruleset() {
  local src="$1" dest="$2"
  mkdir -p "$(dirname "$dest")"
  if [[ "$DO_SONAR" == "1" ]]; then
    cp "$src" "$dest"
  else
    jq '(.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks)
        |= map(select(.context | test("SonarCloud") | not))' "$src" > "$dest"
  fi
}

# ── verify ───────────────────────────────────────────────────────────────────
# Assert the rendered tree in $OUT_DIR is internally consistent, so a bootstrapped
# repo is never blocked by a ruleset requiring a check nothing emits:
#   (a) every required-check CONTEXT in the applied ruleset is a job ci.yml emits
#       (or the SonarCloud app's own external check) — catches `Quality gate` vs
#       `CI gate` drift;
#   (b) .secrets.baseline exists (the pre-commit + gate secret-scan needs it);
#   (c) the pyproject fragment carries the engine pin + the CORE bindings.
# Externally-provided contexts (posted by an app, not a ci.yml job).
VERIFY_EXTERNAL_CONTEXTS=("SonarCloud Code Analysis")

run_verify() {
  local ruleset="${OUT_DIR}/.github/rulesets/main-product.json"
  local ci="${OUT_DIR}/.github/workflows/ci.yml"
  local pyproject="${OUT_DIR}/pyproject.tc_fitness.toml"
  local baseline="${OUT_DIR}/.secrets.baseline"
  local rc=0

  echo "-- verify (${OUT_DIR}) --"

  # (a) ruleset required contexts ⊆ ci.yml job names ∪ external app checks.
  if [[ -f "$ruleset" && -f "$ci" ]]; then
    local job_names contexts ctx matched ext
    job_names="$(sed -n 's/^    name: *//p' "$ci" | sed -e 's/^"//' -e 's/"$//')"
    contexts="$(jq -r '.rules[] | select(.type=="required_status_checks")
                       | .parameters.required_status_checks[].context' "$ruleset")"
    while IFS= read -r ctx; do
      [[ -z "$ctx" ]] && continue
      matched=0
      while IFS= read -r n; do [[ "$n" == "$ctx" ]] && matched=1; done <<< "$job_names"
      for ext in "${VERIFY_EXTERNAL_CONTEXTS[@]}"; do [[ "$ctx" == "$ext" ]] && matched=1; done
      if [[ "$matched" == "1" ]]; then
        echo "ok: required context '${ctx}' is emitted"
      else
        echo "FAIL: ruleset requires context '${ctx}' but ci.yml emits no job of that name" >&2
        echo "      fix: rename a ci.yml job to '${ctx}', OR fix the ruleset's required_status_checks" >&2
        echo "      (ci.yml job names: $(echo "$job_names" | paste -sd',' - | sed 's/,/, /g'))" >&2
        rc=1
      fi
    done <<< "$contexts"
  else
    echo "FAIL: cannot verify contexts — missing ${ruleset} or ${ci}" >&2
    echo "      next: run the render (drop --verify-only) so the tree exists first" >&2
    rc=1
  fi

  # (b) secrets baseline present.
  if [[ -f "$baseline" ]]; then
    echo "ok: .secrets.baseline present"
  else
    echo "FAIL: ${baseline} missing — the gate + pre-commit secret-scan needs it" >&2
    echo "      fix: detect-secrets scan > .secrets.baseline" >&2
    rc=1
  fi

  # (c) pyproject fragment carries the pin + the CORE bindings.
  if [[ -f "$pyproject" ]]; then
    if grep -q 'three-cubes-fitness @ git+' "$pyproject"; then
      echo "ok: pyproject carries the tc-fitness engine pin"
    else
      echo "FAIL: pyproject fragment has no 'three-cubes-fitness @ git+' pin" >&2
      rc=1
    fi
    local b miss=0
    for b in no_llm_attribution canonical_commit_identity engine_version_floor harness_canon_reference ci_consumes_shared_gate; do
      grep -q "core_checks.${b}" "$pyproject" || { echo "FAIL: pyproject fragment omits the CORE binding '${b}'" >&2; miss=1; }
    done
    [[ "$miss" == "0" ]] && echo "ok: pyproject binds the CORE checks (attribution + commit-identity + engine-floor + harness-canon + ci-consumes-shared-gate)"
    [[ "$miss" == "0" ]] || rc=1
  else
    echo "FAIL: ${pyproject} missing" >&2; rc=1
  fi

  if [[ "$rc" == "0" ]]; then
    echo "verify: PASS — ruleset contexts match ci.yml, baseline present, pyproject pinned + bound."
  else
    echo "verify: FAIL — see the FAIL lines above." >&2
  fi
  return "$rc"
}

# --verify-only: check an already-rendered $OUT_DIR and exit (no render, no live ops).
if [[ "$VERIFY_ONLY" == "1" ]]; then
  echo "== verify-only for ${REPO} (${OUT_DIR}) =="
  run_verify
  exit $?
fi

echo "== bootstrap-repo-governance for ${REPO} (dry-run=${DRY_RUN}) =="

# ── 1. repo variables (org-inheritance-aware) ───────────────────────────────
echo "-- variables --"
for v in "${STANDARD_VARS[@]}"; do
  org_val="$(gh api "orgs/three-cubes/actions/variables/${v}" --jq '.value' 2>/dev/null || true)"
  if [[ -n "$org_val" ]]; then
    echo "ok: ${v} inherited from org (repo override not written)"
  else
    echo "warn: ${v} not set org-level; set it manually or org-promote it" >&2
    echo "      next: gh variable set ${v} --org three-cubes --visibility all --body <value>" >&2
  fi
done

# ── 2. secrets from Key Vault ───────────────────────────────────────────────
if [[ "$DO_SECRETS" == "1" ]]; then
  echo "-- secrets (from ${KV_NAME}) --"
  for pair in "${SECRET_MAP[@]}"; do
    gh_name="${pair%%:*}"
    kv_name="${pair##*:}"
    if gh api "orgs/three-cubes/actions/secrets/${gh_name}" >/dev/null 2>&1; then
      echo "ok: ${gh_name} inherited from org (repo override not written)"
      continue
    fi
    val="$(az keyvault secret show --vault-name "${KV_NAME}" --name "${kv_name}" --query value -o tsv 2>/dev/null || true)"
    if [[ -z "$val" ]]; then
      echo "warn: KV secret '${kv_name}' not found in ${KV_NAME}; ${gh_name} NOT wired" >&2
      echo "      fix: create the KV secret (value from the owner / SonarCloud / Codecov), then re-run" >&2
      continue
    fi
    if [[ "$DRY_RUN" == "1" ]]; then
      echo "DRY-RUN  gh secret set ${gh_name} --repo ${REPO} --body <redacted from ${kv_name}>"
    else
      printf '%s' "$val" | gh secret set "${gh_name}" --repo "${REPO}" --body -
      echo "ok: ${gh_name} wired from ${kv_name}"
    fi
  done
fi

# ── 3. canonical branch ruleset ─────────────────────────────────────────────
if [[ "$DO_RULESET" == "1" ]]; then
  echo "-- ruleset (main) --"
  # Branch protection is enforced org-level by the four rulesets committed in
  # tc-pipelines governance/rulesets/ (org-main-product / -core / -baseline +
  # org-branch-naming) — those are the primary enforcement. This per-repo apply
  # is a compatibility fallback that mirrors the product profile
  # (main-product.json) onto a repo the org rulesets do not yet cover.
  ruleset_json=""
  cleanup_ruleset=""
  if [[ -n "$TEMPLATE_DIR" && -f "${TEMPLATE_DIR}/governance/rulesets/main-product.json" ]]; then
    ruleset_json="${TEMPLATE_DIR}/governance/rulesets/main-product.json"
  elif [[ -f ".github/rulesets/main-product.json" ]]; then
    ruleset_json=".github/rulesets/main-product.json"
  else
    ruleset_json="$(mktemp)"
    cleanup_ruleset="$ruleset_json"
    gh api "repos/${TEMPLATE_REPO}/contents/governance/rulesets/main-product.json" \
      --jq '.content' 2>/dev/null | base64 -d > "$ruleset_json" || true
    if [[ ! -s "$ruleset_json" ]]; then
      echo "warn: could not fetch governance/rulesets/main-product.json from ${TEMPLATE_REPO}" >&2
      echo "      fix: pass --template-dir <tc-pipelines clone>, or --no-ruleset to skip" >&2
      rm -f "$cleanup_ruleset"; ruleset_json=""; cleanup_ruleset=""
    fi
  fi
  if [[ -n "$ruleset_json" ]]; then
    # Under --no-sonar, trim the two SonarCloud required contexts so the applied
    # ruleset requires only what the --no-sonar ci.yml emits (Quality gate +
    # no-attribution). The SAME render feeds --verify below.
    applied_ruleset="$(mktemp)"
    render_ruleset "$ruleset_json" "$applied_ruleset"
    existing="$(gh api "repos/${REPO}/rulesets" --jq '.[] | select(.name=="main" and .source_type=="Repository") | .id' 2>/dev/null || true)"
    if [[ -n "$existing" ]]; then
      run gh api "repos/${REPO}/rulesets/${existing}" --method DELETE
    fi
    run gh api "repos/${REPO}/rulesets" --method POST --input "$applied_ruleset"
    if [[ "$DO_SONAR" == "1" ]]; then
      echo "ok: applied main ruleset (required: Quality gate + no-attribution)"
    else
      echo "ok: applied main ruleset, SonarCloud contexts trimmed (required: Quality gate + no-attribution)"
    fi
    rm -f "$applied_ruleset"
    [[ -n "$cleanup_ruleset" ]] && rm -f "$cleanup_ruleset"
  fi
fi

# ── 4. governance files (CODEOWNERS, dependabot, pre-commit, .gitignore) ─────
if [[ "$DO_FILES" == "1" ]]; then
  echo "-- governance files --"
  echo "note: file installation opens a PR — this script prints the fetch+commit"
  echo "      sequence rather than pushing (no live git from the bootstrap)."
  cat <<EOF
  run (in a clone of ${REPO}, on a branch):
    gh api repos/${TEMPLATE_REPO}/contents/governance/CODEOWNERS \\
      --jq '.content' | base64 -d > .github/CODEOWNERS
    gh api repos/${TEMPLATE_REPO}/contents/governance/dependabot.yml \\
      --jq '.content' | base64 -d > .github/dependabot.yml
    gh api repos/${TEMPLATE_REPO}/contents/governance/pre-commit-config.yaml \\
      --jq '.content' | base64 -d > .pre-commit-config.yaml
    gh api repos/${TEMPLATE_REPO}/contents/governance/gitignore \\
      --jq '.content' | base64 -d > .gitignore
    # The pre-commit hooks point entry: at repo-local scripts/git-hooks/*, so copy
    # the hook scripts in (they used to reference governance/git-hooks/*, which only
    # exists inside tc-pipelines — a bootstrapped repo never had that path).
    mkdir -p scripts/git-hooks
    for h in commit-msg pre-push; do
      gh api repos/${TEMPLATE_REPO}/contents/governance/git-hooks/\$h \\
        --jq '.content' | base64 -d > scripts/git-hooks/\$h
      chmod +x scripts/git-hooks/\$h
    done
    uv run pre-commit install --hook-type commit-msg --hook-type pre-push
    uv run pre-commit install
    git add .github/CODEOWNERS .github/dependabot.yml .pre-commit-config.yaml .gitignore scripts/git-hooks
    git commit -m "chore(governance): bootstrap CODEOWNERS + dependabot + pre-commit + gitignore + git-hooks"
    gh pr create --fill
EOF
fi

# ── 5. agent-affordance + harness payload ────────────────────────────────────
# Renders the skeleton set with {{REPO}}/{{CANONICAL_HOMES}} resolved from
# --repo, installs the sonar-sqaa hook + jq-merges the settings.json PostToolUse
# block (idempotent — a re-run neither duplicates the block nor rewrites an
# unchanged render), and ships scripts/safe-commit.sh + scripts/preflight.sh.
# Same no-live-git design as section 4: it renders/verifies locally and prints
# the commit sequence rather than pushing. Toggle off with --no-affordance.
if [[ "$DO_AFFORDANCE" == "1" ]]; then
  echo "-- affordance + harness payload --"
  echo "note: skeletons rendered locally for ${REPO}; installation opens a PR (no live git)."

  if [[ -n "$SKELETON_DIR" ]]; then
    for s in "${AFFORDANCE_SKELETONS[@]}"; do
      rendered="$(render_skeleton "$s")"
      if printf '%s' "$rendered" | grep -q '{{'; then
        echo "warn: ${s} still has unresolved placeholders after render" >&2
      else
        echo "ok: render ${s} -> ${s} (placeholders resolved from --repo)"
      fi
    done
    echo "  (rendered from ${SKELETON_DIR}; sed resolves the REPO and CANONICAL_HOMES tokens)"
  else
    echo "note: no local governance/skeletons/ — fetch each skeleton from ${TEMPLATE_REPO} and render:"
    for s in "${AFFORDANCE_SKELETONS[@]}"; do
      echo "  gh api repos/${TEMPLATE_REPO}/contents/governance/skeletons/${s} --jq '.content' | base64 -d \\"
      echo "    | sed -e 's|{{REPO}}|${REPO}|g' > ${s}   # then inline the _canonical-standards-banner.md INCLUDE"
    done
  fi

  cat <<EOF
  run (in a clone of ${REPO}, on a branch):
    # 1. the six rendered affordance docs (CLAUDE/AGENTS/CONTRIBUTING/ETHOS/RESOLVER/SCORECARD) at repo root
    # 2. the sonar-sqaa PostToolUse hook
    mkdir -p .claude/hooks/sonar-sqaa/build-scripts
    gh api repos/${TEMPLATE_REPO}/contents/governance/skeletons/hooks/sonar-sqaa/build-scripts/posttool-sqaa.sh \\
      --jq '.content' | base64 -d > .claude/hooks/sonar-sqaa/build-scripts/posttool-sqaa.sh
    chmod +x .claude/hooks/sonar-sqaa/build-scripts/posttool-sqaa.sh
    # 3. idempotent jq-merge of the PostToolUse block into .claude/settings.json
    #    (deep-merge + unique — re-running does NOT duplicate the block or append)
    gh api repos/${TEMPLATE_REPO}/contents/governance/skeletons/claude-settings.postToolUse.json \\
      --jq '.content' | base64 -d > /tmp/postToolUse.json
    [ -f .claude/settings.json ] || echo '{}' > .claude/settings.json
    jq -s '
      .[0] as \$cur | .[1] as \$blk
      | \$cur
      | .hooks.PostToolUse = ((\$cur.hooks.PostToolUse // []) + \$blk.hooks.PostToolUse | unique)
    ' .claude/settings.json /tmp/postToolUse.json > .claude/settings.json.next
    mv .claude/settings.json.next .claude/settings.json
    # 4. the harness scripts
    mkdir -p scripts
    gh api repos/${TEMPLATE_REPO}/contents/governance/scripts/safe-commit.sh \\
      --jq '.content' | base64 -d > scripts/safe-commit.sh
    gh api repos/${TEMPLATE_REPO}/contents/governance/scripts/preflight.sh \\
      --jq '.content' | base64 -d > scripts/preflight.sh
    chmod +x scripts/safe-commit.sh scripts/preflight.sh
    git add CLAUDE.md AGENTS.md CONTRIBUTING.md ETHOS.md RESOLVER.md SCORECARD.md \\
      .claude/settings.json .claude/hooks/sonar-sqaa scripts/safe-commit.sh scripts/preflight.sh
    git commit -m "chore(governance): bootstrap agent-affordance + harness payload"
    gh pr create --fill
EOF
fi

# ── 6. quality-gate wiring ───────────────────────────────────────────────────
# The gap this closes: a governance-only bootstrap gave a repo a `main` ruleset
# requiring Quality gate + Sonar checks that NOTHING it installed emitted → every
# PR permanently blocked. This section RENDERS the wiring that emits those exact
# contexts — pyproject `[tool.tc_fitness]` + the CORE catalogue + ci.yml (the
# reusable caller + the `Quality gate`/`no-attribution`/`SonarCloud scan`
# aggregators) + auto-merge.yml + Makefile + .secrets.baseline + repo-local
# git-hooks — into $OUT_DIR, ready to copy into the repo. Same no-live-git design:
# it renders/verifies locally and prints the commit sequence. Toggle off with
# --no-wiring.
if [[ "$DO_WIRING" == "1" ]]; then
  echo "-- quality-gate wiring --"
  if [[ -z "$SKELETON_DIR" ]]; then
    echo "warn: no local governance/skeletons/ — pass --template-dir <tc-pipelines clone> to render the wiring" >&2
  else
    GOV_DIR="$(cd -- "${SKELETON_DIR}/.." && pwd)"
    RULESET_SRC="${GOV_DIR}/rulesets/main-product.json"
    mkdir -p "${OUT_DIR}/.github/workflows" "${OUT_DIR}/.github/rulesets" "${OUT_DIR}/scripts/checks" "${OUT_DIR}/scripts/git-hooks"

    # tc-fitness gate + CORE catalogue + the loop targets.
    render_wiring "pyproject.tc_fitness.toml.tmpl" "${OUT_DIR}/pyproject.tc_fitness.toml"
    render_wiring "_core_catalogue.py.tmpl"        "${OUT_DIR}/scripts/checks/_core_catalogue.py"
    render_wiring "Makefile.tmpl"                  "${OUT_DIR}/Makefile"

    # CI: the caller + the aggregators that carry the bare required contexts. The
    # SONAR-BLOCK is kept/stripped by render_wiring per --sonar/--no-sonar.
    render_wiring "workflows/ci.yml.tmpl"          "${OUT_DIR}/.github/workflows/ci.yml"
    render_wiring "workflows/auto-merge.yml.tmpl"  "${OUT_DIR}/.github/workflows/auto-merge.yml"

    # The ruleset that MATCHES the emitted contexts (sonar-trimmed under --no-sonar).
    render_ruleset "$RULESET_SRC" "${OUT_DIR}/.github/rulesets/main-product.json"

    # Secret baseline: prefer a fresh scan; fall back to the shipped empty baseline.
    if command -v detect-secrets >/dev/null 2>&1; then
      if ( cd "$OUT_DIR" && detect-secrets scan > .secrets.baseline ) 2>/dev/null; then
        echo "ok: .secrets.baseline generated by detect-secrets scan"
      else
        cp "${SKELETON_DIR}/secrets.baseline" "${OUT_DIR}/.secrets.baseline"
      fi
    else
      cp "${SKELETON_DIR}/secrets.baseline" "${OUT_DIR}/.secrets.baseline"
      echo "note: detect-secrets not installed — shipped the empty baseline; regenerate with 'detect-secrets scan'"
    fi

    # Repo-local git-hooks (the pre-commit entry: points at scripts/git-hooks/*).
    for h in commit-msg pre-push; do
      cp "${GOV_DIR}/git-hooks/${h}" "${OUT_DIR}/scripts/git-hooks/${h}"
      chmod +x "${OUT_DIR}/scripts/git-hooks/${h}"
    done
    cp "${GOV_DIR}/pre-commit-config.yaml" "${OUT_DIR}/.pre-commit-config.yaml"

    if [[ "$DO_SONAR" == "1" ]]; then
      render_wiring "sonar-project.properties.tmpl" "${OUT_DIR}/sonar-project.properties"
      echo "ok: rendered sonar-project.properties (projectKey ${SONAR_PROJECT_KEY})"
    fi

    if [[ "$DO_RELEASE" == "1" ]]; then
      cat > "${OUT_DIR}/.github/workflows/release.yml" <<EOF
---
name: "Release"
on:
  workflow_dispatch:
    inputs:
      version: { description: "CalVer tag (e.g. v2026.7.10)", required: true, type: string }
      changelog-label: { description: "CHANGELOG section label", required: true, type: string }
permissions:
  contents: write
jobs:
  release:
    uses: three-cubes/tc-pipelines/.github/workflows/release.yml@${PIPELINES_TAG}
    with:
      version: \${{ inputs.version }}
      changelog-label: \${{ inputs.changelog-label }}
    secrets:
      gh-token: \${{ secrets.GITHUB_TOKEN }}
EOF
      echo "ok: rendered .github/workflows/release.yml"
    fi

    # The affordance skeletons rendered to OUT_DIR too, so it is a complete drop-in.
    for s in "${AFFORDANCE_SKELETONS[@]}"; do
      render_skeleton "$s" > "${OUT_DIR}/${s}"
    done

    echo "ok: wiring rendered to ${OUT_DIR} (fitness-tag=${FITNESS_TAG} pipelines-tag=${PIPELINES_TAG} sonar=${DO_SONAR})"
    cat <<EOF
  run (in a clone of ${REPO}, on a branch):
    # copy the rendered wiring in, MERGE the pyproject fragment into pyproject.toml,
    # then run the gate once before you push.
    cp -r ${OUT_DIR}/.github ${OUT_DIR}/scripts ${OUT_DIR}/Makefile ${OUT_DIR}/.secrets.baseline \\
      ${OUT_DIR}/.pre-commit-config.yaml .
    cat ${OUT_DIR}/pyproject.tc_fitness.toml   # merge [dependency-groups] + [tool.tc_fitness] into pyproject.toml
$( [[ "$DO_SONAR" == "1" ]] && echo "    cp ${OUT_DIR}/sonar-project.properties ." )
    uv lock && uv sync --all-extras --all-groups
    uv run pre-commit install --hook-type commit-msg --hook-type pre-push && uv run pre-commit install
    make check           # the exact gate CI runs — get it green before push
    git add -A && git commit -m "chore(governance): wire the tc-fitness quality gate + CI"
    gh pr create --fill
EOF
  fi
fi

# ── 7. verify ────────────────────────────────────────────────────────────────
if [[ "$DO_VERIFY" == "1" ]]; then
  run_verify || {
    echo "next: fix the FAIL lines, re-run with --verify (or --verify-only --out-dir ${OUT_DIR})" >&2
    exit 1
  }
fi

# ── one-time human acts (not scriptable) ─────────────────────────────────────
# These four require a human with org-admin / cloud / third-party rights; the
# bootstrap can prepare everything else but must not (and cannot) perform them.
cat <<EOF

== one-time human checklist (org-admin / cloud / third-party) ==
  1. WIF + Key Vault identity (for CI to mint the App token + read secrets):
       az deployment group create -g RG-AGENTS-CORE \\
         --template-file infra/bicep/ci-deploy-identity.bicep \\
         --parameters repoOwner=three-cubes repoName=${REPO_SLUG} keyVaultName=${KV_NAME}
     then set repo vars AZURE_CLIENT_ID / AZURE_TENANT_ID / AZURE_SUBSCRIPTION_ID from its outputs.
  2. Maintainers team (owns the CODEOWNERS control plane):
       gh api -X PUT orgs/three-cubes/teams/maintainers/repos/${REPO} -f permission=push
     and confirm .github/CODEOWNERS routes control-plane paths to @three-cubes/maintainers.
  3. GitHub App install (three-cubes-agent, so agents author PRs as the App):
       install/grant the App on ${REPO} (Settings → GitHub Apps) — a human act.
  4. SonarCloud project (only under --sonar):
       create project ${SONAR_PROJECT_KEY} in org three-cubes, enable the PR decoration,
       and confirm the SONAR_TOKEN secret resolves (org-inherited or repo-set).
  Also: add your maintainer email to [tool.tc_fitness.core_checks.canonical_commit_identity]
  allowed_emails, and (for autonomous merge) flip the main ruleset review count to 0 only
  AFTER the gate is proven green + deterministic (governance/gate-hardening.md).
EOF

echo "== done. Verify: gh api repos/${REPO}/rulesets ; gh secret list --repo ${REPO} =="
