---
type: standard
status: adopted
date: 2026-05-23
owner: platform
applies_to:
  - mcp-tool-authors
  - sub-agents
operationalises:
  - the canonical MCP tooling ADR (D9 — contract tests non-negotiable)
  - the interface-has-contract-test (G1) gate
related:
  - the mcp-tooling-canonical-pattern standard (§5 Test pyramid)
  - the testing-strategy standard (§Contract Testing)
  - the agent-actionable-feedback standard (lead-with-action)
  - the quality-ratchet standard (baseline-shrinks-only)
---

# Contract test patterns — TS + Python MCP tools

Write a contract test for every registered MCP tool. Each test
covers the registrar's external surface: input schema, output text
shape, and side-effect contract.

## What each test asserts

For every registered tool:

1. **Registration** — the tool name appears in the server's registry with a non-empty description.
2. **Schema acceptance** — a representative valid input produces a non-error reply.
3. **Schema rejection** — at least one canonical invalid input (missing required, empty string, out-of-range, unknown enum) returns `isError: true`.
4. **Output prefix** — assert the canonical text prefix the agent pattern-matches against (e.g. `Sent from`, `WOULD send from`, `No events today in`).
5. **Irreversible-tool dry-run** — for `irreversible: true` tools, the auto-paired `<tool>_validate` companion produces a `WOULD <action>` reply and the external adapter is never called.

Assertions stay durable when prose drifts because they target prefixes and structural markers. URLs, timestamps, and brand strings live outside the contract — leave them alone.

## TS MCP contract — copy + rename

```typescript
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';

// vi.mock() is hoisted at transform time. Place it BEFORE the imports
// it mocks; the registrar import below would otherwise pull the real
// client before the mock takes effect.
vi.mock('../../src/client.js', () => ({
  graphGet: vi.fn(),
  graphPost: vi.fn(),
  // ... every export the registrar imports ...
  GraphApiError: class GraphApiError extends Error { /* ... */ },
  toolKitCodeForGraphStatus: (status: number) => 'backend_error',
}));

import { graphGet, graphPost } from '../../src/client.js';
import { register<Group>Tools } from '../../src/tools/<group>.js';

type CapturedTool = {
  name: string;
  description: string;
  handler: (args: Record<string, unknown>) => Promise<{
    content: Array<{ type: 'text'; text: string }>;
    isError?: boolean;
  }>;
};

function buildServer(): { tools: Record<string, CapturedTool> } {
  const server = new McpServer({ name: 'test', version: '0.0.0' });
  register<Group>Tools(server);
  // The SDK stores registered tools under `_registeredTools`, sometimes
  // nested under `.server` depending on SDK version. Read both.
  const captured = ((server as unknown) as {
    server?: { _registeredTools?: unknown };
    _registeredTools?: unknown;
  });
  return {
    tools: (captured.server?._registeredTools ?? captured._registeredTools ?? {}) as Record<string, CapturedTool>,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('<group> tools — registration contract', () => {
  it('registers exactly the N <group>_* tools with non-empty descriptions', () => {
    const { tools } = buildServer();
    for (const name of ['<tool_1>', '<tool_2>']) {
      expect(tools[name]).toBeTruthy();
      expect(tools[name]?.description?.length ?? 0).toBeGreaterThan(0);
    }
  });
});

describe('<tool_1> contract', () => {
  it('happy-path emits "<canonical prefix>"', async () => {
    (graphGet as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ /* fake response */ });
    const { tools } = buildServer();
    const reply = await tools.<tool_1>.handler({ /* valid args */ });
    expect(reply.content[0]?.text).toMatch(/^<canonical prefix>/);
  });

  it('schema rejects missing required field', async () => {
    const { tools } = buildServer();
    const reply = await tools.<tool_1>.handler({ /* missing field */ });
    expect(reply.isError).toBe(true);
  });
});
```

For `irreversible: true` tools, also add:

```typescript
describe('<tool_1> contract', () => {
  it('exposes a `<tool_1>_validate` companion', () => {
    const { tools } = buildServer();
    expect(tools.<tool_1>_validate).toBeTruthy();
  });

  it('dry-run via _validate emits "WOULD <action>" and triggers no side effect', async () => {
    const { tools } = buildServer();
    await tools.<tool_1>_validate.handler({ /* valid args */ });
    expect(graphPost).not.toHaveBeenCalled();
  });
});
```

### Tools that touch the filesystem

