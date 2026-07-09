---
type: standard
status: proposed
date: 2026-05-17
owner: platform
applies_to:
  - all-python-packages
  - python-mcp-servers
  - any-future-installable-python-package
sources:
  - ADR — Python dependency locking with uv
  - ADR — quality ratchet
  - ADR — JS/TS tooling baseline
  - agent-actionable-feedback standard
  - mcp-engineering standard
purpose: >
  Operational playbook for Python dependency locking with uv. Tells a developer
  how to install uv, run a first-time bootstrap, add a new Python package to
  the workspace, update deps, regenerate the lockfile, integrate with
  pre-commit and CI, and recover from common failure modes.
---

# Python Dependency Locking — Operational Standard

> A repo adopting this standard uses a uv workspace at the root with a single `uv.lock`
> covering every Python package under the workspace. The architectural decision belongs in
> the repo's own uv dependency-locking ADR. This
> document is the **operational** surface — workflows, exact commands, failure
> recovery.

## Where this fits

| Layer | Surface | Where |
|-------|---------|-------|
| Architectural decision | the repo's uv dependency-locking ADR | the repo's ADR series |
| Operational playbook | this standard | this file |
| Workspace declaration | root `pyproject.toml` `[tool.uv.workspace]` | repo root |
| Workspace lockfile | `uv.lock` | repo root |
| Member packages | each member's `pyproject.toml` (e.g. `packages/<pkg>/pyproject.toml`) | repo |
| Pre-commit hook | `.pre-commit-config.yaml` (`uv-lock-check` local hook) | repo root |
| CI step | the CI check step (`uv lock --check` section) | repo |
| Dependabot config | `.github/dependabot.yml` (`pip` ecosystem) | repo |

## 1. Installing uv locally

uv ships as a single static binary. Pick whichever install path matches the rest of your toolchain.

### macOS / Linux (developer laptops)

```bash
# Homebrew (recommended for macOS — matches the rest of the repo's brew-installed tools)
brew install uv

# OR pipx (cross-platform)
pipx install uv

# OR the official one-liner
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Verify:

```bash
uv --version    # expect 0.11.x or newer
```

### CI

CI uses `astral-sh/setup-uv@v3` or invokes the same `curl` one-liner before running the gate. See `.github/workflows/ci.yml`.

## 2. First-time bootstrap

After a fresh clone (or after pulling a change that touched any `pyproject.toml` / `uv.lock`), the canonical one-command path is:

```bash
make bootstrap        # alias: make dev-env
```

This runs `uv lock --check` → `uv sync --locked --all-packages` → hashed `requirements-ci.txt` → pinned `pnpm install`, mirroring CI exactly. It writes the uv cache to a path **outside `$HOME` and the repo** (e.g. `/tmp/<repo>-uv-cache`) so sandboxed agents — which can't write `~/.cache/uv`, and where the repo is read-only at deploy — can install and test. Override `UV_CACHE_DIR` / `UV_PROJECT_ENVIRONMENT` to relocate.

Manual equivalent (Python only):

```bash
# Validate the lockfile is up to date with the workspace pyprojects
uv lock --check

# Install the workspace into a local .venv (idempotent)
uv sync --frozen
```

`--frozen` refuses to mutate `uv.lock` — if the lockfile and any workspace `pyproject.toml` disagree, install fails fast. This is the correct CI behaviour and the right default locally.

If you intentionally changed deps (added/removed/bumped), run plain `uv sync` (or `uv lock`) to regenerate, then commit both the changed `pyproject.toml` and `uv.lock` together.

## 3. Workspace structure

The root `pyproject.toml` declares:

```toml
[project]
name = "dev-tools"
version = "0.0.0"
requires-python = ">=3.10"

