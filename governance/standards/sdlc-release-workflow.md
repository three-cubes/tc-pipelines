---
type: standard
context: three-cubes
status: active
version: "1.0"
created: 2026-04-18
owner: platform
tags: [sdlc, git, release, branching, versioning, standards]
---

# SDLC Release Workflow

Standard branching model, versioning convention, and release process for **public Three Cubes repositories that ship as installable packages** (today: `quanyeomans/kairix`). This document is the canonical home for the CalVer + `main`/`develop` model.

**Related:**
- the development-workflow standard — general PR + quality-gate workflow
- a trunk-only repo's `CLAUDE.md` — trunk-only operating posture (overrides the develop-branch model below for that repo)
- the python-dependency-locking standard — uv lockfile rules (applies to released Python packages)

> **Reconciliation with trunk-only repos.** A trunk-only repo (e.g. `tc-agent-zone`) follows this model by exception: `main` is the only durable branch (direct push is blocked — every change lands via PR), with one feature branch per feature merged to `main` ~daily per the development-workflow standard §Branching (no long-lived `develop`). The `main`/`develop`/alpha-tag model below applies to **kairix** and any **future package repos that need a public/internal split**. If a trunk-only repo's deploy story later requires pre-release pinning, this doc is the source pattern to adapt — but until then, do not introduce a `develop` branch into a trunk-only repo.

---

## 1. Why this model

We deploy to a private VM before publishing to a public repository. This creates a gap: the public `main` branch must only contain validated, production-quality code, but we need a stable target for CI and VM testing while features accumulate.

The model solves this with two durable branches and pre-release tags:

- `main` is always releasable. Public users and `pip install` see only validated commits.
- `develop` accumulates features between releases. The VM deploys from pre-release tags cut from `develop`.
- `main` never receives direct commits — only merge commits from `develop` at release time.

---

## 2. Branch structure

```
main        ← validated releases only
             ← CalVer tags: v2026.4.18, v2026.5.1, …
             ← CHANGELOG updated here
             ← pip install kairix → this branch

develop     ← all feature PRs merge here
             ← CI runs on every PR
             ← alpha tags: v2026.4.18a1, a2, …
             ← VM deploys from alpha tags

feature/*   ← one branch per feature or fix, PR → develop
hotfix/*    ← urgent fix branched from main, PR → main AND back-merged to develop
```

### Branch naming

| Prefix | Use |
|---|---|
| `feature/FEAT-NNN-short-description` | New capability, from develop |
| `fix/short-description` | Bug fix, from develop |
| `hotfix/short-description` | Critical production fix, from main |
| `docs/short-description` | Docs-only change, from develop |
| `chore/short-description` | Tooling, CI, dependency update |

---

## 3. Versioning — CalVer

All package repos use **Calendar Versioning**: `YYYY.MM.DD` (no leading zeros in month/day).

| Context | Format | Example |
|---|---|---|
| Stable release (main) | `YYYY.MM.DD` | `2026.4.18` |
| Same-day second release | `YYYY.MM.DD.N` | `2026.4.18.1` |
| Alpha pre-release (develop) | `YYYY.MM.DDaN` | `2026.4.18a1` |
| Development snapshot | `YYYY.MM.DD.devN` | `2026.4.18.dev1` |

**Rules:**
- `pyproject.toml` version is `YYYY.MM.DDaN` while on `develop`. Changed to `YYYY.MM.DD` in the merge-to-main PR.
- Alpha numbering resets to `a1` for each new CalVer date. `a2`, `a3` etc. when multiple alpha tags are cut on the same date.
- PEP 440 alpha releases (`aN`) are preferred over dev releases (`.devN`) because `pip install <package>` ignores alpha pre-releases by default — users on `pip install` always get stable.

---

## 4. Day-to-day workflow

### Starting a feature

```bash
git checkout develop
git pull origin develop
git checkout -b feature/FEAT-042-cross-encoder-reranking
# ... work ...
git push origin feature/FEAT-042-cross-encoder-reranking
# Open PR → develop
```

### PR requirements before merge to develop

- All CI checks pass (unit tests, linting, type checking)
- Benchmark gate passes (auto-triggers for retrieval code changes)
- At least one reviewer approval (or self-merge with written rationale for solo work)

### After PR merges to develop

If the VM needs this specific change immediately, cut a new alpha tag:
```bash
git checkout develop && git pull
git tag v2026.4.18a2
git push origin v2026.4.18a2
```
Then on the VM:
```bash
pip install git+https://github.com/quanyeomans/kairix@v2026.4.18a2
```

Otherwise wait — alpha tags are cut in batches when a VM deploy makes sense.