Stub only the methods the handler uses; preserve the rest via `importOriginal`. The mcp-tool-kit telemetry sink uses `mkdir`, so the test environment needs it available:

```typescript
vi.mock('node:fs/promises', async (importOriginal) => {
  const actual = await importOriginal<typeof import('node:fs/promises')>();
  return {
    ...actual,
    mkdir: vi.fn(async () => undefined),
    writeFile: vi.fn(async () => undefined),
  };
});
```

## Python MCP contract — copy + rename

`tests/contract/conftest.py`:

```python
"""Contract-test fixtures for the <server> MCP tools."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[6]
for src in (
    REPO_ROOT / "agentic" / "tools" / "mcp" / "<server>" / "src",
    REPO_ROOT / "agentic" / "tools" / "mcp" / "mcp-tool-kit" / "src",
):
    s = str(src)
    if src.exists() and s not in sys.path:
        sys.path.insert(0, s)


@pytest.fixture(scope="session")
def tools_registry() -> list:
    """Return the populated TOOLS list. Importing the server module
    triggers every ``define_tool(...)`` call."""
    from <server_pkg> import server as srv
    return srv.TOOLS


@pytest.fixture
def tool_by_name(tools_registry):
    """``tool_by_name('render')`` → the registered DefinedTool dataclass."""

    def _find(name: str):
        for entry in tools_registry:
            if entry.name == name:
                return entry
        raise KeyError(f"no registered tool named {name!r}")

    return _find


@pytest.fixture
def invoke():
    """Call a handler with a properly-built ToolContext. ToolContext is
    a dataclass requiring notes, dry_run, tool_name — this mirrors what
    dispatch_tool builds internally."""
    import asyncio
    from mcp_tool_kit import ToolContext
    from mcp_tool_kit.notes import NotesCollector

    def _invoke(tool, args):
        ctx = ToolContext(notes=NotesCollector(), dry_run=False, tool_name=tool.name)
        result = tool.handler(args, ctx)
        if asyncio.iscoroutine(result):
            return asyncio.run(result)
        return result

    return _invoke
```

`tests/contract/test_<tool>_contract.py`:

```python
"""Contract for the ``<tool>`` MCP tool."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from mcp_tool_kit import ToolResult

pytestmark = pytest.mark.contract


def test_schema_requires_<field>(tool_by_name) -> None:
    tool = tool_by_name("<tool>")
    with pytest.raises(ValidationError):
        tool.schema()


def test_schema_forbids_extra(tool_by_name) -> None:
    tool = tool_by_name("<tool>")
    with pytest.raises(ValidationError):
        tool.schema(<valid>, unexpected="boom")


def test_happy_path_emits_canonical_token(tool_by_name, invoke) -> None:
    tool = tool_by_name("<tool>")
    result = invoke(tool, tool.schema(<valid>))
    assert isinstance(result, ToolResult)
    assert result.text.startswith("<canonical prefix>")
```

## Irreversible-tool dry-run contract

A tool registered with `irreversible: true` gets an auto-paired `<tool>_validate` companion. The companion calls the same handler with `dryRun=true`, so the handler must check `ctx.dryRun` and short-circuit before any external side effect.

Canonical handler shape:

```typescript
handler: async ({ subject, start, end }, ctx) => {
  // Build the request and validate inputs — these are reversible.
  if (ctx.dryRun) {
    return { text: `WOULD <action> ...` };
  }
  // External call lives below the dry-run guard.
  await graphPost('/events', { /* ... */ });
  return { text: `<action complete>` };
}
```

The contract test locks this in:

```typescript
it('dry-run via _validate triggers no side effect', async () => {
  const { tools } = buildServer();
  await tools.<tool>_validate.handler({ /* valid args */ });
  expect(graphPost).not.toHaveBeenCalled();
});
```

## Baseline-shrink workflow

The G1 gate (the `interface_has_contract_test` fitness check) lists uncovered interfaces in its baseline file (`.architecture/baseline/interface_has_contract_test-ids.txt`) and fails the PR when a NEW (non-baseline) interface lands without coverage. Each PR that adds contract tests also removes the matching IDs from the baseline.

