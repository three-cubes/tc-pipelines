# New repo bootstrap

The canonical pattern for starting a new Three Cubes repo. Synthesised across
Three Cubes repos (e.g. kairix, a retrieval product, and an agent-infra repo)
after they moved to trunk-based development.

Use this as a checklist when seeding a new repo or when sanity-checking an
existing one against the org standard.

## Branch strategy

**Trunk-based on `main`.** No long-lived `develop` branch. Routine commits
go direct to `main` after `safe-commit.sh` / `make check` passes locally;
PRs only for release-stabilisation, large grouped reviews, or external
collaboration.

**Branch protection rule on `main`:**
- Require status check `CI gate` (or equivalent terminal gate name) to pass
- Require linear history (or signed merge commits)
- Restrict force-push
- No required PR review for solo work; add reviewer requirement once team
  size warrants it

**Release flow:**
- `release.yml` (workflow_dispatch) tags `main` HEAD with CalVer
  `vYYYY.M.D[.N]` and creates a GitHub Release whose body is read from
  the corresponding `CHANGELOG.md` section
- No `develop→main` PR ritual
- Alpha tags: `release-alpha.yml` cuts `vYYYY.M.D.aN` from `main` HEAD

## Repository defaults

```
.github/
  workflows/
    ci.yml              # quality gate (per-stage if Python-heavy, single-job if make-orchestrated)
    release.yml         # workflow_dispatch, tags + GitHub Release
    release-alpha.yml   # workflow_dispatch, cuts alpha tag from main
    dependabot.yml      # security-only by default; cooldown enforced
.architecture/
  baseline/             # grandfathered violations per fitness rule
scripts/
  checks/               # fitness function detectors (Python preferred)
  safe-commit.sh        # local pre-push gate; mirrors CI exactly
CHANGELOG.md            # release notes — release.yml reads sections by version
CLAUDE.md               # engineering standards (for human + agent collaborators)
README.md               # one-screen orientation per top-level dir
```

## Fitness functions (canonical set)

Mechanical, blocking checks. Each detector lives in `scripts/checks/`,
each has a baseline file at `.architecture/baseline/<rule>-files.txt`
that grandfathers existing violations. **Net-new violations block** at
local pre-commit, `safe-commit.sh` / `make check`, and CI Stage 0.

| ID | Rule | Source |
|---|---|---|
| F1 | No internal `@patch` / `monkeypatch.setattr` on first-party modules | kairix |
| F2 | No `monkeypatch.setenv` on project env vars | kairix |
| F3 | Per-line suppressions (`# noqa`, `# type: ignore`, `# nosec`, etc.) carry rationale | kairix |
| F5 | No internal-name imports in tests; inject Fakes via constructor | kairix |
| F6 | No `*_fn` / `*_loader` / `*_factory` test-only kwargs in production | kairix |
| F7 | Per-file coverage ≥ 90% (unit) | kairix |
| F8 | Every test carries a category marker (`unit` / `bdd` / `contract` / `integration` / etc.) | kairix |
| F10 | CI workflow silencers (`continue-on-error`) require rationale | kairix |
| F11 | Test skip mechanisms require rationale | kairix |
| F12 | Every BDD feature has a happy-path scenario | kairix |
| F13 | BDD scenarios reject implementation symbols | kairix |
| F15 | No logging of secret-named variables in plaintext | kairix |
| F16 | Cognitive complexity ≤ 15 per function | kairix |
| F17 | No string literal ≥10 chars duplicated ≥3 times | kairix |
| F18 | No commented-out code | kairix |
| F19 | Unused parameters must be `_`-prefixed | kairix |
| F20 | Empty function bodies require docstring or `# Intentionally empty —` | kairix |
| F21 | `scripts/checks/check_*.{py,sh}` failure output carries `fix:` / `next:` / `run:` markers | kairix |
| F22 | Repo paths follow per-tree naming conventions | kairix |
| F23 | Every top-level directory has a `README.md` orientation | kairix |
| F24 | No `from tests.*` imports in production code | kairix |
| F30 | Every CLI subcommand + MCP tool has an outcome test | kairix |
| F31 | No hardcoded `/Users/<dev>/` or `/home/<dev>/` paths | cross-repo |
| F32 | No real first / org names in test fixtures + reference data + docs | cross-repo |
| F33 | `# shellcheck disable=<rule>` directives require rationale | cross-repo |

**Repo-specific additions** — a repo may keep local checks that encode its
own domain concerns. Example: an agent-platform repo keeps these, which are
not relevant to product repos:

