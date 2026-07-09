---
type: standard
status: adopted
date: 2026-05-10
owner: platform
applies_to:
  - cli
  - mcp-tools
  - skills
  - deployment-pipelines
  - quality-harness
  - bdd
  - consulting-engagement-management
  - content-production
---

# Agent-Actionable Feedback Standard

Agent-facing systems need UX contracts just as much as human-facing systems do. For an agent, the return message is the product surface: it determines whether the next turn moves toward the goal or falls backward into diagnosis.

This standard applies to CLIs, MCP tools, skills, deployment scripts, CI/CD checks, BDD harnesses, consulting engagement management workflows, LinkedIn/content-production pipelines, and executive-material production gates.

## Core rule

Every failure or blocked response must tell the agent:

1. **The fix** — lead with the concrete action that resolves the violation. Do not lead with what happened — the agent already sees the violation; what they need is the next move.
2. **What to do next** — the next smallest step (re-run a script, re-check, etc).
3. **The exact command** — copy-pasteable invocation that gets back to green.
4. **Pass / Forbidden examples** — concrete code (not prose) showing the right and wrong shape, where the rule has a code-shaped output.

Do not return only "what is wrong" or a long list of what NOT to do. A diagnostic-only message makes the agent restart investigation. An action-led message lets the agent continue.

## Canonical shape (2026-05-17 — adopted from kairix)

```
<Lead with the fix as one sentence ending "— to pass.">

fix: <concrete replacement code / pattern; name the helper / class / module>
next: re-run `<exact command>` to confirm the gate goes green.
run: bash scripts/safe-commit.sh "<conventional-commit message>"

Pass example:
  <code that shows the right shape>

Forbidden example:
  <code that shows the violation>

<optional one-paragraph rationale — only when the WHY isn't obvious from the examples>
```

**Lead-with-fix, not lead-with-violation**: the first sentence names the destination ("Refactor to constructor injection on a Deps dataclass — to pass."), not the offence ("Production source changed without a paired test."). The violation is what the agent already sees; what they need is the path forward.

## Structured envelope shape (2026-05-24 — extended with `try:`)

Tools and CLIs that emit structured errors follow this canonical field order:

```json
{
  "ok": false,
  "error": {
    "code": "no_results | invalid_input | forbidden | not_found | rate_limited | backend_error",
    "what": "Brief description of the failure condition.",
    "hint": "Background detail that helps the agent understand the failure shape.",
    "try": "kairix search \"<query>\" --agent <calling-agent>",
    "fix": "Concrete next move that resolves the condition.",
    "next": "Smallest verification step that proves recovery.",
    "run": "Copy-pasteable command that drives the verification."
  }
}
```

Field order in source and in serialised output: `code`, `what`, `hint`, optional `try`, `fix`, `next`, `run`, optional `Pass example:`, optional `Forbidden example:`.

### Use `try:` to route to a sibling tool

Set `try:` when the failure pattern matches a recovery the agent should attempt FIRST — before retrying the current tool. The canonical use case is empty-result envelopes from narrow tools: a `dex_search` empty hit recovers fastest via `kairix search`; an empty `kairix search` recovers via `perplexity_search`. Pick the `try:` value from the tool-routing guide — it names every sibling-bridge pair the platform supports.

Lead the `try:` with the imperative command. The agent reads `try:` as "run this next call before reasoning further".

**Pass example:**

```json
{
  "ok": false,
  "error": {
    "code": "no_results",
    "what": "No matching contacts in Dex for query 'jordan'.",
    "hint": "Dex stores name + company + title; substring matching is case-insensitive.",
    "try": "kairix search \"jordan\" --agent <me>",
    "fix": "Refine the query — try last name or company name.",
    "next": "Run dex_search with the refined query."
  }
}
```

**Forbidden example:**

```json
{
  "ok": false,
  "error": {
    "code": "no_results",
    "what": "No contacts found.",
    "fix": "Try a different query."
  }
}
```

The forbidden shape forces the agent to re-investigate from scratch; the pass shape names the local fallback (`try: kairix search`) AND the eventual next move (`fix: refine the query`).

### Fitness-function coverage for `try:`

