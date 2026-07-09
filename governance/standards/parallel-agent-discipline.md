---
type: standard
status: adopted
date: 2026-05-15
owner: platform
applies_to:
  - subagent-spawning
  - worktree-isolation
  - parallel-execution
  - branch-coordination
addresses_incidents:
  - "Parallel git ops causing branch swaps + manifest merge conflicts (2026-05-15)"
  - "Sub-agent invented model identifiers without reading live state (2026-05-15)"
---

# Parallel agent discipline

The companion standard to [`subagent-orchestration.md`](subagent-orchestration.md). Where that document names the *rules*, this one names the *failure modes* observed in practice and the *defences* that prevent them.

Drafted because an early parallel-execution session repeatedly violated rules that already existed in canon — see the "Incidents" section below. The standard exists now so the next session can read it once and avoid the same footguns.

## Rule 1 — Read live state before encoding it

**The incident.** A sub-agent was asked to fill in `agent.config.yaml` `model:` blocks. It invented `claude-opus-4-7` for all 6 agents from training data, without ever reading the live host's rendered config. Live state was a proxied provider alias per the provider-preference policy that had been in place for over a week.

**The rule.** Pre-work agents that produce content matching real platform state MUST read that state before writing. "What's deployed?" comes before "what does the spec say?".

**The defence.** When you brief a sub-agent to produce config-like content:
- The brief includes a numbered "read first" step pointing at the live config path on the host (or the in-repo template that mirrors it)
- The brief states what the sub-agent should do if the read disagrees with their assumption (flag, don't invent)
- Spawn-time check: review the brief before sending — does it include the read-first step?

**Anti-defence.** The sub-agent's confidence in the model output is NOT a defence. Models will produce confident-sounding nonsense for any config schema. The brief is the only defence.

**Pass example:**
> "Before writing the model block, read the live value from the running host's rendered config (e.g. query it for `agents.defaults.model`). Use the values returned. If you can't reach the host, flag and stop."

**Forbidden example:**
> "Fill in the model block for each agent using sensible defaults."

## Rule 2 — One git tree at a time

**The incident.** Multiple sub-agents were spawned in parallel without `isolation: worktree`. They shared the parent's `.git/HEAD`. As each agent ran git operations (branch, commit, push), they switched the parent's HEAD. Net effect: my work landed on the wrong branch repeatedly, and the agents stashed each other's working trees during execution.

**The rule** (already in `subagent-orchestration.md`, restated here with the failure mode named):
> "No parallel git operations: branch, commit, merge and PR operations stay with the parent agent."

When you need parallelism with git operations:
- Use `isolation: worktree` — each agent gets its own checkout with its own HEAD
- Or: have sub-agents write files only; the parent does all branching/committing/pushing
- Never: spawn multiple agents in the same checkout without isolation

**The defence.** Before spawning ≥2 parallel agents:
- Decide explicitly: is this *read parallelism* (safe always), *write parallelism with non-overlapping files* (safe with care), or *git parallelism* (forbidden without worktree isolation)?
- If git parallelism is in scope, set `isolation: worktree` in the Agent tool call
- For non-overlapping file writes, list the files each agent owns and verify no overlap

**Pass example (read parallelism):**
> Spawn 3 agents to read different vault docs and produce summary reports. None do git operations.

**Pass example (worktree-isolated git parallelism):**
> Spawn 6 agents with `isolation: worktree` to each commit a non-overlapping file set to their own branch. Parent merges/cherry-picks all 6 branches at the end.

**Forbidden example:**
> Spawn 3 agents in parallel without isolation, each asked to commit different files. Branches will swap mid-execution.

## Rule 3 — The Edit/Write tool ≠ git isolation

**The discovery.** Even with `isolation: worktree`, sub-agents' `Edit` and `Write` tool calls resolve paths relative to the *user's primary working directory*, not the agent's worktree path. Result: agents claim to write to their worktree but the files appear in the parent's checkout.

**The rule.** Path discipline is at the tool-call level, not the git-isolation level. Agents must:
- Always use absolute paths in Edit/Write calls
- Verify the path resolves to their worktree (not the parent) before committing

**The defence.**
- Sub-agent briefs explicitly say: "Use absolute paths starting with your assigned worktree root. Confirm `pwd` matches the worktree root before any commit."
- Post-merge, the parent agent reviews the diff. If shadow files appear in the parent's working tree, abort the merge and re-brief the sub-agent with explicit path discipline.

## Rule 4 — Don't pre-commit-hook your way into a branch swap

**The discovery.** A pre-commit hook in some workflows runs `make check` which regenerates files. That regeneration changes the working tree. If a sub-agent then commits, the commit picks up the regenerated files. Worse: if the agent is on the wrong branch when the regeneration happens, the regenerated content gets attributed to the wrong feature.

**The defence.**
- Know which pre-commit hooks regenerate state. Document them in `.pre-commit-config.yaml` with comments.
- Sub-agents that don't need pre-commit gates should disable them for their session
- After any pre-commit-hook regeneration, re-verify the current branch before committing

**This is recorded** in `CLAUDE.md` "Recovery paths" table as: "You're a sub-agent and your branch keeps getting switched — parent owns all git ops".

## Rule 5 — Branch-name sprawl is a real cost

**The discovery.** Over a single multi-hour session, ~7 branches were created (`refactor/host-zone-split-*`, `worktree-agent-*`, `feat/w3m-agent-regeneration-*`, `infra/bootstrap-w3-wiring-*`, etc.). Multiple required conflict resolution against each other and against `main`. Three were closed as duplicates.

**The rule.** Default to trunk (`main`) for single-concern work. Branches for multi-step work that needs review surface. Sub-agent worktree branches are ephemeral — merged or discarded within the same session.

**The defence.**
- Before spawning sub-agents in worktrees, ask: "do these need to be separate PRs, or are they parts of one PR?" If the latter, cherry-pick them to the parent's branch and discard the worktree branches.
- Run `gh pr list --state open` at session start and end. Anything left should be intentional, not residue.

## Incidents log

| Date | Incident | Rule violated | Canonical fix |
|---|---|---|---|
| 2026-05-15 | Agent invented `claude-opus-4-7` model IDs | Rule 1 (read live state) | the provider-policy ADR + a config-coherence fitness check |
| 2026-05-15 | Sub-agents shared `.git/HEAD`; branches swapped mid-execution | Rule 2 (one git tree at a time) | This standard + `subagent-orchestration.md` |
| 2026-05-15 | Sub-agent in worktree wrote files to parent checkout via Edit/Write | Rule 3 (Edit ≠ git isolation) | This standard |
| 2026-05-15 | Pre-commit hook regen → branch swap caught by a peer agent | Rule 4 (pre-commit-hook awareness) | This standard + CLAUDE.md Recovery paths |
| 2026-05-15 | 7 branches at peak; 3 closed as dup; merge conflicts within session | Rule 5 (trunk-default, branch-as-exception) | This standard + trunk-only directive in CLAUDE.md |

Each row links to the canonical fix that addresses the regression.

## Fitness-function coverage

| Rule | Mechanical enforcement |
|---|---|
| Rule 1 (read live state) | TODO: a `live_state_read_first` check — manual review for now |
| Rule 2 (no parallel git ops) | TODO: a `no_parallel_git_ops` check — hard to enforce statically; manual review |
| Rule 3 (Edit path discipline) | TODO: post-merge sweep that flags shadow files in parent checkout |
| Rule 4 (pre-commit-hook awareness) | `.pre-commit-config.yaml` documents regenerating hooks |
| Rule 5 (branch sprawl) | a `branch_naming` check enforces naming; manual review for sprawl |

Manual-review rules become work items if recurring incidents justify the automation cost.

## Updates to this standard

- **2026-05-15** — initial draft post-W3 session, 5 incidents recorded.
- Future updates: on each new sub-agent-induced incident, add a row to the Incidents log and update the relevant rule.