```bash
git checkout -b shrink/g1-<server>-<group>-contract-tests

# 1. Write tests using the skeletons above.
$EDITOR agentic/tools/mcp/<server>/test/contract/<group>.contract.test.ts

# 2. Verify locally.
pnpm --filter <server-pkg-name> test test/contract/<group>.contract.test.ts

# 3. Remove the matching interface IDs from the baseline.
$EDITOR .architecture/baseline/interface_has_contract_test-ids.txt

# 4. Confirm the gate sees the shrink.
python3 scripts/checks/interface_has_contract_test.py

# 5. Commit — both the test file AND the baseline edit go in one commit.
git add agentic/tools/mcp/<server>/test/contract/<group>.contract.test.ts
git add .architecture/baseline/interface_has_contract_test-ids.txt
git commit -m "test(<server>): contract tests for N <group>_* tools — G1 shrink"
```

When the same PR also touches production source (adds a tool, edits a handler), regenerate the inventory in the same commit:

```bash
python3 tools/interface-inventory/generate.py
git add docs/standards/public-interface-inventory.yaml
git commit --amend --no-edit
```

The `inventory_is_freshly_generated` gate enforces this — its FAIL message points back here.

## Parallel-PR conflict on the baseline

Two contract-test PRs whose removed lines are adjacent will conflict on the baseline file. Resolve by accepting both deletions — both interface sets are covered, both belong out of the baseline.

```diff
-mcp-tool-ts.<server>.<group_a>_*    # removed by PR A
-mcp-tool-ts.<server>.<group_b>_*    # removed by PR B
```

Rebase the later PR on the merged trunk, accept both deletions, run the gate to verify, force-push.

## How the G1 gate matches files

Each inventory entry declares one or more globs:

```yaml
expected_test_globs:
  - agentic/tools/mcp/<server>/test/contract/<tool>.contract.test.ts
  - agentic/tools/mcp/<server>/test/contract/*.contract.test.ts
```

The gate evaluates each glob:

- **Exact filename** (no `*` or `?`) — the interface is covered when a file at that path exists.
- **Wildcard** — a candidate file matches the glob, AND the matched file's content contains the tool name as a substring.

The wildcard's content check lets grouping conventions work cleanly: `calendar.contract.test.ts` covers all 5 `calendar_*` tools because the file mentions each name. A contract file that doesn't mention a tool doesn't cover that tool, even when its filename matches the wildcard.

## File-location conventions

| Language | Path |
|---|---|
| TypeScript MCP | `agentic/tools/mcp/<server>/test/contract/<group>.contract.test.ts` |
| Python MCP | `agentic/tools/mcp/<server>/tests/contract/test_<tool>_contract.py` |

(TS uses `test/` singular; Python uses `tests/` plural — each follows its ecosystem's convention.)

## Mock scope

Mock the EXTERNAL adapter the tool calls — the Graph client, the file system, the network. The MCP SDK and `define_tool` itself stay real; the contract IS the registrar's behaviour against a working SDK.

## Pass example — clear G1 by writing the contract test

Write the contract test using the skeleton above, then make the file discoverable by EITHER (a) naming it `<new_tool>.contract.test.ts` so the exact glob matches, OR (b) naming it `<group>.contract.test.ts` and including the literal string `<new_tool>` in the file body so the wildcard glob matches. Run the `interface_has_contract_test` fitness check to confirm G1 passes.

_Compare against the shape G1 rejects: a new `mcp-tool-ts.<server>.<new_tool>` appears in the inventory; `expected_test_globs` lists `<server>/test/contract/<new_tool>.contract.test.ts`; no file at that path exists and no wildcard-matched file mentions `<new_tool>`; and the `interface_has_contract_test` baseline does not list the id. G1 fails the PR in that shape._

## Operator-outcome tests (F30)

Every surface the inventory lists as `argparse-cli` / `shell-entrypoint` / `mcp-tool-*` must also carry at least one **operator-outcome** test (the `operator_outcome_tests` gate, kairix F30): one that exercises the surface end-to-end and asserts on captured **output content**, not just the return code. G1 proves the tool is wired; F30 proves it actually runs and says what an operator expects.

For an argparse CLI the qualifying test MUST:

- `subprocess.run([sys.executable, "scripts/checks/<name>.py", …])` with the **literal script-path string inline in `args[0]`** — the gate's AST matcher reads string constants inside the call, so a `Path` variable or a module-level constant is invisible and the test does not count;
- live in a file matching the surface's `expected_test_globs` (e.g. `tests/fitness/test_<name>*.py`);
- assert on `result.stdout` / `result.stderr` content (`assert "PASS <gate>" in result.stdout`) — never `assert result.returncode == 0` alone, and never an internal-fake assertion (`assert mock_x.called`).

Run the `operator_outcome_tests` fitness check to confirm; the gate names every surface still missing one.