---

## 5. VM deployment from develop

The VM always runs a pinned alpha tag, never `@develop` directly (floating refs make rollback harder).

```bash
# Deploy a specific alpha to VM
pip install git+https://github.com/quanyeomans/kairix@v2026.4.18a1

# Check what is installed
pip show kairix

# Rollback to previous alpha
pip install git+https://github.com/quanyeomans/kairix@v2026.4.17a2
```

**Validation checklist before cutting a stable release:**

- [ ] `kairix onboard check` reports green on VM
- [ ] `kairix embed` completes without errors
- [ ] `kairix benchmark run` weighted total >= previous stable baseline
- [ ] MCP server starts and responds to `search` tool call
- [ ] No regression in monitoring log (`kairix eval monitor`)

---

## 6. Cutting a stable release

Once `develop` is validated on the VM:

1. **Open a PR: `develop → main`**
   - Title: `release: v2026.4.18`
   - Update `pyproject.toml` version from `2026.4.18a2` → `2026.4.18`
   - Update `CHANGELOG.md` — add release section, move "Unreleased" items under it
   - CI must pass on the PR

2. **Merge the PR** (squash or merge commit — prefer merge commit to preserve history)

3. **Tag on main:**
   ```bash
   git checkout main && git pull
   git tag v2026.4.18
   git push origin v2026.4.18
   ```

4. **Immediately cut a new develop alpha** for the next cycle:
   ```bash
   git checkout develop
   git merge main  # keep develop ahead of main
   # bump pyproject.toml version to next expected CalVer + a1
   git commit -am "chore: bump develop to 2026.5.1a1"
   git push origin develop
   ```

5. **VM final deploy from stable tag:**
   ```bash
   pip install git+https://github.com/quanyeomans/kairix@v2026.4.18
   ```

---

## 7. CHANGELOG format

Follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Every PR to `develop` that adds user-visible behaviour adds a bullet under `## [Unreleased]`. The release PR moves those bullets to a dated section.

```markdown
## [Unreleased]

## [2026.4.18] - 2026-04-18

### Added
- Cross-encoder re-ranking (`pip install kairix[rerank]`, opt-in via config)
- CI benchmark regression gate (contract suite, mock backend, auto PR comment)

### Changed
- Temporal chunk-date boost now requires explicit temporal marker in query (guard on by default)

### Fixed
- `_enrich_chunk_dates` path match now uses LIKE suffix (was exact match, missed all rows)
```

---

## 8. Hotfixes

For urgent production bugs that cannot wait for the next release cycle:

```bash
git checkout main
git checkout -b hotfix/critical-embed-bug
# fix
git push origin hotfix/critical-embed-bug
# PR → main (fast, minimal review)
# After merge to main:
git checkout main && git pull
git tag v2026.4.18.1   # same-day patch suffix
git push origin v2026.4.18.1
# Back-merge to develop
git checkout develop
git merge main
git push origin develop
```

---

## 9. Applying this model to other repos

The same model applies to all Three Cubes **package** repos. Repo-specific details:

| Repo | Notes |
|---|---|
| `quanyeomans/kairix` | Public package. `main` is public-facing. Alpha tags for VM. |
| `three-cubes/tc-agent-zone` | **Exception — trunk-only.** Private. No `develop` branch. See its `CLAUDE.md` and the development-workflow standard. Alpha tags not used. |
| Future repos | Follow this standard by default. Document deviations in repo CONTRIBUTING.md or its `CLAUDE.md`. |

For repos that deploy via `git pull` (not pip install), use the same alpha tag convention for VM pinning but deploy with:
```bash
git fetch origin
git checkout v2026.4.18a1  # detached HEAD, pinned
# or
git reset --hard v2026.4.18a1
```

### Trunk-only VM-deploy repos — deploy on merge

A trunk-only repo that deploys to a VM (e.g. `tc-agent-zone`) does not cut alpha tags or run a manual `git checkout` on the deploy path. Merge to `main` **triggers** its `deploy-on-merge` workflow, which calls the tc-pipelines [`azure-vm-deploy.yml`](../../.github/workflows/azure-vm-deploy.yml) reusable (pinned to a `@vN` tag) to snapshot → apply → smoke the target VM. The deploy is bracketed by a recovery-point snapshot before the first mutation and a verification probe after — see [`snapshot-before-apply.md`](snapshot-before-apply.md) + [`deployment-verification.md`](deployment-verification.md). Reserve the manual pinned-checkout flow above for operator-driven or recovery deploys; the pip-install alpha-tag flow (§4–§6) stays scoped to package repos.
