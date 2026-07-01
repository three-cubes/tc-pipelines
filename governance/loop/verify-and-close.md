# verify-and-close — the deterministic close side of the autonomous delivery loop

Reusable workflow: [`.github/workflows/verify-and-close.yml`](../../.github/workflows/verify-and-close.yml)
(`on: workflow_call`).

This is **SP-C-3** (decision **D5**) of the
[Autonomous Delivery Platform](https://linear.app/three-cubes/initiative/autonomous-delivery-platform-dae678e12c5d)
initiative — the automation that **replaces a human/agent manually verifying a
merge and hand-marking the Linear issue Done**. It closes the loop that the
dispatch side opens: an agent delivers a PR, it merges to `main`, and this
workflow deterministically verifies the merged result and drives the linked
Linear issue to its terminal state — with no per-merge human approval gate
(Increment-3 "Shape-as-orchestrator + enforcing hooks";
delivery-management verbs from PLA-232, harvest-then-decay from PLA-241/PLA-242).

## The contract

A consumer's **on-merge-to-main** workflow calls this reusable. It then, in order:

1. **Resolves the linked Linear issue id.** Precedence:
   1. the `issue-id` input, if set;
   2. the merged branch name, parsed against the org convention
      `<user>/<team>-<number>-<slug>` (e.g. `dan/sgo-156-...` => `SGO-156`) —
      the branch is read from the **merged PR** for the commit (works for merge,
      squash, and rebase strategies, where the push `ref_name` is only `main`);
   3. the merged PR body, scanned for an explicit identifier (e.g. `SGO-156`).
   - If **none** resolve, the workflow emits a **documented SKIP** with `fix:` /
     `next:` guidance and does **not** touch Linear — a false-close is worse than
     a skip (mirrors the SGO-169 deterministic-fallback rule).
2. **Runs the post-merge verification** (`verify-command`) with the repo checked
   out at the merged sha. This is the **deterministic verification trigger** —
   its exit code is the interim gate.
3. **On PASS** — transitions the issue to `done-state` (default `Done`) via the
   Linear GraphQL API and posts a `verification-confirmed on <sha>` comment. This
   is the delivery-management **close** verb (`update -> harvest -> close`,
   PLA-232) expressed against Linear.
4. **On FAIL** — moves the issue to `needs-fix-state` (default `Todo`), adds the
   `needs-redispatch` label (created on the issue's team if absent), and comments
   the failure log (a link to the Actions run). The **backlog dispatcher** picks
   the issue up from there — the failure is **never silently dropped** (SP-C
   failure-driven-next). By default the run then exits non-zero so the failure is
   visible red on `main` (`fail-on-verify-failure`, after the redispatch handoff).

## The independent-verifier seam (SGO-169)

The interim gate is **deterministic**: the close fires when the `verify-command`
job is green. Between verify and close there is an **explicit, documented,
currently-optional hook** for the independent-verifier judgment step —
`.github/workflows/independent-verifier.yml`, a fresh-context agent that checks
the diff against the work item's acceptance criteria (SGO-169). It is the
**judgment upgrade** on top of the deterministic gate, not a replacement for it.

Wire it via the `independent-verifier-verdict` input:

- default `pass` => interim behaviour (deterministic close-on-green);
- a consumer that has adopted SGO-169 runs `independent-verifier.yml` as an
  **upstream job** and passes its check-run conclusion (`pass` | `fail` | `skip`)
  into this input. `fail` blocks the close and routes the issue to needs-fix.

Kept **advisory-until-proven**: a flaky REQUIRED verifier would manufacture agent
loops, so the verifier stays a judgment input to this deterministic close — never
a silent hard gate (`governance/gate-hardening.md`, Determinism).

## The `LINEAR_API_KEY` secret

The workflow authenticates to the Linear GraphQL API (`https://api.linear.app/graphql`)
with a **required secret**, `LINEAR_API_KEY`.

- It is a Linear **personal/workspace API key**, sent verbatim in the
  `Authorization` header with **no `Bearer` prefix** (per the Linear API). An
  OAuth access token would use `Bearer` — this workflow uses the raw-key form.
- The key needs write access to the target team's issues: **update issue state**,
  **create comments**, **add labels**, and **create a label** (only used the first
  time `needs-redispatch` is applied on a team).
- Store it as an **Actions secret** in the consumer repo (or org-level, scoped to
  the consumer repos), e.g. `gh secret set LINEAR_API_KEY --repo <owner>/<repo>`.
- It is scoped to **only** the Linear step inside the reusable — it is never
  present in the environment of the arbitrary consumer `verify-command`.

## Wiring it (consumer)

Add an on-merge-to-main workflow to the consumer repo:

```yaml
name: on-merge-to-main
on:
  push:
    branches: [main]

permissions:
  contents: read
  pull-requests: read # resolve the merged PR (branch + body) for the commit

jobs:
  verify-and-close:
    uses: three-cubes/tc-pipelines/.github/workflows/verify-and-close.yml@v1
    with:
      verify-command: ./scripts/smoke.sh # your smoke / E2E / deploy-verify
    secrets:
      LINEAR_API_KEY: ${{ secrets.LINEAR_API_KEY }}
```

Common overrides:

| input | default | when to change |
|---|---|---|
| `verify-command` | *(required)* | your post-merge smoke / E2E / deploy-verify |
| `checkout` | `true` | `false` for a pure remote deploy-verify (no working tree) |
| `working-directory` | `.` | monorepo package path |
| `done-state` | `Done` | your team's terminal state name |
| `needs-fix-state` | `Todo` | the state the dispatcher re-picks from |
| `needs-redispatch-label` | `needs-redispatch` | your dispatcher's queue label |
| `independent-verifier-verdict` | `pass` | wire SGO-169's conclusion once adopted |
| `fail-on-verify-failure` | `true` | `false` to keep the run green on verify-fail |
| `issue-id` / `branch-name` / `pr-body` | *(auto)* | non-standard triggers that don't map a merge commit to a PR |

## Injection-safety

Every caller-supplied input and every `github.event.*` field is **env-bound**
before it reaches a shell body — never interpolated into a `run:` string — so no
value can break out of its string context. Dynamic values injected into GraphQL
go through `jq --arg` (JSON-encoded), never string-spliced into a query. The
`verify-command` is executed as a deliberate `bash -c "$VERIFY_COMMAND"` and runs
**without** `LINEAR_API_KEY` in its environment. Third-party actions are SHA-pinned.
