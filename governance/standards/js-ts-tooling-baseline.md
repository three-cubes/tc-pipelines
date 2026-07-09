---
type: standard
status: proposed
date: 2026-05-17
owner: platform
applies_to:
  - all-typescript-packages
  - all-javascript-packages
  - agent-runtime-plugins
  - typescript-mcp-servers
  - typescript-services
sources:
  - ADR — JS/TS tooling baseline
  - ADR — toolpack and capability pattern
  - ADR — quality ratchet
  - agent-actionable-feedback standard
  - plugin-authoring standard
  - mcp-engineering standard
purpose: >
  Operational playbook for the JS/TS toolchain. Tells a developer how to set up
  pnpm locally, run lint/build/test, add a new TS/JS package, update deps, read
  the eslint output, edit the lockfile policy, integrate with pre-commit and CI,
  and grant a per-file exemption without inline disables.
---

# JS/TS Tooling Baseline — Operational Standard

> A repo adopting this standard uses pnpm workspaces + a single eslint flat config at the
> root. Every TS/JS package conforms. The architectural decision belongs in the repo's own
> JS/TS tooling ADR. This document is
> the **operational** surface — workflows, exact commands, failure recovery.

## Where this fits

| Layer | Surface | Where |
|-------|---------|-------|
| Architectural decision | the repo's JS/TS tooling ADR | the repo's ADR series |
| Operational playbook | this standard | this file |
| Workspace declaration | `pnpm-workspace.yaml` | repo root |
| Node + pnpm pinning | `package.json` (`engines`, `packageManager`) + `.nvmrc` | repo root |
| Shared eslint config | `eslint.config.js` (flat config) | repo root |
| Pre-commit hook | `.pre-commit-config.yaml` (eslint hook) | repo root |
| CI workflow | `.github/workflows/ci.yml` | repo |
| Dependabot config | `.github/dependabot.yml` (npm ecosystem) | repo |

## 1. Installing pnpm locally

The repo uses `corepack` to provision pnpm — no global pnpm install required.

### macOS / Linux (developer laptops)

```bash
corepack enable
corepack prepare pnpm@10.27.0 --activate
```

Verify:

```bash
pnpm --version    # expect 10.27.0
node --version    # expect to match .nvmrc (24.x)
```

If `node` is wrong, either:

- `nvm use` from the repo root (reads `.nvmrc`), or
- install Node 24.x from your OS package manager.

### CI

`pnpm/action-setup@v4` provisions pnpm; `actions/setup-node@v4` reads `.nvmrc` and caches the pnpm store. See `.github/workflows/ci.yml`.

## 2. First-time bootstrap

After a fresh clone, the canonical one-command path installs both the Python and Node workspaces at once:

```bash
make bootstrap        # alias: make dev-env
```

It enables corepack + the pinned pnpm, then runs `pnpm install --frozen-lockfile`, alongside the uv steps (see the Python dependency-locking standard §2). The uv cache is written outside `$HOME` so sandboxed agents can install. Node-only manual equivalent (e.g. after a `package.json` / `pnpm-lock.yaml` change):

```bash
pnpm install --frozen-lockfile
```

`--frozen-lockfile` refuses to mutate `pnpm-lock.yaml` — if the lockfile and `package.json` disagree, install fails with a clear error. This is the correct CI behaviour and the right default locally.

If you intentionally changed deps (added/removed/bumped), run plain `pnpm install` to regenerate the lockfile, then commit both `package.json` and `pnpm-lock.yaml` together.

## 3. Running lint / build / test locally

From the repo root:

```bash
# Canonical parity path
make check

# Focused workspace commands (adjust the glob to your workspace layout)
pnpm -r --filter "./<workspace-glob>/**" lint
pnpm -r --filter "./<workspace-glob>/**" build
pnpm -r --filter "./<workspace-glob>/**" test
pnpm -r --if-present test:coverage

# Single package
pnpm --filter <pkg-name> lint
pnpm --filter <pkg-name> build
pnpm --filter <pkg-name> test
pnpm --filter <pkg-name> test:coverage

# Small-diff preflight (the quality-harness + TS-coverage-presence checks)
python3 <path-to>/run-quality-harness.py --staged
python3 <path-to>/typescript_coverage_present.py
```

