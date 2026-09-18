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
the canonical post-merge evidence promotion action. During migration, keep
exact-main validation until a queue run emits the required synthetic-merge
contexts.

The governance bootstrap renders the queue-less profile by default: PR,
`merge_group`, and exact-main `push` triggers. A successful PR fan-in captures
the synthetic two-parent merge SHA and tree in the reusable
`postmerge-pr-evidence` composite. On the subsequent `main` push, the paired
`verify-postmerge-pr-evidence` composite accepts the result only when the
landed merge has the same parents and tree, and the saved evidence binds the
same PR, PR-head SHA, workflow run, and attempt. Direct pushes, stale attempts,
non-merge commits, ambiguous PRs, and changed trees fail closed. A verified
promotion may reuse the trusted PR matrix while still publishing exact-main-SHA
release evidence. The shared Python gate also requires
`pre-evaluation-normalize` to leave the checkout clean before evaluation. This
binds the PR evidence to committed content; contributors run and commit any
mechanical repair locally. After the merge queue is enabled in the GitHub UI and a queue
run has emitted every required context, render with `--merge-queue`; that
profile keeps PR and `merge_group` triggers and removes post-merge promotion.

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

## Evidence and handoff contract

Each boundary passes a machine-readable identity to the next boundary. The
workflow summary indexes the retained evidence.

| Boundary | Required input | Required output |
|---|---|---|
| Local to PR | Tested commit, exact command and terminal status | PR evidence naming the local gate and generated artifacts |
| PR to merge admission | PR head plus exact integration identity | Successful required contexts bound to the admitted tree |
| Merge to publish | Preparation or candidate receipt plus immutable asset digests | Tag, release and published artifact identities |
| Publish to deploy | Published candidate identity and protected-environment decision | Target-side admission receipt |
| Deploy to production verdict | Target receipt, runtime identity and product probes | PVT receipt, candidate state and recovery decision |

A failed or cancelled stage retains its stage name, run and attempt identity,
exit classification, bounded sanitized diagnostics, receipt or locator digest,
and rollback and cleanup results. Truncated console output is diagnostic context;
the retained receipt and content-addressed artifact are the handoff. Candidate
promotion requires a complete retained handoff.

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

`setup-uv-cached` resolves the repository files after checkout when its input is
empty. Leave the Python and uv inputs empty for normal lanes so the repository
files remain authoritative. A compatibility-matrix lane passes its deliberate
alternate value explicitly. A nonempty input takes precedence over the file;
the action does not compare them. Legacy fallbacks keep repositories without
the source files working while they migrate.

The dependency graph comes from the committed lockfile. Local bootstrap and
reusable CI both use locked sync, so they install the same graph. A toolchain
update changes its authored version source and any affected lockfile in one PR.
Dependency automation updates the authored source and lockfile, then runs the
local gate and reusable caller before merge. The reviewed workflow diff must
identify any nonempty toolchain input as a compatibility-matrix value; it is
not parity evidence for the repository's normal toolchain lane.

## Operational runbook

1. Sync from the committed lockfile and authored toolchain files. Use the
   repository's under-60-second smoke command while editing, then run the exact
   full local gate before push. Record the tested commit, commands and terminal
   results in the PR.
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
8. If a stage fails, retain its receipt, diagnostic artifact, rollback result
   and cleanup result. Use the recorded candidate and attempt identity to
   resume, roll back, or fix forward.
9. Complete bounded cleanup after the retained evidence and recovery window
   are verified. Cleanup preserves the failed candidate verdict.

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