[tool.uv.workspace]
members = [
  "packages/mcp-tool-kit",
  "packages/mcp-powerpoint",
]
```

The `[project]` table exists only to anchor the workspace — the repo is not published. The `[tool.uv.workspace]` block lists every member by path.

Each member's own `pyproject.toml` carries the package's `[project]` table with `name`, `version`, `requires-python`, and `dependencies`. Member `requires-python` may be narrower than the root but never wider.

## 4. Adding a new Python package to the workspace

Pre-flight: confirm the package is installable (has its own `pyproject.toml` with a `[project]` table). One-off scripts under `scripts/` do NOT join the workspace.

### Steps

1. Create the package directory (e.g. `packages/mcp-new-thing/`).
2. Add `pyproject.toml` with:
   ```toml
   [project]
   name = "mcp-new-thing"
   version = "0.0.1"
   requires-python = ">=3.10"
   dependencies = [
     "mcp[cli]>=1.0",
   ]

   [build-system]
   requires = ["setuptools>=61"]
   build-backend = "setuptools.build_meta"
   ```
3. Append the path to `[tool.uv.workspace].members` in the root `pyproject.toml`.
4. Run `uv lock` from the repo root — uv picks up the new workspace member and regenerates `uv.lock`.
5. Verify: `uv lock --check` returns 0.
6. Commit the new `pyproject.toml`, the updated root `pyproject.toml`, and the regenerated `uv.lock` in the same commit.
7. If your repo tracks committed artefacts in a manifest, add an entry for the new package and its lockfile coverage there (the lockfile remains the single root `uv.lock` — no per-package lockfile).

### Stay inside the workspace conventions

- Let the single root `uv.lock` cover every workspace member; remove any per-package `uv.lock` you find.
- Declare a precise `requires-python` lower bound in every new `pyproject.toml` per ADR-016 D8.
- Express dependencies through `pyproject.toml` + the root `uv.lock`; remove any `requirements.txt`, `poetry.lock`, or `Pipfile.lock` that creeps in.
- Pin top-level deps in `pyproject.toml` with the tightest reasonable range and let uv resolve transitives into the lockfile; transitive pins in `pyproject.toml` cause spurious lockfile churn.

## 5. Updating dependencies

### Manual path

From the repo root:

```bash
# Bump a specific dep across the workspace
uv lock --upgrade-package <package>

# Bump every dep (use sparingly — review the diff carefully)
uv lock --upgrade