`make check` is the source-of-truth local flow: it boots the pnpm workspace, prefers `.venv/bin` when present so Python tooling matches CI, runs the quality harness, executes blocking TS build/test gates, and exercises the same changed-file TS coverage presence gate that CI runs.

Workspace lint is intentionally informational in the current parity path; build, test, and changed-file coverage presence are the blocking proof points.

## 4. Adding a new TS/JS package

Pre-flight: confirm the package belongs in the workspace. Python MCPs (`*-py` suffix or `pyproject.toml`-only) do NOT join the workspace.

### Steps

1. Create the package directory under one of the workspace globs (e.g. `packages/plugins/*`, `packages/mcp/*`, `packages/services/*`, or `packages/skills/<name>/`).
2. Add `package.json` with these required scripts:
   ```json
   {
     "name": "<scoped-or-bare-name>",
     "version": "0.0.1",
     "private": true,
     "scripts": {
       "lint": "eslint . --max-warnings 0",
       "build": "<tsc | tsup | ...>",
       "test": "<runner>"
     }
   }
   ```
3. If the package needs a TypeScript config, add a `tsconfig.json`. Don't add a per-package eslint config — the root config covers it.
4. Run `pnpm install` from the repo root — pnpm picks up the new workspace member.
5. Verify: `pnpm --filter <new-pkg> lint && pnpm --filter <new-pkg> build && pnpm --filter <new-pkg> test`.
6. Commit `package.json` + any source. The root `pnpm-lock.yaml` updates automatically.

### Stay inside the workspace conventions

- Let the root `pnpm-lock.yaml` own lockfile state; remove any per-package `package-lock.json` (npm). The gate fails the PR otherwise.
- Inherit lint config from the root `eslint.config.js`; remove any per-package `.eslintrc*` or `eslint.config.js` you find.
- Pin exact versions in `package.json` per ADR-015 D10; rewrite any `^` or `~` semver ranges to the resolved exact version.
- Run `pnpm install` from the repo root; this keeps the workspace coherent and updates the single lockfile (use `npm install` only when porting an external package outside the workspace).

## 5. Updating dependencies

### Manual path

From the repo root:

```bash
# Bump a dep across all packages (or a single workspace)
pnpm up <package>@<version>
pnpm up --filter <pkg-name> <package>@<version>

# Interactive upgrade
pnpm up -i
```

Commit both `package.json` and `pnpm-lock.yaml` in the same commit.

### Dependabot path

`.github/dependabot.yml` runs the npm ecosystem daily. Patch bumps auto-merge after CI green; major-version bumps are reviewed manually because they often ship rule-semantics changes (especially eslint, @typescript-eslint, sonarjs).

When reviewing a Dependabot PR, check:

- CI is green (`pnpm -r lint`, `pnpm -r build`, `pnpm -r test`, sonar quality ratchet).
- The bump is in scope for the grouped-update strategy (Dependabot config controls grouping).
- Major-version bumps include a release-notes link in the PR body so the reviewer can scan for breaking changes.

## 6. Reading the eslint output + fixing each rule class

When `pnpm -r lint` fails, eslint prints one block per file:

```
/path/to/file.ts
  12:5  error  Unexpected use of `eval`  no-eval
  18:1  error  Cognitive Complexity of function is 16 which is greater than 15  sonarjs/cognitive-complexity
```

### Mapping a rule class to a fix

The rule name (last column) is the canonical identifier. Look it up:

- `sonarjs/*` rules: https://github.com/SonarSource/eslint-plugin-sonarjs
- `@typescript-eslint/*` rules: https://typescript-eslint.io/rules/
- Core eslint rules: https://eslint.org/docs/latest/rules/

Common rule classes:

| Cluster | Typical fix |
|---|---|
| `sonarjs/cognitive-complexity` | Extract a helper function; break a long if/else chain into a lookup table |
| `sonarjs/no-duplicate-string` | Extract the literal to a `const` |
| `@typescript-eslint/no-explicit-any` | Replace `any` with a precise type, `unknown`, or a generic |
| `@typescript-eslint/no-unused-vars` | Remove the unused binding, OR prefix with `_` if intentionally unused (allowed by config) |
| `sonarjs/no-identical-functions` | Extract the shared body to a helper |

### `--fix`

Many rules are auto-fixable:

```bash
pnpm -r lint -- --fix      # safe auto-fixes across all packages
```

