---
type: standard
status: proposed
date: 2026-05-17
owner: platform
applies_to:
  - all-typescript-mcp-servers
  - all-python-mcp-servers
  - mcp-tool-kit
  - mcp-tool-kit
sources:
  - ADR-017-canonical-mcp-tooling
  - ADR-010-toolpack-and-capability-pattern
  - ADR-015-js-ts-tooling-baseline
  - ADR-016-python-dependency-locking-with-uv
  - mcp-engineering-standard
  - agent-actionable-feedback
purpose: >
  Operational playbook for authoring, testing, deploying, and evolving MCP servers
  in a repo. Tells a developer how to choose TS vs Python, scaffold a new
  MCP, write the tool contract, run tests, deploy through the agent runtime, bump the SDK,
  and add a new tool to an existing MCP. The architectural decisions are in
  ADR-017.
---

# MCP Tooling Canonical Pattern — Operational Standard

> The architectural decision (language matrix, helper packages, layout, transport,
> tests-as-contract) is in ADR-017 (the canonical MCP tooling pattern).
> This document is the **operational** surface — workflows, exact commands,
> recovery paths.
>
> [`mcp-engineering-standard.md`](mcp-engineering-standard.md) is partially
> superseded by ADR-017 (build-tooling sections). The *tool-design contract*
> (structured I/O, validate companions, drop-and-warn, no raw `server.tool`)
> remains canonical there.

## Where this fits

| Layer | Surface | Where |
|-------|---------|-------|
| Architectural decision | ADR-017 | the canonical MCP tooling ADR |
| Operational playbook | this standard | this file |
| Tool-design contract | `mcp-engineering-standard.md` (still canon for tool-UX rules) | `mcp-engineering-standard.md` |
| JS/TS build tooling | `js-ts-tooling-baseline.md` (ADR-015) | the JS/TS tooling baseline standard |
| Python build tooling | `python-dependency-locking.md` (ADR-016) | the Python dependency-locking standard |
| TS helper package | `@three-cubes/mcp-tool-kit` | e.g. `tools/mcp/mcp-tool-kit/` |
| Python helper package | `mcp-tool-kit` (python sub-path) | e.g. `tools/mcp/mcp-tool-kit/python/` |

## 1. When to write a new MCP (vs a skill / plugin)

Before authoring a new MCP, confirm it earns the slot. The decision tree:

| If… | Then… |
|---|---|
| The capability is **a prompt or procedure with no executable side effect** | Write a `SKILL.md` only. No MCP. |
| The capability is **agent-local, single-agent, low-coupling, no shared auth/state** | Bash or Python skill under the repo's skills tree (e.g. `skills/<agent>/<name>/`). No MCP. |
| The capability **runs inside the agent runtime process** (mutating runtime config, intercepting prompts, augmenting context) | A runtime plugin (e.g. an openclaw plugin). See the runtime's plugin-authoring standard. |
| The capability is **a shared executable surface called by 2+ agents** OR **wraps an external API requiring typed contracts** OR **wraps a Python-native heavy dependency** | MCP server. Continue below. |

If still in doubt, the language matrix (ADR-017 D1) decides:

- **TypeScript MCP** — external API integration, app-facing tooling, browser/calendar/CRM/image-gen surfaces.
- **Python MCP** — ML/embedding/Python-native deps (`python-pptx`, `pypdf`, sentence-transformers, kairix internals).
- **Go MCP** — none today. Adoption requires satisfying the four Go-adoption conditions (CPU-bound + measured bottleneck + MCP-shaped contract + sustained Go capacity).

## 2. Authoring a TypeScript MCP

### 2.1 Scaffold

From the repo root:

```bash
mkdir -p tools/mcp/mcp-<name>/{src/tools,test/{tools,contract}}
cd tools/mcp/mcp-<name>
```

Create the four required files:

**`package.json`** (workspace member per ADR-015 D1):

