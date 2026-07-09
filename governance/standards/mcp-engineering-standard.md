---
title: MCP engineering standard
date: 2026-05-11
status: partially-superseded-by-ADR-017  # build-tooling sections only; tool-design contract remains canon
owner: platform
companion:
  - skills-architecture
  - tool-ux-contract
  - quality-harness
  - testing-strategy
---

# MCP engineering standard

A repo may mix Python / TypeScript / shell / config, but executable
agent capabilities need one engineering posture.

**Decision:** TypeScript is the default implementation language for new MCP
servers and executable tool surfaces we control. Python remains first-class for
Python-native dependencies and existing Python servers, but it is an exception
path, not a second default.

This is not a move away from the Python quality work. The opposite: the Python
quality-harness patterns are the baseline we now lift into TypeScript work.
TypeScript gets the same contract discipline, failability proof, ratcheting, and
agent-actionable failures that Python forced us to clarify.

## Language decision rule

| Capability shape | Default | Exception path |
|---|---|---|
| New external API integration | TypeScript MCP server using `@three-cubes/mcp-tool-kit` | Python only if the canonical SDK/runtime is Python-only or materially better |
| New shared executable tool used by 2+ agents | TypeScript MCP server | Python only for Python-native heavy dependencies |
| Existing bash/python skill being promoted | TypeScript MCP cluster | Keep script only if agent-local, low-coupling, and no shared auth/state |
| Document, deck, PDF, table, ML/data dependency | TypeScript orchestration unless the core library is Python-native | Python MCP server using `mcp_tool_kit` |
| Prompt/procedure only | Prompt-only `SKILL.md` | No executable wrapper |

Examples of valid Python exceptions today:

- `mcp-powerpoint` because `python-pptx` is the real rendering dependency.
- PDF/table extraction where `pypdf`, `pdfplumber`, or similar Python libraries
  are the capability.
- ML/data workflows where Python libraries are the product, not incidental glue.

Every Python exception must state the reason in the board card or implementation
report. If the reason is only “I know Python better”, use TypeScript.

## Required MCP tool contract

All agent-facing MCP tools must satisfy the Tool UX contract:

- TypeScript tools use `defineTool` from `@three-cubes/mcp-tool-kit`.
- Python tools use `define_tool` from `mcp_tool_kit`.
- Unknown fields use drop-and-warn unless ambiguity requires failure.
- Errors use structured `{code, what, hint, ...}` envelopes.
- Irreversible tools declare validate companions.
- Tool descriptions are agent-facing and include useful defaults.
- Tests cover happy path, coercion/drop-and-warn path, structured error path,
  and validate companion path where applicable.

No new raw MCP `server.tool(...)`, raw `Tool(...)`, or hand-rolled validation
for agent-facing tools without an explicit architecture note.

## Quality patterns carried from Python into TypeScript

The quality-harness work established maintainability patterns that now apply to
both languages:

| Pattern | Python expression | TypeScript expression |
|---|---|---|
| Contract over implementation | pytest contract tests for public functions/CLI surfaces | Vitest contract tests for public `defineTool` surfaces and exported clients |
| Boundary fakes, not internal patches | avoid monkeypatching internal functions; fake filesystem/API boundaries | avoid `vi.mock` of repo internals; fake HTTP/client boundaries |
| Ratcheting debt | per-file baseline files | same baselines for TS checks when added |
| Failability proof | sabotage fixture proves the check fails | Vitest/fitness fixture or CLI sabotage proves TS gate fails |
| Agent-actionable errors | check output includes `fix:`, `next:` or `run:` | same for TS scripts, MCP errors, and CI failures |
| No silent gate suppression | `# quality-harness rationale:` near suppressions | same near `// @ts-expect-error`, eslint disables, Vitest skips, workflow silencers |
| Generated artefact contract | generated docs checked with `git diff --exit-code` | same for TS build/catalog outputs when committed |

## Required local validation by change type

### TypeScript MCP server/library change

Run from the repo root against every touched TypeScript package:

```bash
pnpm --filter <package-name> run typecheck
pnpm --filter <package-name> run test -- --run
pnpm --filter <package-name> run build
```

If the package exposes coverage, run:

```bash
pnpm --filter <package-name> run test:coverage
```

When the change touches TypeScript implementation under `src/`, the coverage run must emit `coverage/lcov.info` and pass the changed-file coverage gate (the `typescript_coverage_present` fitness check, now in tc-fitness).

Minimum expectation for new TypeScript MCP packages:

- `tsconfig.json` with `strict: true`.
- `package.json` scripts: `typecheck`, `test`, `build`.
- Vitest tests for tool contract behaviour.
- No committed `node_modules/`, `dist/`, coverage, or runtime cache output.

### Python MCP server/library change

Run in the server/package venv:

```bash
python -m pytest -q <package-tests>
python -m compileall -q <src-path>
ruff check <src-path> <tests-path>
```

Minimum expectation for new Python MCP packages:

- Pydantic schemas for tool args.
- `mcp_tool_kit` for listing/dispatch/tool UX behaviour.
- pytest tests for tool contract behaviour.
- No committed `.venv/`, `.pytest_cache/`, `__pycache__/`, or `*.egg-info/`.

### Cross-language repo gate

Before commit:

```bash
make check
```

Targeted preflight for a small diff — run the fitness harness (`tc-fitness run`, wrapped by `make check`).

`make check` is the canonical local parity path. It runs the quality/fitness harness, executes Python tests with branch coverage, runs the TS workspace build/test gates, and invokes the TypeScript changed-file coverage presence check.

If the CI check fails because a known branch-range scan includes
pre-existing unrelated debt, document the exact failing gate and prove the touched
surface passed its targeted gate. Do not hide the failure.

## CI state and next ratchets

TypeScript MCP gates are first-class in `make check`, the CI check, and the CI workflow:

1. Install the pnpm workspace from the repo root with `pnpm install --frozen-lockfile --ignore-scripts`.
2. Run workspace lint/build/test across the MCP workspace packages in CI, with lint currently informational and build/test blocking.
3. Run the TS MCP gate script locally to enforce typecheck/test/build across `tools/mcp/**`, building `@three-cubes/mcp-tool-kit` first.
4. Run `pnpm -r --if-present test:coverage` in CI so every package that advertises coverage emits artefacts.
5. Fail the gate when touched TypeScript implementation files are absent from LCOV (the `typescript_coverage_present` check).

Next maintainability ratchets:

1. Add skip/suppression rationale checks for TypeScript:
   `it.skip`, `describe.skip`, `test.skip`, `// @ts-ignore`,
   `// @ts-expect-error`, eslint-disable comments, and Vitest coverage excludes.
2. Add ratcheted TypeScript coverage after the package gates are stable.
3. Raise the test existence check into a stronger contract-shape check once the
   current server tests have converged on consistent `defineTool` fixtures.

Authors still include package-local gate evidence in completion notes for
touched packages.

## Review checklist

For every executable capability PR:

- [ ] Language decision follows the rule above; Python exceptions state why.
- [ ] Tool UX contract library is used (`mcp-tool-kit` or `mcp_tool_kit`).
- [ ] Tests assert public tool behaviour, not private implementation details.
- [ ] Typecheck/build/test gates for each touched package are documented.
- [ ] Quality-harness suppressions have rationale.
- [ ] Generated catalog/capability artefacts are current.
- [ ] No runtime/build/cache artefacts are committed.