Always review the diff. Auto-fixes for `sonarjs/no-unused-private-class-members` and similar can be aggressive.

## 7. Lockfile policy

**Never edit `pnpm-lock.yaml` by hand.** It is regenerated by `pnpm install`. Hand-edits will be overwritten or will cause hash-mismatch errors.

If you see a merge conflict in `pnpm-lock.yaml`:

```bash
# Drop the conflicted lockfile and regenerate
rm pnpm-lock.yaml
pnpm install                      # NOT --frozen-lockfile; regenerate fresh
git add pnpm-lock.yaml package.json
```

Verify CI passes with `--frozen-lockfile` after the regeneration.

## 8. Local environment parity with GitHub Actions

For local runs to match the Quality gate workflow, use the same bootstrap sequence CI uses:

```bash
uv sync --locked --all-packages
uv pip install --require-hashes --only-binary :all: -r .github/requirements-ci.txt
pnpm install --frozen-lockfile --ignore-scripts
make setup
make check
```

What this aligns:

- `uv sync --locked --all-packages` puts workspace Python packages into the same `.venv` CI uses.
- `uv pip install ...requirements-ci.txt` installs the CI toolchain (`pytest`, `ruff`, `bandit`, `detect-secrets`, coverage helpers) into that same venv.
- `pnpm install --frozen-lockfile --ignore-scripts` matches the CI workspace install posture.
- `make setup` installs the pre-commit hooks so staged-file checks fire before push.
- `make check` mirrors the local/CI gate chain.

If local and CI differ, treat that as a defect in the repo tooling/docs and fix the parity gap rather than normalising the mismatch.

## 9. Pre-commit hook behaviour + override

The eslint hook in `.pre-commit-config.yaml` runs on staged `.ts`/`.tsx`/`.js`/`.jsx` files under the repo's TS/JS workspace source globs. It invokes:

```bash
pnpm exec eslint --fix --max-warnings 0 <staged-files>
```

### When the hook fails

The hook emits `agent-actionable-feedback`-shaped messages. Examples:

```
FAIL eslint-staged
fix: 3 eslint errors in packages/mcp/mcp-outlook/src/server.ts;
     run `pnpm --filter mcp-outlook lint` to see them
next: fix the errors and re-run the commit
```

```
FAIL eslint-staged
fix: pnpm-lock.yaml missing; run `pnpm install --frozen-lockfile`
next: re-run the commit
```

```
FAIL eslint-staged
fix: node_modules stale; run `pnpm install --frozen-lockfile`
next: re-run the commit
```

### Override mechanism

