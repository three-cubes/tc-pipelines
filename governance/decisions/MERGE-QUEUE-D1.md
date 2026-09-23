# MERGE-QUEUE-D1 — GitHub merge queue for PRODUCT repos (re-test vs latest tip)

Status: Accepted (canonical REST-importable template)
Scope: tc-pipelines (CORE governance templates), product repositories
Supersedes (for product repos): kata `docs/adr/ADR-013` (which removed
`merge_group` for "auto-merge, no queue"). See "Reconciliation" below.
Related: SGO-166 (auto-merge-on-green), SGO-168 (this note), SGO-180 (two-profile
rulesets), ADRs STD-MERGE / RULESET-D1 / GATE-HARDEN.

## Decision

Product repos merge to `main` through a **GitHub merge queue** so every PR is
**re-tested against the latest tip** before it lands (the "not-rocket-science"
rule: never merge a green-against-a-stale-base PR that would red `main`). Small
config/data repos may keep **auto-merge, no queue** — their change shape doesn't
carry the semantic-conflict risk a queue exists to catch.

The canonical queue configuration lives in
[`governance/rulesets/merge-queue.json`](../rulesets/merge-queue.json):

- **grouping = ALLGREEN** — a group merges only if the whole group is green
  (one red entry fails the group, not just itself).
- **group size** — `min_entries_to_merge: 1`, `max_entries_to_merge: 1`,
  `min_entries_to_merge_wait_minutes: 0`, `max_entries_to_build: 3`.
- **allowed merge method** — `MERGE` (the repository's merge-commit policy).
- **check-response timeout** — `check_response_timeout_minutes: 30` (a required
  check that never reports within the window fails the entry, not hangs the queue).
- **human break-glass** — the `three-cubes/maintainers` team may bypass for a
  pull request only. GitHub Apps and integrations are not bypass actors, and a
  bypass remains visible in the pull-request audit trail.

## REST application

GitHub supports the `merge_queue` rule in the repository rulesets REST API. Apply
the canonical payload with an installation token that has repository
administration permission:

```sh
gh api "repos/${OWNER}/${REPOSITORY}/rulesets" \
  --method POST \
  --input governance/rulesets/merge-queue.json
```

For an existing ruleset, read its ID by name and use `PUT` with the same payload.
The source file intentionally contains no live numeric ruleset or repository IDs;
those are deployment state and must be discovered from the API at apply time.

## `on: merge_group` — the fan-in check must report on queue events

A merge queue builds a temporary `merge_group` ref and expects the required
checks to report against it. If a product repo's fan-in **"CI gate"** job does
not run on `merge_group` events, the queue can never go green. Add the trigger:

```yaml
on:
  pull_request:
  merge_group:      # required: the fan-in "CI gate" job must report here too
```

The job named **"CI gate"** (the fan-in check-run that
[`auto-merge-on-green.yml`](../../.github/workflows/auto-merge-on-green.yml)
keys off) must therefore report on BOTH `pull_request` and `merge_group`.

## Reconciliation with kata ADR-013

kata `docs/adr/ADR-013` deliberately **removed** `merge_group` to run
"auto-merge, no queue". This note does **not** reverse that decision globally —
it **scopes** it:

- **Product repos** (kairix): adopt the queue (re-test vs tip). ADR-013's
  no-queue stance is superseded **here only**.
- **Small config / data repos** (kata-shaped): may keep auto-merge-no-queue;
  their diffs don't carry the mid-air-collision risk the queue guards against.

## Rollout (per product repo)

1. Add `merge_group:` to the repo's `ci.yml` `on:` and confirm the "CI gate" job
   reports on it.
2. Harden the gate to `governance/gate-hardening.md` and verify it runs green and
   deterministic (never flip a queue on top of a flaky gate).
3. Apply `governance/rulesets/merge-queue.json` via the repository rulesets API.
4. Apply `governance/rulesets/main-product.json` (0-review) via the API.
5. Verify two stacked PRs are each re-tested against the updated tip before merge.
