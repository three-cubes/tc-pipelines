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
production deployment. It implements the release and deployment portion of
[`ai-sdlc-product-architecture.md`](ai-sdlc-product-architecture.md).

## The required flow

```
local affected graph
        |
        v
PR affected graph ──> exact integration graph ──> immutable candidate digest
                                                        |
                                                        v
                                                protected publish
                                                        |
                                                        v
                                                production deploy
                                                        |
                                                        v
                                                PVT or rollback
```

The validation lanes provide:

1. **Local and PR affected graphs** provide fast, path-aware evidence.
2. **Exact integration validation** proves the admitted integration commit.
3. **Candidate qualification** exercises the immutable artefact that production consumes.

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
  "sdlc_release": "<version>",
  "sdlc_lock_digest": "sha256:<64-hex>",
  "candidate_tag": "<repository-native immutable version tag>",
  "candidate_digest": "sha256:<64-hex>",
  "generation": 0,
  "state": "active",
  "release_notes_mode": "generated",
  "preparation_run_id": 0,
  "preparation_artifact_digest": "sha256:<64-hex>",
  "provenance_digest": "sha256:<64-hex>"
}
```

The candidate task serializes release identity allocation, reserves one unique
repository-native version tag, builds the release bytes once, verifies them and
writes this record. Qualification, publish and deployment consume
`candidate_digest`. `generation` identifies the next deployable generation. `state`
records `active`, `revoked`, `superseded`, or `deployed`. `release_notes_mode`
records `changelog` or `generated`. The protected publish job reads the record
and publishes the referenced bytes.

The published candidate dispatches production deployment. Production pulls the
recorded digest and performs no application rebuild. The protected
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

Ansible converges host prerequisites. Docker Compose applies the qualified
single-host container stack. Consumer adapters provide persistent-state harvest,
runtime configuration and product PVT journeys. SSH and cloud control-plane
transports consume the same typed request and return the same receipt.

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
| Local to PR | Tested commit, SDLC lock, task identities and terminal status | PR evidence naming completed tasks and generated artefacts |
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

## Environment and toolchain ownership

The `tc-pipelines` release catalogue identifies the canonical environment image,
SDLC package, workflow commit, schema and compatible `tc-fitness` version. The
consumer's `sdlc.yaml` declares product toolchain requirements. The generated
`tc-sdlc.lock` resolves both into one reviewed identity.

Language lockfiles remain the source of dependency graphs. Native bootstrap and
the canonical image consume those lockfiles through the same graph task.
Compatibility matrices are explicit tasks with distinct identities; their
results supplement the normal locked environment.

The coordinated upgrade command updates every materialised package, image,
workflow and fitness reference in one PR and executes the affected graph before
merge.

## Operational runbook

1. Run `make bootstrap`, `make prepare` and the affected graph. Run the complete
   graph before release admission. Record the tested commit, SDLC lock, task
   identities and terminal results.
2. Let the green PR enter the merge queue.
3. The queue's exact integration result provides merge admission.
4. Build the release candidate once for the successful merge-group head
   and its main-tip mapping, or for the successful exact-main head in a
   queue-less repository. The operation records candidate identity and
   preparation evidence.
5. Approve the protected publish Environment after reviewing the candidate
   summary. GitHub publishes the exact prepared bytes.
6. Approve the protected production Environment. The deploy verifies the
   candidate receipt, converges the host, applies the recorded digest and
   executes health and product verification journeys.
7. Read the deployment's PVT receipt and terminal state. A green receipt is the
   production completion record; a held or failed receipt names the recovery
   operation and preserved evidence.
8. If a stage fails, retain its receipt, diagnostic artifact, rollback result
   and cleanup result. Use the recorded candidate and attempt identity to
   resume, roll back, or fix forward.
9. Complete bounded cleanup after the retained evidence and recovery window
   are verified. Cleanup preserves the failed candidate verdict.

## Migration and verification

1. Adopt the released environment, graph declaration and coordinated lock.
2. Prove affected and exact-integration tasks locally and in hosted execution.
3. Enable merge queue and prove every required context on a synthetic merge, or
   retain the exact-main evidence path where queue support is unavailable.
4. Build and qualify one immutable candidate digest.
5. Connect candidate publication to protected deployment through the typed
   receipt.
6. Bind live PVT, rollback and cleanup receipts to candidate state.
7. Remove equivalent post-merge evaluation and superseded deployment paths
   after their consumer counts reach zero.

Shared environment, graph, evidence and deployment transaction behaviour belongs
in `tc-pipelines`. Fitness evaluation belongs in `tc-fitness`. Product build
inputs, runtime configuration, state semantics and verification journeys belong
in the consumer repository.
