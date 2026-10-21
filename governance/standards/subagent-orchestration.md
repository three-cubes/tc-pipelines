# Sub-agent orchestration standard

Sub-agents protect the main session's context window and let independent analysis happen in parallel. They do not remove the parent agent's accountability for integration quality.

## Principles

- **Bounded output:** every sub-agent gets an exact artefact path or return signal.
- **Single owner:** the parent agent integrates results and owns final quality.
- **Read-only by default:** prefer read-only inventory, audit and review tasks unless an implementation slice is truly independent.
- **No parallel git operations:** branch, commit, merge and PR operations stay with the parent agent.
- **No live operations:** sub-agents must not deploy, restart services or mutate live config unless explicitly authorised and designed for that operation.
- **Preflight the allowed set:** confirm the target sub-agent id is in this session's allowed set before spawning; the set is session-scoped. See [§Spawn preflight](#spawn-preflight).
- **Failure path required:** each delegation says what to do if blocked.
- **Scoped loop:** each sub-agent runs its own orient → frame-done → check instance on its slice (the agent operating loop); the parent keeps the outer loop and integrates.
- **Parent owns effectiveness:** the parent specifies the capability and source-of-truth the sub-agent needs; under-specified delegation is the parent's defect, not the sub-agent's.

- **Match model + thinking to the task, defaulting high:** delegated planning, engineering, analysis and review run at a high-capability model + high thinking — that is what a high-capability subagent-model default provides, so a spawn is capable unless the parent *explicitly* downgrades. Downgrade to a small model + low thinking ONLY for genuinely trivial delegations (a one-line smoke test, a mechanical lookup). A weak sub-agent on a substantive task yields low-quality output the parent must redo, and wasted retries — the opposite of why we parallelised.

## Practical parallelism guide

| Task type | Parallelism | Rule |
|---|---:|---|
| Read-only file inventory / comparison | High | Safe when outputs are separate files and no tools mutate shared state. |
| Documentation triage | Moderate | Use clear output paths and avoid duplicate coverage. |
| Code implementation | Low | Only when file ownership is non-overlapping. Parent integrates. |
| Build/test/validation | 1 | Sequential only; avoid resource contention and contradictory results. |
| Git operations | 1 | Parent only. |
| Live deploy/restart/config apply | 1 | Parent only, explicit approval required. |

## Delegation contract

Every delegation carries one contract — whether **inter-agent** (an orchestrator
agent → a delegate agent via board card + brief) or **intra-agent** (a primary
spawning an in-process sub-agent). The contract is the sub-agent's slice of the
operating loop: the parent frames the sub-agent's
done, names what it orients on, and names the capability it uses, so the
sub-agent can run orient → done → check on its slice.

Every sub-agent task must include:

1. **task sentence** — the one thing to produce;
2. **success criteria / definition-of-done** — the typed conditions the
   sub-agent checks its result against and returns evidence for;
3. **output path/format/audience** — where the result lands and its shape;
4. **context and constraints** — what it must know, what it must not touch;
5. **source-of-truth to orient on** — the canon/file/data to ground in first, so
   it does not re-derive or wander;
6. **capability to use** — the skill(s) or ToolPack intent for the slice; the
   sub-agent selects the declared route, invokes context-augmentation first, and
   does not improvise with undeclared tools;
7. **failure path** — what to do when blocked (return with the specific blocker;
   never stall, never silently narrow scope);
8. **return protocol** — how and when to hand the result back;
9. **acceptance rule** — how the parent decides the returned work is done.

Items 5 and 6 are the difference between an effective sub-agent and a
skill-blind one. **The parent owns sub-agent effectiveness: under-specified
delegation is the parent's defect, not the sub-agent's.** A sub-agent that used
the wrong tool or returned thin work was, in almost every case, handed a brief
missing its source-of-truth (5) or its capability (6).

When the source-of-truth is a work-tracker item, the delegation includes its
concrete issue identifier or URL. The sub-agent reads that item first, then
searches or lists related items as needed. Follow-up work addresses items and
projects by the returned ids, not by title.

See `delegation-brief` skill for the full format.

## Test-first sub-agent specs

A sub-agent spec for any behaviour change is test-first by construction: name the
target behaviour, write the tests, prove they fail against the current behaviour,
then implement to green. The sub-agent returns the captured red-before-green
evidence — the failing run and the passing run — as its definition-of-done proof;
a task closes only on a green run preceded by a red one.

Order the spec so the test precedes the implementation:

1. **behaviour** — the exact input → observable output the change must produce;
2. **failing test** — write the test(s) that assert that behaviour;
3. **red proof** — run them against the current code and capture the FAIL, failing
   for the stated reason rather than a setup error;
