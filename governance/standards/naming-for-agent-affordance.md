---
type: standard
status: adopted
date: 2026-05-28
owner: platform
applies_to:
  - skill-naming
  - mcp-server-naming
  - mcp-tool-naming
  - toolpack-naming
  - capability-naming
  - cli-tool-naming
supersedes: none
layered_above: repo-ia-and-naming.md
---

# Naming for Agent Affordance

Every name an agent, a client, or you ever see is a **contract**. If a name only makes sense to the engineer who wrote the code underneath it, the abstraction has leaked. This standard governs the **semantics** of names — what a name communicates about the work being done. The syntactic rules (kebab-case, snake_case, file extensions) live in [`repo-ia-and-naming.md`](repo-ia-and-naming.md). Apply both: this one decides *what* the name should be; that one decides *how* it is spelled.

This standard applies at every surface where an agent or client discovers, selects, or invokes a capability. It does not apply below that surface — internal module names, package directories, helper scripts an agent never sees can remain implementation-flavoured.

## Why this exists

Names like `mcp-deck-render-ts`, `office-production`, `git-ops`, `kv-read`, `error-diagnosis-protocol` describe the **engineering shape** of the thing — its tool stack, its file format, its language, the developer's mental model. They tell an agent nothing about the **work** it is being asked to do. When an agent has to read every SKILL.md and every MCP tool list to figure out what a name means, the catalogue has become a quiz, not an affordance.

The lesson surfaced from the deck-render stack: two MCP servers (`mcp-deck-render` Python + `mcp-deck-render-ts` TypeScript) bundled under a skill called `office-production`, exposed to agents who have to infer that "produce-pack" means "use the skill, not the MCPs, and definitely not the file-format thing the skill is named after". Three layers of name, three different framings, zero coherence. The architecture is correct; the names are not.

## The four principles

### 1. Name by intent, not by implementation

The name should describe **the work the agent is being asked to do**, in the language the work is done in. Not the tool. Not the library. Not the engineering stage. The enforcement of this principle at the package-name layer is locked in the repo's public-names ADR (ADR-029 D1) — every published package, MCP server directory, MCP tool name, skill name, and capability binding name describes the work; language suffixes at user-facing surfaces are forbidden.

| Anti-pattern | Why it leaks | Intent-aligned direction |
|---|---|---|
| `deck-render` | Names one stage of a longer pipeline | `pack-author`, `evidence-brief` |
| `office-production` | Names a file-format family | `client-pack`, `decision-pack` |
| `kv-read` | Names the tool (Azure Key Vault) | `secret-retrieval` |
| `tmux` | Names the engineering library | `interactive-session-control` |
| `error-diagnosis-protocol` | Engineering-stage jargon | `failure-analysis` |
| `pdf-extract` | Names the input format | `document-content-parsing` |

### 2. No language or technology suffixes at user-facing surfaces

`-ts`, `-py`, `_v2`, `-azure`, `-graph` (when meaning Microsoft Graph) belong in **package metadata, internal module names, and engineering directories** — never in an MCP name, capability name, skill name, ToolPack manifest, or anywhere an agent's tool catalogue surfaces. If the suffix shows up on a surface an agent reads, the abstraction has failed.

A capability that needs more than one implementation language collapses into ONE MCP server per the public-names ADR (ADR-029 D2) — language-specific helpers live under `internal/<language>/` sub-paths and communicate via subprocess + JSON (D4). Mirrored developer libraries collapse to one package name with sub-paths (D3). The MCP boundary is the encapsulation point; the split lives below the surface.

### 3. Use shared language across you, the agents, and the clients

The audience is not the engineer. Pick verbs and nouns from the **business / consulting / craft** vocabulary the work belongs to, not from the toolchain. Consulting examples:

- *Compose*, *produce*, *brief*, *pack*, *review*, *evidence*, *story* — consulting words
- *Render*, *build*, *process*, *parse*, *sync* — engineering words

Engineering verbs are fine **for engineering work** (`apply-config`, `restore-crons`, `vm-bootstrap` — these address engineering tasks, named at engineering surfaces). Use them when the audience is the engineer; never when the audience is the agent doing consulting work.