# Edit a member's pyproject.toml dependencies array directly, then:
uv lock
```

Commit both the changed `pyproject.toml` and the updated `uv.lock` in the same commit.

### Dependabot path

`.github/dependabot.yml` runs the `pip` ecosystem weekly with a 3-day cooldown across all update types. Dependabot opens PRs against the workspace `pyproject.toml` files. Each PR must include a regenerated `uv.lock` — the CI gate blocks merges with stale lockfiles.

When reviewing a Dependabot PR, check:

- CI is green (`uv lock --check`, ruff, bandit, pytest, sonar quality ratchet).
- The lockfile diff is plausible (a patch bump should touch a small number of hashed entries; a sprawling diff suggests a transitive cascade — read the bump carefully).
- Major-version bumps include a release-notes link so the reviewer can scan for breaking changes.

## 6. Lockfile policy

**Never edit `uv.lock` by hand.** It is regenerated by `uv lock`. Hand-edits will be overwritten or will fail hash verification.

If you see a merge conflict in `uv.lock`:

```bash
# Drop the conflicted lockfile and regenerate
rm uv.lock
uv lock
git add uv.lock
```

Verify CI passes with `uv lock --check` and `uv sync --frozen` after the regeneration.

### Hashes

`uv lock` writes SHA256 hashes for every locked artefact by default. Do NOT pass `--no-hashes`. The CI gate rejects lockfiles without hashes (ADR-016 D3).

## 7. Pre-commit hook behaviour + recovery

The `uv-lock-check` hook in `.pre-commit-config.yaml` runs only when a `pyproject.toml` is staged. It invokes:

```bash
uv lock --check
```

### When the hook fails

The hook emits `agent-actionable-feedback`-shaped messages. Examples:

```
FAIL uv-lock-check
fix: pyproject.toml changed but uv.lock is stale; run `uv lock` and re-stage uv.lock
next: re-run the commit
```

```
FAIL uv-lock-check
fix: uv not on PATH; install via `brew install uv` or `pipx install uv`
next: re-run the commit
```

### No bypass

There is no PR-body override for the lockfile gate (unlike ADR-014's quality ratchet). The lockfile is either current or it isn't.

If you genuinely need to bypass the hook (e.g. emergency fix to an unrelated file that the hook globs over-broadly), use `git commit --no-verify` — but expect CI to catch the same issue. Document the bypass in the commit body.

## 8. CI behaviour + debugging a failed CI lock check

The CI check step runs `uv lock --check` **before** the existing ruff / bandit / pytest sections. The placement is deliberate: a stale lockfile is a structural error, not a code-quality finding.

### When CI fails on `uv lock --check`

1. Click the failing job. The output names which `pyproject.toml` is out of sync.
2. Reproduce locally:
   ```bash
   uv lock --check
   ```
3. Regenerate:
   ```bash
   uv lock
   git add uv.lock
   git commit -m "chore: regenerate uv.lock"
   git push
   ```

### When `uv sync --frozen` fails

`uv sync --frozen` is used by production install paths (CI, VM bootstrap). A failure means a `pyproject.toml` was edited without regenerating the lockfile. Same fix as above.

## 9. Recovery paths

| Blocked state | Where to look | Fix | Next |
|---|---|---|---|
| `FAIL uv-lock-check` in pre-commit | The hook output names the stale `pyproject.toml` | `fix:` `uv lock && git add uv.lock` | `next:` re-run the commit |
| `uv: command not found` | uv not installed | `fix:` `brew install uv` (macOS) or `pipx install uv` | `next:` re-run the command |
| `uv lock` fails with "no compatible Python version" | A workspace member's `requires-python` excludes the root's range, or vice versa | `fix:` narrow the offending member's `requires-python` (or widen — but never wider than the root) | `next:` re-run `uv lock` |
| `uv lock` fails with a resolution conflict | Two workspace members pull in transitively-incompatible versions of a shared dep | `fix:` tighten the offending top-level constraint in the conflicting member's `pyproject.toml`; OR, if genuinely incompatible, split to per-package lockfiles + document the carve-out in ADR-016 Updates | `next:` re-run `uv lock` |
| `uv sync --frozen` fails in CI | Lockfile stale on the branch | `fix:` `uv lock` locally, commit, push | `next:` watch CI re-run |
| Merge conflict in `uv.lock` | Two branches both bumped a dep | `fix:` `rm uv.lock && uv lock && git add uv.lock` | `next:` resolve, commit |
| the no-orphan-top-dirs fitness check fails citing `uv.lock` | `uv.lock` not in the check's ALLOWED_FILES | `fix:` add `uv.lock` to that check's ALLOWED_FILES (should already be there) | `next:` re-run `make check` |

## 10. Production install (VM / containers)

Production paths use `uv sync --frozen` — never plain `uv sync`, never `uv pip install --system` against an unfrozen environment. The pattern:

```bash
# On the VM, in the repo root
uv sync --frozen           # installs the workspace into .venv/ from uv.lock
.venv/bin/python -m <member-entry-point>
```

If a VM-bootstrap script currently calls `pip install` against any of the workspace members, migrate it to `uv sync --frozen`. Tracked under ADR-016 Open Questions §4.

## Stay inside the lockfile contract

- Install against the workspace with `uv sync --frozen`; `pip install` bypasses the lockfile and produces a non-reproducible env.
- Express dep changes through `uv add` / edit `pyproject.toml` + `uv lock`; remove any `poetry add` / `pip-compile` / `pdm add` invocation from scripts and CI.
- Lock with hashes — run plain `uv lock` (ADR-016 D3); strip any `--no-hashes` flag from scripts.
- Use the single root `uv.lock` for every workspace member; remove per-package lockfiles when you find them.
- Declare a precise `requires-python` lower bound in every `pyproject.toml` per ADR-016 D8.
- Regenerate `uv.lock` via `uv lock`; treat hand-edits as a bug to revert.
- Run `uv lock --check` in CI as a required gate; that check exists to be honoured, not bypassed.
- Raise an ADR before introducing a new lockfile tool (poetry, pip-tools, PDM); changing the lockfile contract is an ADR-level decision.

## References

- The repo's uv dependency-locking ADR — architectural decision and rationale.
- The JS/TS tooling ADR — JS/TS analogue (pnpm workspace + lockfile).
- The quality-ratchet ADR — touch-based quality ratchet that operates uniformly on Python and JS/TS.
- [`mcp-engineering-standard.md`](mcp-engineering-standard.md) — MCP server engineering rules; Python MCPs follow this standard's lockfile contract.
- [`agent-actionable-feedback.md`](agent-actionable-feedback.md) — `fix:`/`next:`/`run:` requirements that the lock hook and CI output conform to.
- uv documentation: <https://docs.astral.sh/uv/>
- uv workspaces: <https://docs.astral.sh/uv/concepts/projects/workspaces/>
- uv lockfile reference: <https://docs.astral.sh/uv/concepts/projects/sync/>
