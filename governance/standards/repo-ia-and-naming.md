---
type: standard
status: adopted
date: 2026-05-10
owner: platform
applies_to:
  - repo-ia
  - file-naming
  - directory-structure
  - capability-contracts
  - refactors
---

# Repo IA and Naming Standard

A repo should be easy for humans and agents to reason about. The tree should answer two questions quickly:

1. **Where does this belong?**
2. **What is this file or directory for?**

This standard governs new paths and structural refactors. The first executable ratchet covers high-signal surfaces only — for example: top-level directories, `docs/**/*.md`, and importable Python under `scripts/checks/`, `scripts/lib/`, and `tests/`. Existing exceptions are ratcheted through a path-naming ratchet baseline and should shrink over time.

## Core principles

1. **Resolver-first.** Every top-level directory and major capability family has a local `README.md` that explains what belongs there and what does not.
2. **Boundary before move.** Do not move files merely for neatness. Moves should align with an architectural boundary: capability, runtime type, deployment boundary, test layer, evidence/archive, or service boundary.
3. **Kebab-case for human-facing paths.** Directories and docs should be lowercase kebab-case unless a platform convention requires otherwise.
4. **Snake_case for importable Python.** Python modules/packages that are imported should use snake_case. Executable CLI script names may use kebab-case.
5. **Conventional uppercase only when conventional.** `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`, `AGENTS.md`, `SOUL.md`, `MEMORY.md`, `STYLE.md`, `TOOLS.md`, and similar agent-runtime bootstrap files are allowed.
6. **Generated/runtime distinction must be visible.** Generated committed files need generator headers/checks. Runtime/cache/log artefacts do not belong in source.
7. **Compatibility beats purity.** Runtime paths consumed by the agent runtime, systemd, cron or deployment scripts should move only with compatibility wrappers and path-reference audits.
8. **Repo-relative paths serialise as POSIX.** When a repo-relative path is turned into a string for a committed or cross-process/cross-OS artefact (capability manifests, catalogues, the interface inventory, export manifests, skill indices, VM runner paths), use `path.relative_to(root).as_posix()` — never `str(path.relative_to(root))`, which emits the host-native separator (backslashes on Windows) and silently breaks Linux CI consumers and generated-artefact-freshness diffs (it "fails in inconsistent ways"). For a value that is already POSIX by contract, parse it with `PurePosixPath`, not `Path`. Enforced by the posix-path-serialisation fitness check.

## Top-level directory resolver

The table below is **one repo's example top-level layout** — an illustration of the principle, not a mandated tree. Adapt the directories and boundaries to your repo; what transfers is the discipline: every top-level directory has a clear boundary and a local `README.md`.

| Directory | Boundary | Target status |
|---|---|---|
| `.architecture/` | Quality-harness baselines and architecture fitness metadata | Keep |
| `.github/` | GitHub workflow definitions | Keep |
| `agent-bootstrap/` | Bootstrap artefacts and generated capability manifests | Keep now; generated sub-tree may move later |
| `agents/` | Durable agent identity/bootstrap source | Keep |
| `benchmark-results/` | Historical/curated benchmark evidence | Future `evidence/benchmarks/` candidate |
| `cron-scripts/` | Scheduled operational scripts | Future `operations/cron/` candidate |
| `docs/` | Repo-canonical architecture, standards, runbooks, decisions, plans | Keep |
| `eval/` | Curated eval datasets/fixtures | Future `tests/evals/` or `evidence/` alignment |
| `hooks/` | Platform event hooks | Keep |
| `infra/` | Config templates, IaC, systemd, deployment wiring | Keep |
| `mcp-servers/` | MCP server implementations | Keep; move shared libraries later |
| `scripts/` | Repo automation, generators, validators | Keep |
| `skills/` | Active AgentSkill implementations | Keep |
| `skills-backlog/` | Legacy/prototype skills, not active runtime | Future `archive/skills-backlog/` candidate |
| `suites/` | Legacy eval/test suite definitions | Future `tests/suites/` candidate |
| `tests/` | Automated tests by layer | Keep |
| `tools/` | Current long-running service implementations | Future `services/` candidate |
| `workflows/` | Lobster/workflow definitions | Future `operations/workflows/` candidate |

