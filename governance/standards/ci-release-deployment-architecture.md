---
type: standard
context: three-cubes
status: active
owner: platform
tags: [ci, release, deployment, merge-queue, operations]
---

# CI, Release and Deployment Architecture

This standard defines the release path for trunk-based repositories: PR
feedback, exact-merge validation, immutable release evidence, and protected
production deployment.

## The required flow

```
PR fast feedback ─┐
                  ├─ merge queue: exact integration gate ─ candidate record
                  │                                        │
                  └─ PR feedback                           ├─ protected publish
                                                           │
                                                           └─ protected production deploy
```

The validation lanes provide:

1. **PR feedback** gives an author fast, path-aware evidence before merge.
2. **Merge-queue validation** proves the synthetic exact integration commit.

The merge queue validates the integration commit. The release workflow records
provenance for that commit in the candidate record.

## Required repository configuration

Repositories with merge queue enable it on the protected default branch, require
the queue contexts, and subscribe CI to `merge_group`. Queue-less private
repositories use the strict `main-core.json` or `main-product.json` ruleset and
exact-main validation. During migration, keep exact-main validation until a
queue run emits the required synthetic-merge contexts.

The governance bootstrap renders the queue-less profile by default: PR,
`merge_group`, and exact-main `push` triggers. After the merge queue is enabled
in the GitHub UI and a queue run has emitted every required context, render with
`--merge-queue`; that profile keeps PR and `merge_group` triggers and removes
the post-merge full gate. This prevents duplicate full CI without losing the
release evidence for the final integrated commit.

Release repositories apply `release-tags.json`. It protects release tags from
updates and deletion, records bypasses, and lets the publish job verify the
immutable asset digest before deployment.

## Candidate, publish and deploy

A release candidate is a durable machine record:

```json
{
  "release_sha": "<40-hex>",
  "candidate_tag": "<repository-native immutable version tag>",
  "generation": 0,
  "state": "active",
  "release_notes_mode": "generated",
  "preparation_run_id": 0,
  "preparation_artifact_digest": "sha256:<64-hex>",
  "provenance_digest": "sha256:<64-hex>"
}
```

The preparation job serializes release identity allocation, reserves one unique
repository-native version tag, builds and verifies the release bytes, and writes
this record. `generation` identifies the next deployable generation. `state`
records `active`, `revoked`, `superseded`, or `deployed`. `release_notes_mode`
records `changelog` or `generated`. The protected publish job reads the record
and publishes the referenced bytes.

The published candidate dispatches production deployment. The protected
Environment approves the deployment. The target verifies the release assets and
candidate receipt before apply.

## Production verification and PVT

The product deployment workflow runs live PVT after target-side apply and smoke
checks. The PVT runner writes a receipt containing the release identity, runtime
identity, probes, and evidence. A green receipt promotes the candidate to
known-good. A held or failed receipt preserves the evidence and selects the
product's hold, rollback, or fix-forward path.

Same-repository `workflow_dispatch` uses the scoped `GITHUB_TOKEN`. A
cross-repository handoff or App-audited handoff uses a short-lived GitHub App
token. The publisher summary records the release tag, target workflow, and PVT
contract. The target workflow records production approval and the PVT verdict.

Generic infrastructure deployment workflows record their component smoke and
rollback result. The product deployment workflow writes the PVT receipt that
completes the product release.

At publish and deploy time, use the successful merge-group head with its durable
mapping to the protected-branch tip. A queue-less repository uses its successful
exact-main head. Verify that the assets match the candidate record and that the
generation is next. Candidate state records `active`, `revoked`, `superseded`,
and `deployed`. Rollback selects an earlier deployed generation.

## Release metadata

Each repository uses its established version scheme. A CalVer package build uses
the version that its package metadata supplies. A CalVer release process that
controls the version derives its tag from the protected tag set in the release
workflow. A repository with a semantic or other native format allocates that
format. The candidate record stores the selected `changelog` or `generated`
release-note mode.

## Toolchain ownership

Each toolchain has one authored source:

| Tool | Canonical source | Consumers |
|---|---|---|
| Node/pnpm | `packageManager` and `.nvmrc` | local bootstrap and setup action |
| Python | `.python-version` | local bootstrap and setup action |
| uv | `.uv-version` | local bootstrap and setup action |

`setup-uv-cached` resolves the repository files after checkout. A workflow can
pass an explicit value only for a deliberate compatibility matrix. The action
retains legacy fallbacks while repositories add the source files.

## Operational runbook

1. Author a PR and use the repository's under-60-second local smoke command.
2. Let the green PR enter the merge queue.
3. The queue's exact integration result provides merge admission.
4. Start the release candidate operation for the successful merge-group head
   and its main-tip mapping, or for the successful exact-main head in a
   queue-less repository. The operation records candidate identity and
   preparation evidence.
5. Approve the protected publish Environment after reviewing the candidate
   summary. GitHub publishes the exact prepared bytes.
6. Approve the protected production Environment. The deploy stages, verifies,
   applies, smoke-tests and executes the attested PVT for the published
   candidate.
7. Read the deployment's PVT receipt and terminal state. A green receipt is the
   production completion record; a held or failed receipt names the recovery
   operation and preserved evidence.
8. If a stage fails, use the recorded candidate/attempt identity to resume,
   roll back, or fix forward from the recorded identity.

## Migration and verification

1. Enable merge queue and add `merge_group` to the consumer gate before
   removing the push trigger.
2. Prove a queue run emits every required context on a synthetic merge.
3. Replace separate prepare/publish dispatches with one workflow DAG separated
   by the protected publish Environment.
4. Replace manual deployment dispatch with the candidate-record handoff and
   retain protected production approval in the target workflow. Use
   `GITHUB_TOKEN` for same-repository dispatch. Use an App token for
   cross-repository or App-audited handoffs.
5. Bind the deployment's live PVT receipt to candidate promotion and recovery
   state.
6. Scope `deploy-on-merge` to generic infrastructure work. Dispatch product
   deployment from published candidates.
7. Configure the release trigger once and verify that each release runs one
   full language/E2E matrix.

The reusable-workflow implementation belongs in `tc-pipelines`; Hermetic build,
runtime provenance and VM-specific verification stay with the consuming product
repository.
