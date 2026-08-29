---
type: standard
context: three-cubes
status: active
owner: platform
tags: [ci, release, deployment, merge-queue, operations]
---

# CI, Release and Deployment Architecture

This architecture gives trunk-based repositories fast PR feedback, exact-merge
validation, immutable release evidence and protected production deployment.

## The required flow

```
PR fast feedback ─┐
                  ├─ merge queue: exact integration gate ─ candidate record
                  │                                        │
                  └─ (PR never deploys)                    ├─ protected publish
                                                           │
                                                           └─ protected production deploy
```

The validation lanes have distinct roles:

1. **PR feedback** gives an author fast, path-aware evidence before merge.
2. **Merge-queue validation** proves the synthetic exact integration commit.

The merge queue validates the integration commit. Post-merge attestation records
provenance for that same candidate.

## Required repository configuration

Queue-capable repositories enable GitHub merge queue on the protected default
branch and require the queue contexts. Consumer CI subscribes to `merge_group`.
Private repositories without merge-queue support use strict required status
checks and retain exact-main validation. During migration, the consumer keeps
its exact-main post-merge validation until a queue run has emitted the required
contexts for a synthetic merge.

## Candidate, publish and deploy

A release candidate is a durable machine record:

```json
{
  "release_sha": "<40-hex>",
  "candidate_tag": "<repository CalVer tag>",
  "preparation_run_id": 0,
  "preparation_artifact_digest": "sha256:<64-hex>",
  "provenance_digest": "sha256:<64-hex>"
}
```

The preparation job serializes release identity allocation, reserves one unique
repository-format CalVer tag, builds and verifies exact candidate bytes, then
records the identity. The protected publish job consumes that artifact directly.

The published candidate dispatches production deployment. The protected
Environment controls the decision. Target-side deployment verifies the public
immutable assets and candidate receipt before apply.

## Production verification and PVT

Production verification is an executable stage of the deployment workflow. A
deployment that declares an attested PVT invokes the product-owned live PVT
runner after the target-side apply and smoke boundary. The runner writes a
receipt bound to the release identity, runtime identity, probes and captured
evidence. A green receipt promotes the deployed candidate to known-good; a
held or failed receipt retains the evidence and enters the product's explicit
hold, rollback or fix-forward path.

The release publisher creates this handoff with a short-lived GitHub App token.
GitHub's default workflow token does not emit follow-on workflow events, so an
App-authenticated `workflow_dispatch` is the portable release-to-deployment
mechanism. The publisher records the release tag, target workflow and PVT
contract in its job summary. The target workflow owns production approval and
the terminal PVT verdict.

Generic infrastructure deployment workflows expose only the checks they run.
They record component smoke and their own rollback result. A generic smoke
notice is not PVT evidence and cannot complete a product release.

At publish and deploy time, verify that the candidate SHA is an ancestor of the
protected branch, its exact merge-queue contexts passed, its attested assets
match the candidate record, and its generation is the next deployable generation.
Candidate state records `active`, `revoked`, `superseded` and `deployed`; an
explicit rollback operation selects an earlier deployed generation.

## Release metadata

For a repository whose release version is not an input to a package build,
derive CalVer from the immutable existing tag set in the release workflow and
store it in the candidate record. The migration adds reusable `changelog` and
`generated` release-note modes; the selected mode is part of the candidate
record.

## Toolchain ownership

Each toolchain has one authored source:

| Tool | Canonical source | Consumers |
|---|---|---|
| Node/pnpm | `packageManager` and `.nvmrc` | local bootstrap and setup action |
| Python | `.python-version` | local bootstrap and setup action |
| uv | `.uv-version` | local bootstrap and setup action |

The migration first adds file resolution to the shared setup action and its
parity test. Consumers then move Python and uv values into those files; local
bootstrap and reusable jobs resolve the same values.

## Operational runbook

1. Author a PR and use the repository's under-60-second local smoke command.
2. Let the green PR enter the merge queue.
3. The queue's exact integration result becomes the only merge admission.
4. Start one release candidate operation for a selected merged SHA. It records
   the candidate identity and preparation evidence.
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
4. Replace manual deployment dispatch with an App-authenticated candidate-record
   handoff and retain the protected production approval in the target workflow.
5. Bind the deployment's live PVT receipt to candidate promotion and recovery
   state.
6. Remove the VERSION-only trigger and verify that a release no longer causes a
   second full language/E2E matrix.

The reusable-workflow implementation belongs in `tc-pipelines`; Hermetic build,
runtime provenance and VM-specific verification stay with the consuming product
repository.
