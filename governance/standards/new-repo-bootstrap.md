# New repo bootstrap

Bootstrap a new Three Cubes repo — or bring an existing one up to the org
standard — with the [`bootstrap-repo-governance.sh`](../scripts/bootstrap-repo-governance.sh)
onboarding script. One command sets the repo's variables + secrets, applies the
canonical org ruleset (product profile — see
[`CANONICAL-ORG-RULESET.md`](../CANONICAL-ORG-RULESET.md)), installs the governance
files, and renders the full
quality-gate baseline (the tc-fitness engine pin + `[tool.tc_fitness]` gate, the
CORE-check catalogue, the reusable CI + auto-merge callers, the Makefile, and the
secrets baseline) — so a bootstrapped repo's `main` ruleset only ever requires
checks the repo actually emits.

This is the union baseline already canonical across the fleet — a shared
baseline, not a new constraint set. It composes the org standards; where a
section is owned by another standard, this doc references it rather than
restating it.

## One-command bootstrap

Run the script against the target repo:

```bash
governance/scripts/bootstrap-repo-governance.sh --repo three-cubes/<name>
```

It runs seven sections in order, each independently toggleable via a flag:

1. **Repo variables** — reconcile `AZURE_CLIENT_ID` / `AZURE_SUBSCRIPTION_ID` /
   `AZURE_TENANT_ID` against the org, writing a repo-level override only where the
   org value is absent (org inheritance covers the common case). See
   [repo-governance-secret-wiring](repo-governance-secret-wiring.md).
2. **Secrets from Key Vault** — wire `SONAR_TOKEN` + `CODECOV_TOKEN` from
   `kv-tc-agents`, org-inheritance-aware (skips a repo override where the org
   secret already resolves).
3. **Branch ruleset (`main`)** — apply the canonical org ruleset (product
   profile); see [`CANONICAL-ORG-RULESET.md`](../CANONICAL-ORG-RULESET.md) for the
   required checks and review rules (single source of truth). Also blocks deletion
   + non-fast-forward.
4. **Governance files** — print the fetch+commit sequence for `CODEOWNERS`,
   `dependabot.yml`, the pre-commit config, `.gitignore`, and the repo-local
   `scripts/git-hooks/` (`commit-msg` + `pre-push`).
5. **Agent-affordance + harness payload** — render `CLAUDE.md`, `AGENTS.md`,
   `CONTRIBUTING.md`, `ETHOS.md`, `RESOLVER.md`, and `SCORECARD.md` with the repo
   tokens resolved, install the `sonar-sqaa` PostToolUse hook (idempotent
   `settings.json` merge), and ship `scripts/safe-commit.sh` + `scripts/preflight.sh`.
6. **Quality-gate wiring** — render the gate that emits the exact contexts the
   ruleset requires (see *What it renders*).
7. **Verify** — the internal-consistency self-check (see *`--verify` self-check*).

The script performs no live git: it renders and verifies locally and prints the
`run (in a clone …)` fetch+commit sequence for anything that lands in the repo —
it never pushes (per [subagent-orchestration](subagent-orchestration.md): no live
ops from a bootstrap). Run it, follow the printed sequences on a branch, and open
the PR as the three-cubes-agent App.

Templates — the ruleset and every skeleton — are fetched from
`three-cubes/tc-pipelines/governance/` over `gh api`; pass `--template-dir <clone>`
to render from a local checkout offline. When the script runs from inside a
tc-pipelines checkout it sources [`../skeletons/`](../skeletons/) locally.

### Flags