## Naming rules

### Directories

- Use lowercase kebab-case: `agent-bootstrap`, `mcp-servers`, `skills-backlog`.
- Avoid vague names for new top-level directories: `stuff`, `misc`, `utils`, `new`, `tmp`, `archive2`.
- Hidden tooling dirs are exempt: `.git`, `.github`, `.architecture`, `.pytest_cache`, `.ruff_cache`.

### Markdown files

- Use lowercase kebab-case: `quality-harness.md`, `tool-ux-contract.md`.
- Use date prefix only when chronology is the identifier: `2026-05-10-decision-title.md`.
- Conventional uppercase files are allowed when they are platform/user conventions: `README.md`, `CHANGELOG.md`, `SECURITY.md`, `AGENTS.md`, `SOUL.md`.
- Do not introduce new all-caps project docs such as `BUILDER-BRIEF.md`; use `builder-brief.md` unless compatibility requires otherwise.

### Python

- Importable modules/packages: snake_case, e.g. `agent_capability_contract.py`.
- Executable repo CLIs may use kebab-case, e.g. `build-agent-capabilities.py`.
- Test files: `test_<thing>.py`.

### Shell scripts

- Use kebab-case with `.sh`, e.g. `restore-crons.sh`.
- Use names that state the operation, not implementation mechanics.

### YAML/JSON manifests

- Use kebab-case for manifests and route files, e.g. `toolpack.yaml`, `route-map.yaml`, `routes.yaml`.
- Use singular when the file describes one thing, plural when it is a collection.

## Capability directory contract

New capability families should use:

```text
capabilities/<capability-id>/
  README.md
  capability.yaml
  route-map.yaml
  bdd.feature
  implementation-map.yaml
```

`<capability-id>` must be lowercase kebab-case.

## Test layout

Place tests under `tests/<area>/test_*.py` for platform-level code. `<area>` mirrors the source root the test exercises:

| Source under test | Test path |
|---|---|
| `scripts/<group>/foo.py` | `tests/scripts/<group>/test_foo.py` |
| `tools/<tool>/run.py` | `tests/tools/test_<tool>_run.py` |
| `<domain>/<area>/<thing>.py` | `tests/<domain>/test_<thing>.py` |
| other top-level source trees (e.g. `infra/`) + fitness checks | `tests/<area>/test_*.py` (e.g. `tests/fitness/`) |

Default pytest discovery (`pytest tests/`) is the canonical scope; CI does not enumerate per-package test paths.

**Exception — encapsulated packages keep tests adjacent.** A package that ships as a self-contained, distributable unit owns its tests inside the package boundary so it stays installable and testable in isolation:

- `packages/lib/<lib>/tests/` — published Python libraries
- `packages/skills/<name>/tests/` — skill bundles (a skill ships with its tests)
- `packages/mcp/<pkg>/tests/`, `packages/plugins/<pkg>/tests/`, `packages/lib/<pkg>/tests/` — MCP / plugin / shared-lib packages

If your code is the runtime-distributable surface, it stays inside the package; if it is platform infrastructure invoked from the repo root, its test goes under `tests/`.

## Move policy

Every structural move PR must include:

1. old path → new path map;
2. compatibility decision: shim, wrapper, symlink, or flag-day;
3. path-reference audit across scripts, workflows, docs, systemd, config templates and tests;
4. validation evidence;
5. explicit statement that no live apply/restart/cron write was performed unless the change owner approved it in-session.

## Fitness-function requirement

High-signal new paths that violate these rules fail the repo's quality harness unless they are added to the path-naming ratchet baseline with rationale in the commit/PR. Expand the ratchet only when the added surface produces clear fix paths rather than ecosystem noise.