4. **implement to green** — make the minimal change that passes;
5. **return red-before-green** — hand back both captures (the red run, then the
   green run) plus the diff.

Paste this skeleton into the delegation prompt:

```
Behaviour: <input> → <observable output>.
1. Write a test asserting that behaviour.
2. Run it against the current code; capture the FAIL (it fails for the stated reason).
3. Implement the minimal change to make it pass.
4. Return: the red run, the green run, and the diff.
Definition-of-done: red-before-green evidence attached; every green has a prior red.
```

**Self-check.** Lead every spec with the failing test. Rewrite a spec worded
"fix X, then write tests" before spawning, so the test observes the old behaviour
fail before the change turns it green.

**Layering.** This spec shape is the layer-4 process control that pairs with the
layer-2 gates: the gates require a changed line to carry a test; the spec makes the
sub-agent prove that test failed first. Canon:
[`agent-process-controls.md`](agent-process-controls.md).

## Scoped sub-agent types (lanes)

A **bare ACP slot** (`claude`, `codex` in `agents.list`) is an external-CLI shell
with no identity, tools, skills, or knowledge — the parent supplies everything at
spawn time. A **scoped sub-agent type** (a *lane*) is instead a native runtime
agent whose config **pins its capability and knowledge up front**, so a primary can
hand it a one-line task without re-teaching it the job:

- **`slide-builder`** — pinned to `presentation-production` + `deliverable-renderer`
  (the governed render path). Builds **exactly one slide** — its contract, then a
  governed render + inspection — from a bounded prompt, and returns a **verdict only**
  (pass/revise + reason + artefact path). Never python-pptx / PptxGenJS / template
  hacking; if the render path is unavailable it stops with a `capability_blocked`
  finding rather than substituting a renderer.
- **`research-lane`** — pinned to `deep-research-protocol` + the `research-pack`
  skills. Runs deep research over **one section's questions** and returns a **bounded,
  cited evidence brief** (claims + sources + confidence), not a drafted deck.

A lane profile pins three things in `agents.list[<lane>]`:

1. **skill set** — a non-empty `skills` array (the lane's bounded toolkit);
2. **knowledge scope** — a dedicated `workspace` (so it does not inherit the
   orchestrator's workspace; the lane's standing role lives in that workspace's
   bootstrap files, never in `systemPromptOverride`, which is banned platform-wide
   because it wipes the SOUL/AGENTS/MEMORY bootstrap);
3. **no onward spawn** — `subagents.allowAgents: []` (a lane is a leaf at
   `maxSpawnDepth: 1`).

A lane is **not a primary**: it has no `bindings[]` channel entry, so it is never
directly addressable and is reachable only as a spawn target. A primary may spawn a
lane or a bare ACP slot, **never another primary** (no-primary-spawn-of-primaries —
that would leak a full identity and risk recursion). Wire a lane into a primary by
adding its id to that primary's `subagents.allowAgents`.

**Spawn contract (the parent verifies live).** A primary dispatches one bounded unit
of work per spawn — e.g. one slide row or one section's questions:

```
subagents(action='spawn', agentId='slide-builder', prompt='<the one slide's row/spec>')
subagents(action='spawn', agentId='research-lane',  prompt='<the one section's questions>')
```

The parent integrates the verdict-only / evidence-brief returns and owns final
quality; per the principles above it also owns all git ops and any live operations.

**Static guard.** A config-coherence fitness check (e.g. `openclaw_subagent_type_coherence`,
D15) fails the build if any `subagents.allowAgents`
target does not resolve to an `agents.list` entry, names a channel-bound primary, or
is a lane that omits its `skills` / `workspace` or re-enables onward spawning — so a
mis-wired delegation is caught before it reaches a live spawn.

## Spawn preflight

The allowed sub-agent id set is **session-scoped**: this session's agent config
fixes it, and it varies between sessions. The runtime rejects a spawn to an id
outside that set before any sub-agent exists. Run this preflight on every spawn:

1. **Query the allowed set first.** Call the runtime's allowed-subagents query
   before spawning, and spawn only with an id returned for this session.
2. **Read the set live each time.** Take the id from the current query result
   rather than from your own agent name or an id seen in an earlier session.
3. **Gate any wait on spawn success.** Yield or wait for completion only after the
   spawn reports success.
4. **On rejection, report and act.** Return one actionable line naming the
   attempted id and the allowed set, then retry with an allowed id or do the work
   inline in this turn, e.g.
   `spawn rejected: 'research-lane' not allowed (allowed: claude, codex) — retrying as 'claude'`.

The preflight sits **inside** the delegation contract. It changes only *which* id
the parent spawns and *whether* it waits; the lane or slot contract still sets the
sub-agent's capability. The parent still owns integration and final quality, all
git operations, and every live operation.