### 4. The skill name should answer "what kind of work is this?"

Not "what file does it produce?", not "what tool stack runs under it?", not "what stage of the workflow does it belong to?". The skill name is the **highest-leverage decision** in the whole stack — every capability binding, every tool name, every ToolPack reference cascades from it. Settle the skill name first, then derive everything below.

If you can finish the sentence *"This skill helps the agent ___"* with the skill name slotted in unchanged, the name is intent-aligned. If you need to translate, it isn't.

## Rules

1. **Skill names** describe the work, not the output. Use the shared business vocabulary. Examples of good: `presentation-production`, `business-case-builder`, `competitive-positioning`, `executive-research-prep`, `delegation-brief`. Examples of bad: `office-production`, `pdf-extract`, `html-deliverable`, `tmux`, `kv-read`.

2. **MCP server names** describe the *capability the server provides*, not the library it uses or the language it's written in. Bad: `mcp-deck-render-ts`, `mcp-dex`, `mcp-graph`, `mcp-microsoft-workplace` (umbrella name — too broad to route by intent). Good (direction): `mcp-pack-renderer`, `mcp-contact-relationships`, `mcp-outlook`, `mcp-sharepoint`, `mcp-powerpoint`.

3. **MCP tool names** describe the action in agent-relevant language. Bad: `build_slide`, `qa_slide`, `inspect_template`. Good (direction): `compose_slide`, `review_slide`, `inspect_brand_template`. Verbs come from the work, not the engineering stage.

4. **ToolPack manifest names** describe the bundle of work, not the agent that uses it. Bad: `builder-ops` (names the consumer). Good: `platform-operations`, `client-pack-production`.

5. **Capability names inside a ToolPack** describe what the agent is asking for, in the agent's voice. Bad: `build-powerpoint-deck`. Good: `produce-client-pack`.

6. **CLI script names** can be more permissive — operators are the audience, engineering verbs are appropriate. `apply-config.sh` is fine. `gen-agent-files` is fine. `run-thing.py` is not — even for operators, the name should say what it does.

7. **Internal module / package / directory names below the surface** — no constraint from this standard. Use whatever the engineering team finds clearest. `mcp_deck_render` as a Python package directory is fine *if* the user-facing MCP name is intent-aligned.

8. **Renames must not break wire contracts silently.** When a skill / MCP / tool name changes, update every reference in one PR: the implementation directory, the runtime config template, `start.sh` paths, `agent.config.yaml` references, ToolPack bindings, BDD scenarios, ADRs that quote the name, and the generator templates so regenerated agent files use the new name. Use the move-policy checklist in [`repo-ia-and-naming.md`](repo-ia-and-naming.md) §Move policy as the audit checklist.

## How to apply when authoring

Before naming a new skill, MCP server, MCP tool, or capability, ask in order:

1. *What is the work the agent is doing?* — answer in one phrase, in the language of the work.
2. *Is this name something you would say to a client?* — if not, reconsider.
3. *Does the name betray the tool stack, the file format, the language, or the engineering stage?* — if yes, rename it before writing the code.
4. *Could I drop the prefix / suffix and still understand it?* — if yes, drop them.
5. *Will the next agent inheriting this catalogue know what this name means without reading the source?* — if not, the abstraction has failed.

## What is *not* changing

- The syntactic rules in [`repo-ia-and-naming.md`](repo-ia-and-naming.md) — kebab-case, snake_case, file conventions all still apply.
- Engineering-internal directory and module names — below the user-facing surface, no constraint from here.
- Operator-facing CLI scripts addressed to engineers — engineering verbs are fine.
- The conventional uppercase files (`AGENTS.md`, `SOUL.md`, etc.) — platform conventions stand.

## Enforcement

A fitness check (e.g. `no_language_suffixes_at_surface`) fails any new MCP server / skill / capability whose name ends in `-ts`, `-py`, `-azure`, `-graph` etc. at the registration surface. Intent-vs-implementation is harder to mechanise — the gate for that is review discipline: every PR that adds a new agent-visible name must justify the name in the PR description ("this skill helps the agent ___").