| Flag | Default | Effect |
|---|---|---|
| `--repo three-cubes/<name>` | required | The target repo. |
| `--kv-name <name>` | `kv-tc-agents` | Azure Key Vault the standard secrets are read from. |
| `--fitness-tag vX.Y.Z` | the pinned tc-fitness engine tag baked into the script | The immutable tc-fitness tag the rendered `pyproject` pins and the CI no-attribution leg uses. |
| `--pipelines-tag vN` | the pinned tc-pipelines reusables tag | The tc-pipelines reusable-workflow ref the rendered `ci.yml` / `auto-merge.yml` / `release.yml` call. |
| `--sonar` / `--no-sonar` | `--sonar` | Emit the SonarCloud jobs and require the two Sonar contexts, or trim both from `ci.yml` and the ruleset. |
| `--with-release` | off | Also render a `release.yml` caller. |
| `--sonar-project-key <key>` | `three-cubes_<slug>` | The SonarCloud `projectKey` rendered into `sonar-project.properties`. |
| `--out-dir <dir>` | a reported temp dir | Where the wiring + affordance payload renders. |
| `--verify` | off | Run the self-check after rendering. |
| `--verify-only` | off | Verify an already-rendered `--out-dir` and exit; render nothing, take no live action. |
| `--template-dir <clone>` | fetch over `gh api` | Render from a local tc-pipelines checkout instead of fetching templates. |
| `--no-secrets` | wire secrets | Skip the Key Vault secret wiring. |
| `--no-ruleset` | apply ruleset | Skip applying the `main` ruleset. |
| `--no-files` | print install sequence | Skip the governance-file install sequence. |
| `--no-affordance` | render payload | Skip the agent-affordance + harness payload. |
| `--no-wiring` | render wiring | Skip the quality-gate wiring render. |
| `--dry-run` | live | Print the live `gh` / `az` calls instead of executing them (local renders still run). |

### What it renders

Under `--out-dir` (a reported temp dir by default), the wiring section renders a
complete drop-in:

- **`pyproject.tc_fitness.toml`** — the engine pin (`three-cubes-fitness` as a
  dev-group dependency at a pinned tag), the `[tool.tc_fitness]` gate block, and
  one `[tool.tc_fitness.core_checks.*]` config block per bound CORE check. Merge
  each fragment into the repo's `pyproject.toml`.
- **`scripts/checks/_core_catalogue.py`** — the CORE-check catalogue binding the
  shared engine checks the repo inherits (attribution, commit-identity,
  engine-floor, harness-canon, ci-consumes-shared-gate), dispatched in-process as
  one gate step so the single `uv run tc-fitness run` contract holds.
- **`.github/workflows/ci.yml`** — the `python-quality-gate.yml` reusable caller
  plus the aggregator jobs (`Quality gate`, `no-attribution`, and under `--sonar`
  `SonarCloud scan`) that carry the *bare* required-status-check context names —
  a reusable call surfaces `<caller> / <reusable job>` checks, never a bare name,
  so these thin aggregators are what the ruleset resolves against.
- **`.github/workflows/auto-merge.yml`** — arms `gh pr merge --auto` on the green
  `Quality gate` fan-in check.
- **`.github/rulesets/main-product.json`** — the canonical org ruleset's
  **product** profile (new repos default to product); see
  [`CANONICAL-ORG-RULESET.md`](../CANONICAL-ORG-RULESET.md) for the required checks
  and review rules (single source of truth).
- **`Makefile`** — `make check` (`uv run tc-fitness run`, the exact gate CI runs)
  and `make setup` (install the local hooks).
- **`.secrets.baseline`** — a fresh `detect-secrets scan` when the tool is
  available, else the shipped empty baseline (secret hygiene is zero-tolerance).
- **`.pre-commit-config.yaml`** + **`scripts/git-hooks/{commit-msg,pre-push}`** —
  the local hook config and the repo-local hook scripts it points at.
- **`sonar-project.properties`** — only under `--sonar`; policy per
  [sonarqube-usage](sonarqube-usage.md).
- **`.github/workflows/release.yml`** — only under `--with-release`.
- The six affordance docs, so `--out-dir` is a self-contained drop-in.

### `--verify` self-check

Run `--verify` after the render — or `--verify-only --out-dir <dir>` against an
already-rendered tree — to assert the rendered tree is internally consistent, so
a bootstrapped repo is never blocked by a ruleset requiring a check nothing emits:

- **Ruleset contexts are a subset of the emitted jobs.** Every
  required-status-check context in the applied `main` ruleset is a job name
  `ci.yml` emits, or a known external app check (`SonarCloud Code Analysis`). This
  catches a `Quality gate`-vs-`CI gate` name drift before it reaches `main`.
- **Secrets baseline present.** `.secrets.baseline` exists — the pre-commit hook
  and the gate's secret-scan step both need it.
- **Pyproject pinned + bound.** The `pyproject` fragment carries the
  `three-cubes-fitness @ git+…` engine pin and every CORE binding
  (`no_llm_attribution`, `canonical_commit_identity`, `engine_version_floor`,
  `harness_canon_reference`, `ci_consumes_shared_gate`).

A failure prints its `fix:` / `next:` line and exits non-zero. The bootstrap
contract test
([`test_bootstrap_repo_governance.py`](../scripts/tests/test_bootstrap_repo_governance.py))
exercises the flags, the render, and this self-check end-to-end.

