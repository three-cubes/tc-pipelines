# three-cubes/ci-workflows

Org-shared CI for three-cubes repositories — reusable workflows (`workflow_call`) and composite actions, so every repo's CI derives from one source instead of drifting copies. Part of [kairix#499](https://github.com/three-cubes/kairix/issues/499) Phase 4.

## Layout

```
actions/                 composite actions (shared steps)
  setup-uv-cached/        pinned uv + cached venv
.github/workflows/        reusable workflow_call workflows (added incrementally)
  python-quality-gate.yml the generic Python lint/type/security/test/coverage gate
```

## Principles

- **Config lives in GitHub org/repo variables + secrets, never hardcoded here or in consuming repos.** Reusable workflows and actions take config as `inputs`; consuming repos pass org/repo `vars`/`secrets` (e.g. `PRIVATE_INFRA_PATTERNS`, `SONAR_TOKEN`, coverage floors, image names). No git-excluded config files.
- **Pin everything.** Third-party actions pinned to a full commit SHA; consumers pin this repo's reusable workflows to a `@vN` tag so a change rolls out per-repo on the org dependency-cooldown cadence, not all at once.
- **Public, but secret-free.** This repo is public (consumed by public + private org repos); it contains zero credentials — those stay in org/repo secrets.

## Consuming

```yaml
# caller in a three-cubes repo:
jobs:
  quality:
    uses: three-cubes/ci-workflows/.github/workflows/python-quality-gate.yml@v1
    with:
      python-version: "3.12"
    secrets: inherit
```

## `python-quality-gate.yml` — reusable Python gate

The generic Python quality gate: the org-standard locked-uv install (the
`setup-uv-cached` composite — pinned `setup-uv` + cached `uv sync` + optional
`--require-hashes` CI tools) followed by lint / type / security / test / coverage
steps. Each step is opt-in via a `run-*` toggle so a repo enables exactly what it
runs. **Repo-specific steps stay in the caller** — taz keeps openclaw / llm-judge /
the fitness harness; kairix keeps arch-fitness / union-coverage / Docker. This
workflow is the shared *middle*, not the whole gate.

### Capability toggles (`run-*`)

| Input | Default | Gates |
|---|---|---|
| `run-shellcheck` | `true` | install shellcheck + lint discovered `*.sh` |
| `run-ruff-lint` | `true` | `uv run ruff check` (blocking) |
| `run-ruff-format-check` | `true` | `uv run ruff format --check` (non-blocking, `|| true`) |
| `run-bandit` | `true` | `uv run bandit -r` SAST |
| `run-compileall` | `true` | `uv run python -m compileall` syntax gate |
| `run-mypy` | `false` | `uv run mypy` (taz: off; kairix: on) |
| `run-pytest` | `true` | pytest + branch coverage + optional XML normalise |
| `run-node` | `false` | pnpm/TS half: setup-node + pnpm install + TS coverage |
| `run-detect-secrets` | `true` | detect-secrets changed-file scan |

### Toolchain + install inputs

| Input | Default | Purpose |
|---|---|---|
| `python-version` | `"3.12"` | Python uv resolves against |
| `uv-version` | `"0.11.16"` | pinned uv version (org standard) |
| `fetch-depth` | `2` | checkout depth (`0` for full-history secret scans) |
| `sync-args` | `"--locked --all-packages"` | `uv sync` args (single-package repos: `--all-extras --all-groups`) |
| `ci-requirements-path` | `".github/requirements-ci.txt"` | `--require-hashes` CI-tools file; `""` skips |

### Lint / type / security targets

| Input | Default | Purpose |
|---|---|---|
| `ruff-lint-paths` | `"scripts/ tests/"` | `ruff check` targets |
| `ruff-lint-args` | `""` | extra `ruff check` args (e.g. `--ignore=...`) |
| `ruff-format-paths` | `"scripts/ tests/"` | `ruff format --check` targets |
| `bandit-paths` | `"scripts/"` | `bandit -r` targets |
| `bandit-args` | `"-ll -ii -c pyproject.toml"` | extra bandit args |
| `mypy-paths` | `"kairix/"` | `mypy` targets |
| `mypy-args` | `"--ignore-missing-imports"` | extra mypy args |
| `compileall-paths` | `"scripts tests"` | `compileall` targets |
| `shellcheck-find-paths` | `"scripts"` | roots searched for `*.sh` |

### Test + coverage

| Input | Default | Purpose |
|---|---|---|
| `pytest-args` | `"-q tests -n auto"` | pytest selector / parallelism / junit |
| `coverage-paths` | `"--cov=scripts --cov=tests/lib"` | `--cov=` sources; `""` disables |
| `coverage-xml` | `"coverage.xml"` | coverage XML output path |
| `coverage-fail-under` | `0` | `--cov-fail-under` floor (0 defers to a ratchet) |
| `normalize-coverage-script` | `""` | optional post-pytest XML normaliser; `""` skips |

### Node / TS half (when `run-node: true`)

| Input | Default | Purpose |
|---|---|---|
| `node-version-file` | `".nvmrc"` | Node version file |
| `pnpm-version` | `"10.27.0"` | pnpm version |
| `pnpm-install-args` | `"--frozen-lockfile --ignore-scripts"` | `pnpm install` args |
| `ts-coverage-command` | `"pnpm -r --if-present test:coverage"` | TS coverage command |

### detect-secrets

| Input | Default | Purpose |
|---|---|---|
| `detect-secrets-baseline` | `".secrets.baseline"` | baseline file path |

### Secrets

| Secret | Required | Purpose |
|---|---|---|
| `gh-token` | no | `GITHUB_TOKEN` override for authenticated git/gh (falls back to `github.token`) |

Repo-specific secrets (`SONAR_TOKEN`, `CLI_PROXY_API_*`, `CODECOV_TOKEN`, …) stay
in the caller's own steps — they are not part of this generic gate.