There is no PR-body override for the eslint hook (unlike ADR-014's quality ratchet). The eslint gate is positive — fix the code or grant a per-file exemption in the flat config (see §10).

If you genuinely need to bypass the hook for a single commit (e.g. emergency fix to a non-JS file that pre-commit globs incorrectly), use `git commit --no-verify` — but expect CI to catch the same issue. Document the bypass in the commit body.

## 10. CI behaviour + debugging a failed CI lint run

The `.github/workflows/ci.yml` runs:

```yaml
- pnpm install --frozen-lockfile
- pnpm -r lint
- pnpm -r build
- pnpm -r test
```

### When CI lint fails

1. Click the failing job. The eslint output is in the `pnpm -r lint` step's log.
2. Reproduce locally:
   ```bash
   pnpm install --frozen-lockfile
   pnpm -r lint
   ```
3. If local passes but CI fails, the most common causes are:
   - **Lockfile drift.** Your branch has a `package.json` change but the lockfile wasn't regenerated. Fix: `pnpm install` (no `--frozen-lockfile`), commit the updated lockfile.
   - **Node version drift.** CI uses `.nvmrc`; if your local Node is different, results differ. Fix: `nvm use` from the repo root.
   - **Untracked files.** Local eslint sees files that aren't on the branch. Fix: `git status` to confirm; commit or stash.

### When `--frozen-lockfile` fails in CI

```
ERR_PNPM_OUTDATED_LOCKFILE  Cannot install with "frozen-lockfile" because pnpm-lock.yaml is not up to date with package.json
```

This means a `package.json` was edited without regenerating the lockfile. Fix locally:

```bash
pnpm install                # regenerates lockfile
git add pnpm-lock.yaml
git commit -m "chore: regenerate pnpm lockfile"
git push
```

## 10. Granting a temporary exemption (NEVER use inline disables)

Per ADR-015 D4 (mirroring ADR-010 D7), `// eslint-disable*` is **forbidden** in `src/` production code. The only sanctioned exemption surface is the **flat config's per-file override block**.

### Why this matters

Inline disables hide the exemption from reviewers — you have to grep the codebase to find them. A per-file override in `eslint.config.js` is in the canonical config, reviewable on every PR, and centrally auditable.

### How to add a per-file override

Edit `eslint.config.js` (NOT the package's local source). Append an override block:

```js
{
  files: ['packages/plugins/<name>/src/<specific-file>.ts'],
  rules: {
    'sonarjs/cognitive-complexity': 'off'
  },
  // Required: rationale comment naming the reason and the tracking issue if applicable.
  // Without a comment the reviewer will reject the override.
}
```

### What a good rationale looks like

```js
{
  // The plugin loader's dynamic-require path is intentionally complex — the
  // context bridge bootstraps before the type system is loaded, so splitting
  // it loses the single-pass guarantee. Tracked at issue #NNN.
  files: ['packages/plugins/context-bridge/src/loader.ts'],
  rules: {
    'sonarjs/cognitive-complexity': 'off'
  }
}
```

### What gets rejected

- No rationale comment.
- "Temporary" or "WIP" rationale without a tracking issue.
- Disabling a rule globally (whole-package, whole-repo) — that's an ADR-level change, not a per-file override.

### When the override is no longer needed

Delete the override block. The next `pnpm -r lint` either passes (rule is now satisfied) or fails with the original finding (rule is genuinely violated — fix the code).

## 11. Cleanup after adopting the root lockfile

When a repo first collapses per-package `package-lock.json` files onto the single root lockfile, drop the stale artefacts once after pulling the change:

```bash
# Drop stale node_modules across all packages
find . -type d -name node_modules -prune -exec rm -rf {} +

# Reinstall from the root lockfile
pnpm install --frozen-lockfile

# Verify
pnpm -r lint
pnpm -r build
pnpm -r test
```

This is a one-time cleanup. After it, every clone uses the root lockfile from the start.

## Stay inside the baseline

- Use `pnpm install` from the repo root for every install; the repo is a pnpm workspace and `npm install` mutates state the workspace does not own.
- Express lint exceptions as per-file overrides in `eslint.config.js`; keep `// eslint-disable*` out of `src/` so the override audit trail stays in one file.
- Pin Node and pnpm versions in BOTH `package.json` (`engines`) AND `.nvmrc` and keep them in sync; mismatched pins cause silent toolchain drift.
- Let the root `pnpm-lock.yaml` be the only lockfile — remove any per-package `package-lock.json`; the gate fails when one exists.
- Run CI with `pnpm install --frozen-lockfile`; if the lockfile mutates in CI, treat it as a bug to fix locally before push.
- Update this standard's plugin list in the same PR that adds a new eslint plugin so reviewers can see the surface change.
- Treat CI as the authoritative ratchet baseline (ADR-014 mode A); use `--local-scan` (mode B) only as a sanity check, never as a substitute.
- Raise an ADR before introducing a per-package eslint config; the per-package shape is a structural divergence and needs a recorded decision.

## References

- The repo's JS/TS tooling ADR — architectural decision and rationale.
- The toolpack-and-capability ADR §D7 — no-suppressions principle (inherited).
- The quality-ratchet ADR — touch-based quality ratchet that operates uniformly on Python and JS/TS.
- The plugin-authoring standard — plugin-specific authoring conventions (manifest, install path, scanner overrides).
- [`mcp-engineering-standard.md`](mcp-engineering-standard.md) — MCP server engineering rules; TypeScript MCPs follow this standard's toolchain.
- [`agent-actionable-feedback.md`](agent-actionable-feedback.md) — `fix:`/`next:`/`run:` requirements that the eslint hook and CI output conform to.
- pnpm workspaces: https://pnpm.io/workspaces
- eslint flat config: https://eslint.org/docs/latest/use/configure/configuration-files
- eslint-plugin-sonarjs: https://github.com/SonarSource/eslint-plugin-sonarjs
- @typescript-eslint: https://typescript-eslint.io/