```json
{
  "name": "mcp-<name>",
  "version": "0.0.1",
  "private": true,
  "type": "module",
  "main": "dist/index.js",
  "scripts": {
    "build": "tsc",
    "lint": "eslint . --max-warnings 0",
    "test": "vitest run",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "@modelcontextprotocol/sdk": "<exact-pin>",
    "@three-cubes/mcp-tool-kit": "workspace:*",
    "zod": "<exact-pin>"
  }
}
```

Exact pins only — no `^` / `~` per ADR-015 D10. Resolve current pins from an existing TS MCP (e.g. `mcp-outlook/package.json`).

**`tsconfig.json`**:

```json
{
  "extends": "../../../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "dist",
    "rootDir": "src",
    "strict": true,
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext"
  },
  "include": ["src/**/*"]
}
```

**`vitest.config.ts`** (required even when minimal):

```ts
import { defineConfig } from "vitest/config";
export default defineConfig({ test: { include: ["test/**/*.test.ts"] } });
```

**`src/index.ts`** — launcher only, no `defineTool` calls:

```ts
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { registerTools } from "./server.js";

const server = new McpServer({ name: "mcp-<name>", version: "0.0.1" });
registerTools(server);
const transport = new StdioServerTransport();
await server.connect(transport);
```

**`src/server.ts`** — tool registration aggregator:

```ts
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { registerExampleTools } from "./tools/example.js";

export function registerTools(server: McpServer) {
  registerExampleTools(server);
}
```

**`src/tools/example.ts`** — `defineTool` calls live here:

```ts
import { defineTool } from "@three-cubes/mcp-tool-kit";
import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

export function registerExampleTools(server: McpServer) {
  defineTool(server, {
    name: "example_thing",
    description: "Agent-facing description with useful defaults.",
    schema: z.object({ query: z.string() }).passthrough(),
    handler: async ({ query }) => ({ result: `echo: ${query}` }),
  });
}
```

### 2.2 Add the workspace member

In `pnpm-workspace.yaml` (the glob `tools/mcp/*` should already cover it). Then from repo root:

```bash
pnpm install
pnpm --filter mcp-<name> build
pnpm --filter mcp-<name> test
pnpm --filter mcp-<name> lint
```

### 2.3 Wire into the runtime

Add an `mcp.servers` entry to the runtime's MCP config (e.g. openclaw's `openclaw.json` template):

```json
"mcp-<name>": {
  "command": "node",
  "args": ["tools/mcp/mcp-<name>/dist/index.js"]
}
```

Run the deploy dry-run (`make dry-run`) to verify the diff, then apply the runtime config after merge.

### 2.4 Anti-patterns

- Bundling (`tsup` / `esbuild`) — `tsc` only per ADR-017 D3.
- `defineTool` calls in `src/index.ts` — they belong in `src/tools/<group>.ts`.
- Raw `server.tool(...)` — always go through `defineTool`.
- A flat `src/` (no `tools/` subdir) — legacy layouts are grandfathered but new MCPs MUST split into `src/tools/`.

## 3. Authoring a Python MCP

### 3.1 Scaffold

```bash
mkdir -p tools/mcp/mcp-<name>/{src/mcp_<name>/tools,tests/{unit,contract}}
cd tools/mcp/mcp-<name>
```

**`pyproject.toml`** (workspace member per ADR-016 D2):

```toml
[project]
name = "mcp-<name>"
version = "0.0.1"
requires-python = ">=3.10"
dependencies = [
  "mcp[cli]>=1.20,<2",
  "pydantic>=2.0,<3",
  "mcp-tool-kit",  # workspace member
]

[tool.uv.sources]
mcp-tool-kit = { workspace = true }

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
```

Then from repo root: edit root `pyproject.toml` `[tool.uv.workspace] members` to add `tools/mcp/mcp-<name>`. Run:

```bash
uv lock
uv sync --frozen
```

**`src/mcp_<name>/server.py`** — registration:

```python
from mcp.server.fastmcp import FastMCP
from mcp_tool_kit import async_tool_handler, wrap_tool_errors
from .tools import example as example_tools

def build_server() -> FastMCP:
    server = FastMCP("mcp-<name>")
    example_tools.register(server)
    return server
```

**`src/mcp_<name>/tools/example.py`** — pure tool functions + decorators:

```python
from mcp.server.fastmcp import FastMCP
from mcp_tool_kit import async_tool_handler, wrap_tool_errors
from pydantic import BaseModel, Field

class ExampleInput(BaseModel):
    query: str = Field(..., description="Free-text input")

@wrap_tool_errors
def _tool_example_thing(query: str) -> dict:
    return {"result": f"echo: {query}"}

def register(server: FastMCP) -> None:
    @server.tool(description="Agent-facing description with useful defaults.")
    @async_tool_handler
    def example_thing(query: str) -> dict:
        return _tool_example_thing(query)
```

The pattern (pure function under the decorator, FastMCP-bound thin adapter on top) mirrors kairix's `server.py` adapters — keeps tests bypassing FastMCP entirely.

### 3.2 Anti-patterns

- Per-package `uv.lock` — root `uv.lock` only per ADR-016 D2.
- Pydantic v1 — Pydantic v2 required.
- Tool functions raising back to FastMCP — always wrap in `wrap_tool_errors` (the JSON-RPC `-32602` masking incident in kairix #177 motivates this).
- Mixing tool registration into `__init__.py` — `server.py` owns the registration.
- Requiring manual venv activation before the MCP can start — launchers must use the repo/package dependency manager or a declared runtime cache.
- Writing tracked generated metadata, such as `.egg-info`, into a source tree that the runtime user cannot update.

### 3.3 Python cold start and ownership

Python MCPs may be cold-started by `uv` or the package-native manager, but the
runtime contract must be deterministic:

- the runtime/gateway launcher, CLI wrapper and any direct skill bridge use the
  same module path and environment defaults;
- dependency caches live in the package-local or runtime cache location, not as
  root-owned writes to tracked source files;
- template/content roots are read from declared env vars or resolver-backed
  defaults, not from a caller-specific cwd;
- the package exposes a low-cost executable health probe that exercises imports,
  required env/template roots and one representative tool path.

If an operator repairs ownership or hydrates an env var so deployment can
proceed, record it as an operational unblock and link a durable issue. The
repair is not complete until the launcher or packaging contract prevents the
same failure from recurring.

## 4. Tool-design contract

Authoritative source: [`mcp-engineering-standard.md`](mcp-engineering-standard.md) §"Required MCP tool contract". Key rules summarised:

| Rule | TS expression | Python expression |
|---|---|---|
| Always use the helper | `defineTool` from `@three-cubes/mcp-tool-kit` | `@wrap_tool_errors` + `@async_tool_handler` from `mcp-tool-kit` (python sub-path) |
| Schema | Zod with `.passthrough()` + did-you-mean | Pydantic v2 strict |
| Errors | `ToolKitError({ code, what, hint })` | `ToolKitError(code, what, hint)` |
| Drop-and-warn unknown fields | `.passthrough()` + `NotesCollector` warning | Pydantic `model_config = ConfigDict(extra="ignore")` + log warning |
| Validate companion for irreversible | `defineTool({ irreversible: true })` auto-registers `<name>_validate` | `define_tool(irreversible=True)` mirror (post-D7) |
| Idempotency | Document in `description`; agents should be able to retry safely | Same |

## 5. Test pyramid

Per ADR-017 D9 + `testing-strategy.md`:

| Tier | Location | Asserts |
|---|---|---|
| Unit | `test/tools/<group>.test.ts` (TS), `tests/unit/test_<group>.py` (Python) | Pure function behaviour; mock no MCP internals |
| Contract | `test/contract/<tool>.contract.test.ts` (TS), `tests/contract/test_<tool>.py` (Python) | Happy-path schema, drop-and-warn path, structured error path, validate-companion path |
| Integration | `test/integration/*.test.ts`, `tests/integration/test_*.py` | Real external service when feasible, otherwise boundary fake per `mcp-engineering-standard.md` |

The contract tier is non-negotiable — gated by the contract-test presence
check (`interface_has_contract_test`, the G1 gate). Author the contract
tests alongside the tool, never after.

**Code-shape guidance lives in the contract-test-patterns standard** —
copy-paste skeletons for both TS and Python MCP tools, the irreversible-tool
dry-run contract (must honour `ctx.dryRun`), the `fs/promises`
mock-with-importOriginal trap, and the baseline-shrink workflow that
takes a new contract test from "passes locally" to "the G1 gate credits it".

## 6. Build, lint, lockfile

| Concern | Authority | Standard reference |
|---|---|---|
| TS package shape, pnpm workspace, eslint flat config | ADR-015 | the JS/TS tooling baseline standard |
| TS lint script contract (`eslint . --max-warnings 0`) | ADR-015 D5 | the JS/TS tooling baseline standard §3 |
| Python `pyproject.toml`, uv workspace, `uv.lock` | ADR-016 | the Python dependency-locking standard |
| Python lint (ruff) + type (mypy `--strict`) | ADR-017 D4 | this standard §3 |
| Quality ratchet (per-file finding non-regression) | ADR-014 | the quality-ratchet standard |

This standard does NOT re-derive build commands — delegate to the linked standards.

## 7. Deploy contract — how the runtime consumes the MCP

The runtime resolves MCP servers via its `mcp.servers` config entries (e.g. openclaw's `openclaw.json` template). For each MCP:

- The `command` + `args` must launch the built artefact (TS: `node .../dist/index.js`; Python: `<pkg> mcp serve` or `python -m <pkg>.cli`).
- The launcher MUST default to stdio transport (ADR-017 D6) — the runtime spawns the process and pipes stdio.
- Env vars (API tokens, etc.) come from the platform secret store (e.g. Azure Key Vault) via the runtime's secret provider (see the security-framework standard).
- HTTP transport is not currently supported in the runtime's launcher; defer per ADR-017 D6.

After editing the config template:

```bash
make dry-run    # verify the deploy diff includes the runtime MCP config
# After merge to main, apply the runtime config via the platform's config-apply step.
```

A `.clobbered.<timestamp>` file means the runtime's config validator (e.g. `openclaw doctor`) rejected the new template — read the validation error, correct the template, re-render.

### 7.1 Post-deploy execution proof

Deploy success is not enough. Every MCP that backs a runtime capability needs a
post-deploy proof that runs as the same runtime user and invokes the real MCP
tool path. The proof must check:

- the MCP process can start under the configured launcher;
- required env vars, credentials and template/content roots are present;
- one representative read/inspect tool returns a structured success response;
- any irreversible write tool has a validate companion route;
- the evidence path and exit code are recorded in the deployment run manifest.

For renderer-backed capabilities, the representative probe must exercise the
renderer binding rather than importing the render library directly.

## 8. Telemetry

Use the helper's telemetry sink rather than ad-hoc logging:

```ts
// TS
import { setTelemetrySink, emitTelemetry } from "@three-cubes/mcp-tool-kit";
setTelemetrySink((event) => process.stderr.write(JSON.stringify(event) + "\n"));
```

```python
# Python
from mcp_tool_kit import set_telemetry_sink
set_telemetry_sink(lambda event: print(json.dumps(event), file=sys.stderr))
```

Event shape (subject to change post-D7): `{tool: str, latency_ms: int, ok: bool, error_code: str | null, agent: str | null}`. Stdout is reserved for the MCP transport; telemetry goes to stderr.

For the current MCP surface, telemetry is **opt-in** — no MCP wires a sink in production. Future work (post-D7): standardise a stderr-JSONL sink and a vault-mounted aggregator.

## 9. Adding a new tool to an existing MCP

1. Identify the tool group. If it fits an existing `src/tools/<group>.ts` (TS) or `src/<pkg>/tools/<group>.py` (Python), add the `defineTool` call there.
2. If the new tool is a different concern, create a new `tools/<new-group>.ts` and register it from `src/server.ts`.
3. Add unit + contract tests in the matching test path. Contract tests are non-negotiable (§5).
4. If the tool mutates state irreversibly, declare `irreversible: true` so the helper auto-registers a `<name>_validate` companion.
5. Update the MCP's `README.md` (or the doc that lists its tools).
6. Run `pnpm --filter mcp-<name> {build,test,lint}` (TS) or `uv run pytest tests/` + `ruff check .` + `mypy src/` (Python).
7. Commit. The CI gates re-run; if the `mcp_contract_tests_present` check lands before this PR, ensure the contract test path matches.

## 10. Bumping the MCP SDK

The MCP SDK ships breaking changes occasionally. Bump procedure:

1. **Read the SDK changelog** for the version range you're bumping across.
2. **Bump in one PR** — update every `package.json` (TS) and every `pyproject.toml` (Python) in the same commit. The future `tools/mcp/MCP-SDK-PINS.md` (ADR-017 D5) will be the single-doc reviewer surface; until it exists, `grep -r "@modelcontextprotocol/sdk" tools/mcp/*/package.json` is the inventory.
3. **Regenerate locks**: `pnpm install` (TS) + `uv lock` (Python).
4. **Run every MCP's build + test + contract suite**. A handshake regression typically shows up in contract tests first.
5. **Smoke on the deployment target**: apply the runtime config, then run the runtime's config validator (e.g. `openclaw doctor`) + manually exercise one tool per MCP.
6. **Cite the bump rationale** in the commit body — at minimum, the SDK changelog link and any breaking changes that required adaptation.

If a single MCP can't accommodate the bump, hold the bump back across the surface — partial pinning causes silent ABI mismatches between the SDK and the helpers.

## 11. Common pitfalls

| Pitfall | Why it happens | Fix |
|---|---|---|
| An MCP has no `vitest.config.ts` | Legacy from before the standard | Add the minimal config per §2.1 |
| An MCP ships only one test file | Surface coverage gap | Add per-tool contract tests under `test/contract/` |
| Tool registered via raw `server.tool(...)` | Author bypassed `defineTool` | Replace with `defineTool` call; the auto-error-envelope is load-bearing |
| `defineTool` call appears in `src/index.ts` | Author put the tool next to the launcher | Move to `src/tools/<group>.ts` and register from `src/server.ts` |
| Tool raises an exception that surfaces as JSON-RPC `-32602` to the agent | Tool wasn't wrapped in `wrap_tool_errors` (Python) or escaped `defineTool` (TS) | Wrap. The kairix incident report (kairix #177) is the canon example. |
| `pnpm install --frozen-lockfile` fails after adding a new MCP | Member glob missed the new path, or root `package.json` didn't get the workspace bump | Verify `pnpm-workspace.yaml` glob; re-run `pnpm install` (no `--frozen-lockfile`) to regenerate |
| `uv lock --check` fails after adding a Python MCP | Member not added to root `[tool.uv.workspace] members` | Add member; re-run `uv lock`; commit `uv.lock` alongside `pyproject.toml` |
| MCP tool is visible but unusable | Env/template root differs between gateway, wrapper and direct bridge | Declare one default path/env contract and test the real MCP invocation |
| Runtime user cannot refresh Python metadata | Build wrote root-owned tracked files | Move generated metadata to cache or fix packaging; log durable issue for any one-off ownership repair |
| Skill falls back to direct library calls | MCP health was not executable or affordance allowed improvisation | Add an MCP health probe and require `capability_blocked` when unhealthy |
| MCP emits no `capabilities.json` | The helper-helper doesn't exist yet (ADR-017 D7) | Future work — track via D7 |
| MCP returns plain `"error: …"` strings to agents | Helper not used | Use `ToolKitError({code, what, hint})` per `mcp-engineering-standard.md` |
| Cold-start tool call hangs for 8s+ | The cold-start envelope helper doesn't exist yet (ADR-017 D7) | Future work — track via D7 |
| Operator-only capability returns a generic error instead of an escalation envelope | Same — D7 future work | Until then, return `{error: "OperatorOnlyCapability", operator_command: "<cmd>"}` manually |

## 12. Helper-helpers to borrow from kairix (future work)

Four idioms exist in kairix but not yet in `mcp-tool-kit`. Each is a future PR; this list is the canonical roadmap so contributors don't re-discover the gap:

1. **`coldStartEnvelope({tool_name, retry_in_seconds})`** — port from kairix `server.py:_check_warm_or_return_envelope`. Every tool checks `isWarm()` before doing work; cold tools trigger background warm-up and return a structured retry payload.
2. **`escalationEnvelope({capability, operator_command, reason, expected_runtime_seconds, see_also})`** — port from kairix `_operator_only_envelope`. Capabilities that take minutes or mutate state are MCP-registered but their handler returns a precise operator-only escalation payload.
3. **`buildMcpHealthRoutes({readiness_check, capability_probe})`** — port from kairix `transport.py:build_mcp_app`. Mountable Express/Fastify routes for `/healthz` and `/healthz/ready`; needed once HTTP transport lands (ADR-017 D6).
4. **`defineCapability` + `getCapabilities`** — port from kairix `tool_capabilities()`. First-class capability catalogue with a per-MCP `capabilities` tool that emits `capabilities.json` for the future aggregator (ADR-017 D8).

`mcp-tool-kit` (python sub-path) mirrors these four APIs at the same time (cross-language parity per ADR-017 D2). When implementing, author the TS and Python halves in the same PR.

## Stay inside the canonical pattern

- Build MCPs in TypeScript or Python; raise a fresh ADR before adding a Go MCP and demonstrate all four Go-adoption conditions are met.
- Keep `@three-cubes/mcp-base` and `three-cubes-mcp-base` inside the originating repo until a second consumer exists outside it; extract to npm / PyPI then.
- Build TS MCPs with `tsc` and Python MCPs with setuptools; skip bundlers — they obscure provenance in stack traces.
- Place every `defineTool` call under `src/tools/<group>.ts` (TS) or `src/<pkg>/tools/<group>.py` (Python) per ADR-017 D3/D4; register them from `src/server.ts`.
- Ship a `test/contract/<tool>.contract.test.ts` (or `tests/contract/test_<tool>_contract.py`) alongside every tool; the contract test IS the tool's contract.
- Pin the MCP SDK to an exact version in `package.json` / `pyproject.toml`; avoid `^` and `~` ranges that drift the SDK under you.
- Use the root `pnpm-lock.yaml` and root `uv.lock` per ADR-015 / ADR-016; remove any per-package lockfile you find.
- Land HTTP transport surface only with a named consumer AND an auth story documented in the PR; otherwise stay on stdio transport.
- Port idioms from kairix by re-implementing them in the consuming repo; kairix source is read-only per the cross-repo change-management rule, so direct imports are out.

## References

- ADR-017 (the canonical MCP tooling pattern) — architectural decisions (D1-D10).
- [`mcp-engineering-standard.md`](mcp-engineering-standard.md) — tool-design contract (in force, with build-tooling sections partially superseded by ADR-017).
- ADR-015 + the JS/TS tooling baseline standard — TS build tooling.
- ADR-016 + the Python dependency-locking standard — Python build tooling.
- The agent-actionable-feedback standard — `fix:`/`next:`/`run:` requirements for MCP error envelopes and CI output.
- The testing-strategy standard — overall test pyramid (contract-enhanced).
- MCP Python SDK: <https://github.com/modelcontextprotocol/python-sdk>
- MCP TS SDK: <https://github.com/modelcontextprotocol/typescript-sdk>
