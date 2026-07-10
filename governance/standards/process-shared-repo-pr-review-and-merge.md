# Shared-repo PR review + merge process

Applies to PRs against the two CORE paved-road repos — the tc-fitness engine and this tc-pipelines repo — and any sibling consumer repo where the author can't self-approve.

## Review
A shared-repo PR needs a review the author **cannot self-provide** (the org's `main` ruleset requires it and GitHub blocks self-approval). The two CORE repos hold **every** PR for an `n+1` human `@three-cubes/maintainers` review — a change to the gate engine or the reusable pipelines is control-plane by definition (decision D3). Get the second party, or treat the PR as blocked. Canon: [`agent-sdlc-access-and-hitl.md`](../agent-sdlc-access-and-hitl.md) + [`STANDARDS.md §4`](../STANDARDS.md).

## Merge — auto-merge on green after the review
Once the required human review is in and the gate is green, the PR **merges itself**: `auto-merge-on-green.yml` fires on the Quality-gate `workflow_run` completion and, when the fan-in "CI gate" check-run is green, arms `gh pr merge --auto --merge` as the App. The required contexts are **Quality gate** + **SonarCloud scan** + **SonarCloud Code Analysis** (a hardened gate also requires **Mutation**); use the merge-commit method, never squash. No human runs the merge.

`gh pr merge --admin` is the **narrow, human-authorised exception** — a logged owner override for when every required check is green and a human review exists. It is never a routine path and never self-authorised by an agent; a ruleset with no bypass actors blocks even admins, so the override is a deliberate human act. It does not relax the never-merge-over-a-red-gate rule for routine work.

## Update the production pins only after a byte-identical-ledger diff
For a tc-fitness bump, diff the consumer's fitness ledger (`tc-fitness run --all` + `--staged`) before and after the pin bump and confirm it is unchanged (sha256) — verdicts must not drift. Tag the engine first (HITL), then bump pins. This is the ledger-diff step the [`improving-fitness-gates.md`](improving-fitness-gates.md) consumer-repin flow depends on.