## Branch strategy

Trunk-based on `main`. The bootstrap applies the canonical org ruleset (product
profile); see [`CANONICAL-ORG-RULESET.md`](../CANONICAL-ORG-RULESET.md) for the
required checks and review rules (single source of truth). Ship one feature = one
branch = one PR authored by the three-cubes-agent App; `auto-merge.yml` merges on
green. See [development-workflow](development-workflow.md).

Cut releases the canonical way via [sdlc-release-workflow](sdlc-release-workflow.md);
render the `release.yml` caller with `--with-release`.

## The quality gate

The gate is the rendered `[tool.tc_fitness]` block, run by `uv run tc-fitness run`
both locally (`make check`) and in CI (the `python-quality-gate.yml` reusable) —
local == CI by construction, because both run the same command over the same
config. CORE governance checks are *inherited* from the shared tc-fitness engine
via the rendered `_core_catalogue.py` binding plus the `[tool.tc_fitness.core_checks.*]`
config blocks; the engine owns the check code, the repo owns only the config.

Add a repo-specific detector, or improve a shared one, per
[improving-fitness-gates](improving-fitness-gates.md) — converge *up* into
tc-fitness for anything shared across repos, and keep only a genuinely repo-local
concern in `scripts/checks/`. Keep the `pyproject.toml` gate block CODEOWNERS-gated
to `@three-cubes/maintainers` so the agent App can never widen the gate that gates
it. Contract-test any new interface per
[contract-test-patterns](contract-test-patterns.md).

## Local development gate

`make check` runs the exact gate CI runs. `make setup` installs the pre-commit
config: the `commit-msg` strip hook (rejects AI/LLM self-attribution before it is
authored — see [AUTONOMOUS-DELIVERY-STANDARD](../AUTONOMOUS-DELIVERY-STANDARD.md))
and the `pre-push` gate replay, so the fitness gate fires before the CI
round-trip rather than after it. Run `make check` green before every push.

## Dependencies

The rendered `.github/dependabot.yml` enforces a cooldown: never apply
package-manager updates until 7+ days post-release (semver-major: 14d); security
advisories bypass.

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

Secret hygiene is zero-tolerance: the rendered `.secrets.baseline` ships empty, so
any new finding gates the build; add to the baseline only with an audited reason
in the commit message. Runtime secrets are fetched from Azure Key Vault at deploy
time, never committed. The shared org secrets and the promotion path are canonical
in [repo-governance-secret-wiring](repo-governance-secret-wiring.md); the security
posture is in [security-framework](security-framework.md).

## One-time human acts

The script prints the four acts it cannot perform itself — each needs org-admin,
cloud, or third-party rights:

1. **WIF + Key Vault identity** — deploy the CI deploy-identity so CI can mint the
   App token and read secrets, then set the `AZURE_*` repo/org variables from its
   outputs.
2. **Maintainers team** — grant `@three-cubes/maintainers` on the repo and confirm
   `CODEOWNERS` routes the control-plane paths to it.
3. **GitHub App install** — install / grant the three-cubes-agent App on the repo
   so agents author PRs as the App.
4. **SonarCloud project** (only under `--sonar`) — create the project in org
   `three-cubes`, enable PR decoration, and confirm `SONAR_TOKEN` resolves.

Then add the maintainer's `<id>+<login>@users.noreply.github.com` to
`[tool.tc_fitness.core_checks.canonical_commit_identity]` `allowed_emails`, and
flip the ruleset's required review count to 0 for autonomous merge only *after*
the gate is proven green and deterministic — see
[gate-hardening](../gate-hardening.md) and [autonomous-loop](../autonomous-loop.md).

## Bootstrap checklist

For a new repo, in order:

- [ ] Run `bootstrap-repo-governance.sh --repo three-cubes/<name>` (add `--verify`).
- [ ] On a branch, follow each printed `run (in a clone …)` sequence: the
      governance files, the affordance + harness payload, and the quality-gate
      wiring (merge the `pyproject` fragments into `pyproject.toml`).
- [ ] Run `make check` green locally before the first push.
- [ ] Open the PR as the three-cubes-agent App and let the green gate merge it.
- [ ] Complete the four one-time human acts above.
- [ ] Add the maintainer identity to `canonical_commit_identity` `allowed_emails`
      before flipping the repo autonomous.

The bootstrap converges a new repo onto the shared baseline in one command; the
checklist is the human sequence around it, not a parallel set of rules.
