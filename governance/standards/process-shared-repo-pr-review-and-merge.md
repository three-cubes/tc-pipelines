# Shared-repo PR review + merge process

Applies to PRs against the two CORE product repos — `tc-fitness` and
`tc-pipelines` — and any sibling consumer repo where the author cannot
self-approve.

## Review
A shared-repo PR needs a review the author **cannot self-provide** (the org's `main` ruleset requires it and GitHub blocks self-approval). The two CORE repos hold **every** PR for an `n+1` human `@three-cubes/maintainers` review — a change to the gate engine or the reusable pipelines is control-plane by definition (decision D3). Get the second party, or treat the PR as blocked. Canon: [`agent-sdlc-access-and-hitl.md`](../agent-sdlc-access-and-hitl.md) + [`STANDARDS.md §4`](../STANDARDS.md).

## Merge — auto-merge on green after the review
Once the required human review is in and the gate is green, the PR **merges itself**: `auto-merge-on-green.yml` fires on the Quality-gate `workflow_run` completion and, when the fan-in "CI gate" check-run is green, arms `gh pr merge --auto --merge` as the App. The required contexts are **Quality gate** + **SonarCloud scan** + **SonarCloud Code Analysis** (a hardened gate also requires **Mutation**); use the merge-commit method, never squash. No human runs the merge.

`gh pr merge --admin` is the **narrow, human-authorised exception** — a logged owner override for when every required check is green and a human review exists. It is never a routine path and never self-authorised by an agent; a ruleset with no bypass actors blocks even admins, so the override is a deliberate human act. It does not relax the never-merge-over-a-red-gate rule for routine work.

## Qualify the coordinated release

For a change to `tc-fitness` or `tc-pipelines`, run the candidate coordinated
release against the reference consumer fixtures. Record the previous and
candidate fitness ledgers and classify every intended change. Publish the
release catalogue after the package, image, workflow and fitness identities pass
the candidate fixtures. Consumer upgrade PRs materialise those identities
together. See [`improving-fitness-gates.md`](improving-fitness-gates.md).