- `agent_bdd_scenarios_present` — every agent has a BDD spec
- `agent_grade_regression` — scorecard delta tracking
- `agent_memory_policy` — per-agent memory hygiene
- `constitution_enforcement_refs_valid` — constitution links resolve
- `no_cross_agent_memory_refs` — agents can't peek into each other's memory
- `imds_block_check` — Azure IMDS metadata endpoint hardening
- `llm_judge_affordance` — LLM-judge prompt format check
- `per_agent_secret_isolation` — per-agent secret scoping
- `token_logger_attribution_complete` — token-usage attribution complete

## Local development gate

Every repo ships `scripts/safe-commit.sh` (or equivalent `make check`)
that runs the same gates CI runs, in the same order:

```
ruff lint → ruff format → mypy --strict → pytest with --cov →
arch fitness (run-all.sh) → detect-secrets → confidential-pattern scan
```

The script writes commits only when **every** gate passes. Coverage
generation (F7/F9) runs locally so the per-file floor is enforced in
seconds, not minutes via CI.

Escape hatch for intermediate refactors: `KAIRIX_SKIP_COVERAGE=1`
(or similar repo-specific env var). CI still enforces the gate on push.

## Releases

- `CHANGELOG.md` carries one section per released version. The current
  `[Unreleased]` section becomes the next release's body.
- `release.yml` accepts `version` (e.g. `v2026.5.18`) and
  `changelog_label` (e.g. `2026.5.18`); the workflow tags `main` HEAD,
  pulls the named section out of `CHANGELOG.md`, and creates a GitHub
  Release with that body.
- Alpha cuts via `release-alpha.yml -f date_version=YYYY.M.D -f alpha_n=N`.
  Alpha tags trigger downstream Docker + PyPI publishes automatically.
- Release HITL: cutting tags + deploying to shared infra requires
  explicit per-action human authorisation.

## Dependencies

**Dependabot cooldown**: never apply package-manager updates until 7+
days post-release (semver-major: 14d). Security advisories bypass.
Configure in `.github/dependabot.yml`:

```yaml
updates:
  - package-ecosystem: "pip"  # or "npm", "uv", etc.
    schedule:
      interval: "weekly"
    cooldown:
      semver-minor-days: 7
      semver-major-days: 14
```

## Secrets

- `.secrets.baseline` (detect-secrets) checked in; pre-commit hook runs
  scan on every commit. Add to baseline only with an audited reason in
  the commit message.
- Runtime secrets fetched from Azure Key Vault via the
  `kairix.secrets` / equivalent module. Environment-set fallback for dev.
- Never log secret-named variables (F15 enforces this mechanically).

## CI → Azure OIDC

For workflows that need cloud access (e.g. fetching secrets from KV,
deploying to a VM):

1. Create an Azure AD App Registration `<repo>-ci-keyvault-reader` (or
   similar role-scoped name).
2. Add federated credentials trusting the repo:
   - `repo:<org>/<repo>:ref:refs/heads/main`
   - `repo:<org>/<repo>:pull_request`
3. Grant the SP minimum-required RBAC role on the target resource (e.g.
   `Key Vault Secrets User` on the KV).
4. Set GH repo variables: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`,
   `AZURE_SUBSCRIPTION_ID`, plus any resource name (e.g.
   `KAIRIX_KV_NAME`).
5. Workflow uses `azure/login@v2` with `permissions: id-token: write`.

No long-lived secrets stored in GitHub — federated identity covers the
auth path.

## Node 24 opt-in

Set `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"` at the workflow-level
`env:` block in every workflow. Suppresses the Node 20 deprecation
warning until `actions/setup-python@v6` and friends ship with Node 24
runtime support.

## Bootstrap checklist

For a new repo, in order:

- [ ] `git init`; default branch `main`; trunk-based
- [ ] `CLAUDE.md` with engineering standards
- [ ] `CHANGELOG.md` with `[Unreleased]` placeholder
- [ ] `scripts/safe-commit.sh` (or `make check` target) running the gate chain
- [ ] `scripts/checks/run-all.sh` invoking each fitness detector
- [ ] `.architecture/baseline/` directory created (empty if no offenders yet)
- [ ] `.github/workflows/{ci,release,release-alpha}.yml` from template
- [ ] `.github/dependabot.yml` with cooldown enforced
- [ ] `.secrets.baseline` initialised via `detect-secrets scan > .secrets.baseline`
- [ ] Branch protection on `main`: require `CI gate`, restrict force-push
- [ ] `docs/standards/` symlink or copy of the canonical-patterns set
- [ ] OIDC App Registration created if cloud access needed
- [ ] Per-language baselines configured (ruff, mypy, pytest, etc.)

This doc is the union baseline of engineering standards already canonical
across the fleet — treat it as the shared baseline, not a new constraint set.
