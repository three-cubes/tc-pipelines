---
type: standard
status: adopted
date: 2026-05-17
owner: platform
applies_to:
  - all-engineering
  - all-agents
extends: subagent-orchestration.md
purpose: >
  Capture the 2026-05-17 sprint learning that when work decomposes into three
  or more genuinely independent streams, the parent agent should dispatch
  parallel sub-agents and integrate, rather than performing the work serially.
  Extends `subagent-orchestration.md` with the parallel-dispatch heuristic and
  the integration discipline that makes it safe.
---

# Sub-agent orchestration lessons — 2026-05-17 sprint

## Headline rule

**Default to parallel, phase only on real dependencies.**

If the work breaks cleanly into three or more streams whose file footprints
do not overlap and whose outputs do not feed each other, dispatch parallel
sub-agents. Serial execution in that situation is a tax on the user.

This extends — does not replace — `subagent-orchestration.md`. All
parallelism rules in the parent standard (no parallel git ops, no live ops
from sub-agents, bounded output, single owner) still apply.

## 5-step sub-agent dispatch checklist

Before launching parallel streams the parent agent confirms each item:

1. **Brief** — every stream gets a delegation brief (task sentence, success
   criteria, output path, context, failure path, return protocol, acceptance
   rule). Per `subagent-orchestration.md` §Delegation brief minimum.
2. **No git** — the brief states explicitly that the sub-agent must not
   `git add` / `git commit` / `git push` / `git checkout` / `git switch`.
   Parent owns all git ops; sub-agents write files only.
3. **Bounded output** — the brief names an exact artefact path or a return
   word-budget (typically under 500 words). Sub-agents that ramble blow the
   parent's context window.
4. **BDD / test discipline** — implementation streams write tests with their
   code; the parent does not accept a stream's claim of "done" without
   evidence (test output, gate result, file diff). Same standard as the
   parent's own work.
5. **Integration phase** — the parent reserves the final phase for stage +
   run gates (`make check`, scoped tests) + commit + push. Sub-agents
   complete; the parent integrates.

## When NOT to spawn sub-agents

- The whole change fits in **one coherent commit** and one mental model.
- There are **two or fewer** small tasks — the dispatch overhead exceeds the
  parallelism gain.
- Streams have **real dependencies** (stream B reads stream A's output) — phase
  serially; parallel dispatch creates false confidence.
- The work involves **live VM state** or **destructive ops** — parent retains
  direct control per `security-framework.md`.

## Integration discipline

Once sub-agents return, the parent:

1. Reads each stream's reported artefacts and verifies the files exist.
2. Stages all changes (`git add` with explicit paths, not `-A`).
3. Runs `make check`. fix: address failures before merging streams. next:
   re-run.
4. Composes a commit message that names each stream and what it landed.
5. Pushes to the trunk branch.

Failure in any stream surfaces to the parent's commit message — partial
integrations are explicit, not hidden.
