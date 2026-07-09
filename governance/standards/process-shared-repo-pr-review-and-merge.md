# Shared-repo PR review + merge process

Applies to PRs against the shared tc-fitness engine repo, the shared tc-pipelines repo, and any sibling consumer repo — anywhere the author can't self-approve.

## Review
- A shared-repo PR needs a review the author **cannot self-provide** (the org's `main` rulesets require a review; GitHub blocks self-approval). Get a second party, or treat it as blocked.

## Merge gate
- Admin-merge (`gh pr merge --merge --admin`) is permissible **only** when every **required** check is green: the `CI gate` aggregator + the `Pre-merge PR gates`. Use `--merge` (preserve history), never `--squash`.
- `codecov/patch` is **non-required** and may flag red even on a healthy PR. Flag-basis reason: new production lines covered only by the *integration* tier trip the patch-target flag while the **F9 union floor** (unit ∪ integration) is still green. Don't block a merge on `codecov/patch` alone — confirm the required checks + F9 union floor are green. (Optional clean-up: add a unit-flag test for the new line.)
- This does **not** relax the no-`--admin` / no-branch-protection-bypass rule for routine work: it's the narrow, user-authorized exception for a shared repo where the required checks are green and a human review exists.

## Update the production pins only after a byte-identical-ledger diff
- For a tc-fitness bump, the consumer's fitness ledger (`tc-fitness run --all` + `--staged`) must be diffed before/after the pin bump and confirmed unchanged (sha256) — verdicts must not drift. Tag the engine first (HITL), then bump pins.