the `actionable_feedback_try_hint_coverage` check scans `defineErrorMapping(table)` declarations across MCP packages. It fails when an entry whose `code` resolves to `no_results`, `not_found`, or `empty` is missing a `tryHint`. The baseline at `.architecture/baseline/actionable_feedback_try_hint_coverage-ids.txt` shrinks PR-by-PR (never grows).

**Forbidden phrasing patterns** (waste context, agents skip them):
- "this was previously deprecated because…"
- "in 2023 we moved away from X…"
- "don't do Y; instead Z" (lead with Z; the don't-do-Y phrasing makes the agent parse the wrong shape first)
- multi-paragraph history lessons
- bullet-lists of every related rule

Every word in a remediation should be directly actionable. If you can delete a sentence and the agent can still get back to green, delete it.

## Output modes

Default output should be short. Do not make every response verbose just because the system can provide detail.

### Default text

Use one actionable line per failure:

```text
<path-or-scope>: <what happened>; fix: <concrete correction>; next: <command or next step>
```

### `--json`

CLIs should expose structured detail for agents/automation:

```json
{
  "ok": false,
  "code": "missing_input | invalid_input | blocked | drift | unsafe | unavailable | failed_gate",
  "what": "The capability manifest is missing Office Production for Growth.",
  "hint": "Growth-visible skills route through client-pack ToolPack.",
  "try": "kairix search \"client-pack growth\" --agent <agent>",
  "fix": "Add or repair the Growth-visible client-pack skill/ToolPack mapping.",
  "next": "Run scripts/build-agent-capabilities.py --json --check after the mapping change.",
  "evidence": ["agent-bootstrap/capabilities/growth.json"],
  "retryable": true
}
```

### `--verbose`

Use verbose output only for diagnostics/provenance: stack traces, rule rationale, matched patterns, baseline locations, raw provider responses, or decision context. Verbose mode should add detail without changing the default fix path.

## Good vs bad

| Bad | Good |
|---|---|
| `missing README.md` | `capabilities: missing top-level resolver README.md; fix: add capabilities/README.md explaining what belongs there; next: rerun make check` |
| `invalid input` | `country: unsupported value "Aust"; fix: use ISO country code such as "AU"; next: retry with {"country":"AU"}` |
| `deployment failed` | `infra/config/gateway.json.template: generated config failed schema validation; fix: remove unsupported agents.list[].promptOverlays; next: run apply-config.sh --dry-run` |
| `BDD route failed` | `route "make this into slides" selected document-publish; fix: map deck/presentation phrases to client-pack; next: rerun route tests for client-pack` |

## Domain applications

### MCP tools

MCP tools follow the tool UX contract: structured `{code, what, hint}` errors, validate companions for irreversible writes, coercion notes, and valid examples. This standard extends the contract by preferring `fix` and `next` in any new structured response surface.

### CLIs and deployment scripts

A CLI failure should usually include:

- failing file/path/resource,
- exact missing/invalid condition,
- command or edit to unblock,
- safe retry command.

Deployment scripts should never end with only “failed”. They should name whether the next step is: rerun dry-run, inspect generated config, fix schema, approve live apply, or escalate.

### CI/CD and quality harnesses

CI is an agent UX surface. A failing check should be a work queue item:

- what rule failed,
- which file/path failed,
- how to fix or baseline it,
- what command proves it is fixed.

Fitness functions should test their own failability and the actionability of their messages.

### BDD and consulting engagement management

BDD scenarios are not limited to software. Engagement-management workflows should have executable acceptance criteria:

- sponsor alignment present,
- next decision owner named,
- artefact has executive-ready structure,
- risks have owner/action/date,
- meeting output has next-step commitments.

Failures should return improvement instructions, not judgement. Example:

```text
Steering pack lacks decision framing; fix: add a slide or section with decision, options, recommendation, and consequence; next: rerun executive-material QA.
```

### LinkedIn/content production

Content-quality checks should behave like product tests:

```text
LinkedIn draft has generic claim without proof; fix: add a concrete observation, example, or implication from the author's own experience; next: rerun content-quality BDD checks.
```

### Executive materials

Executive-material gates should test reader outcomes:

- answer-first structure,
- decision or ask is explicit,
- evidence is sourced,
- implication is clear,
- next step is named.

Failures should instruct the agent how to repair the artefact.

## Recovery

Repair an unhelpful failure message by leading with the imperative MUST/DO. Apply each rule below to the offending surface:

- Summarise the fix path BEFORE any raw stack trace; the trace follows as evidence, not as the lead.
- State the example shape the validator expected — "Provide JSON of the form `{...}`" instead of bare "Invalid", "failed", "not found", or "wrong format".
- Name the imperative repair step in CI failures; the rule name belongs after the action ("Run `make lint --fix`; rule: ESLint react/no-unescaped-entities").
- Specify the exact improvement in BDD failures ("Restructure the executive summary to lead with the recommendation; current draft leads with context"); the quality judgment must carry the next move.
- Take the next safe technical step when it is known; reserve "ask the user" for genuine forks where the agent has no defensible default.
- Return the single smallest useful next action; rank possible causes only after the lead action has unblocked the agent.

## Fitness-function requirement

New quality-harness checks must emit errors containing at least one explicit action marker:

- `fix:`
- `next:`
- `run:`

The first implementation enforces this for the repo's fitness-check scripts. Broader enforcement for MCP tools, shell CLIs and BDD/content pipelines should be added as those surfaces standardise around structured envelopes.

## Coverage of all feedback surfaces

The standard applies wherever an agent or developer encounters a blocking state. Each surface has its own canonical affordance form:

| Surface | Canonical form | Enforced by |
|---|---|---|
| Fitness function error messages (fitness-check scripts) | `<path>: <what>; fix: <action>; next: <verify>` | the `actionable_feedback` check |
| ADR decision sections | "Controls" table mapping each decision to a fitness function. Each control gives the rule + the script that catches violation + how to fix. | `the `docs_affordance` check` (TODO) |
| `CLAUDE.md` pointer-reference rows | Common-task row includes both the canonical doc AND the failure recovery path | `the `docs_affordance` check` (TODO) |
| Standards docs (`docs/standards/*.md`) | "Fitness-function requirement" section naming what gate enforces the rule | manual |
| BDD scenarios (`tests/bdd/**/*.feature`) | Each scenario cites the source rule in a comment (`# rule: ADR-003 D4`); failure remediation is implicit in the rule citation | review |
| pytest assertions | Assertion message contains `fix:` or `next:` for any blocking failure agents would hit | review |
| Apply scripts (`infra/config/apply-*.sh`) | Failure prints which file rolled back, which validator failed, what to re-run | review |
| Scorecard FAIL lines | Each failing check emits an evidence string + `fix:` pointer to the relevant ADR or standard | per check |
| MCP tool responses | Structured `{code, what, hint, try?, fix, next, evidence, retryable}` envelope per "Output modes" section | per tool — `mcp-engineering-standard.md` + the `actionable_feedback_try_hint_coverage` check for `try` coverage |
| LLM-as-judge | Semantic affordance check on the above surfaces. Catches "syntactically correct but unhelpful". See the LLM-as-judge ADR (TODO). | the `llm_judge_affordance` check (TODO) |

## Pattern: PASS + Forbidden examples

For documentation surfaces (ADRs, CLAUDE.md, standards), the richer affordance form is the "pass example / forbidden example" pair (kairix F15-style):

```markdown
### Rule: agents must invoke kairix before answering from working memory

**Pass example:**
> "Let me check my prior context on this. *invokes kairix search* … Found 3 relevant prior sessions; the most recent says we decided X."

**Forbidden example:**
> "I recall from our last session we discussed X." (no kairix invocation; pattern-matching from training data not from durable memory)

**Why:** ADR-003 D1 — Kairix is canonical recall layer; per-session memory drifts without it.

**Control:** the `agent_memory_policy` check checks the config; runtime behaviour is verified in `tests/bdd/agents/<name>/scenarios.feature`.
```

This form gives the agent both the WHAT (rule), the WHY (rationale), and the recognition pattern (pass vs forbidden in concrete tokens the agent can match against its own behaviour).

## Default vs verbose for documentation

Documentation should default to **concise**: one sentence of rule, one sentence of "why", one pointer to the control. Verbose detail (extended rationale, supersession history, edge cases) goes in the ADR body — not in the index/pointer surface (CLAUDE.md, canonical-patterns.md).
