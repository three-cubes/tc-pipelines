# Infrastructure and deployment fitness

## What this standard establishes

Every deployable service declares one structured runtime contract. The contract describes the
paths, identities, access operations, transaction phases and evidence needed to operate the
service. Fast checks validate that contract before merge. The deployment pipeline exercises the
same contract on the target and returns a digest-bound receipt.

This gives directory mappings, permissions, rollback and cleanup one testable source of truth.
Product-specific PVTs continue to prove business behaviour after the shared contract passes.

## Why

Static configuration can be valid while the deployed service cannot read its configuration,
write its state, traverse a mounted parent directory or find a profile-relative plugin. A command
can also exit successfully while its service is unhealthy, its evidence is stale or its cleanup
failed. These failures repeat when path and identity assumptions are copied between shell scripts,
workflow YAML, container configuration and tests.

The shared contract moves those assumptions into data, evaluates them locally, and records what
the target actually observed.

## Canonical ownership

| Concern | Canonical home | Output |
|---|---|---|
| Contract validators | `tc-fitness` CORE checks | Fast, deterministic findings |
| Deployment orchestration and safe evidence transport | `tc-pipelines` | Target receipt and retained diagnostics |
| Service identifiers, paths, identities and product probes | Consumer repository | Canonical target registry and product PVT |
| Cloud-resource security | Checkov and the repository's IaC | IaC security findings |
| Artifact origin | Build provenance and immutable digests | Verified candidate identity |

## Runtime contract

The portable validation document uses schema identifier `tc-fitness/runtime-contract/v1`. A
consumer authors one target registry in YAML or JSON and references it from `sdlc.yaml`.
`tc-sdlc` invokes the compatible `tc-fitness` engine, which loads it strictly and selects one
environment and target, and produces canonical JSON for hashing and deployment. YAML support uses
the engine's optional PyYAML extra; selecting YAML without that dependency fails with an actionable
dependency error. The selected canonical bytes are hashed with SHA-256 and travel with the
candidate.

The document contains four sections.

### Filesystem

`filesystem` declares:

- host, container and profile namespaces;
- named roots with absolute POSIX paths and lifecycle classifications;
- mounts from one named root to a target namespace and path;
- aliases that point to a named canonical root;
- symlink source and destination relationships; and
- explicit, reasoned allowances for intentional nested roots.

Validation resolves paths by component. It detects missing references, physical overlap across
logical namespaces, cycles, symlink escape, alias disagreement and mount targets outside their
declared namespace. Container paths are resolved inside the container namespace.

### Access

`access` declares:

- runtime identities with numeric UID, primary GID and supplementary groups;
- required operations for each identity and path;
- owner, group and mode expectations;
- setgid, default ACL and umask inheritance expectations; and
- secret paths with authorised and denied identities.

The operation set is `traverse`, `read`, `write`, `create`, `delete` and `rename`. Create, delete
and rename checks include the parent directory. Declaration mode validates the matrix, identities,
path references and inheritance expectations without requiring a live target. Observation mode is
activated by an explicit evidence input; the target collector then performs each declared operation
as the declared identity and records the resulting owner, group, mode and access result. A configured
observation input is mandatory evidence: missing or incomplete observations fail.

### Deployment transaction

`deployment` declares:

- the immutable candidate and execution-artifact identities;
- preflight, recovery, apply, probe, cutover, rollback and cleanup entrypoints;
- the identity and configuration used for every probe;
- the recovery policy and retained recovery reference; and
- bounded timeouts and retention.

The successful sequence is:

```text
validate contract and candidate
→ preflight
→ recovery point
→ apply
→ probe as the runtime identity
→ cutover
→ retain evidence and run bounded cleanup
```

Any failure after mutation begins, including apply, probe or cutover failure, records diagnostics,
executes rollback, verifies the restored runtime, retains the failed candidate verdict and runs
bounded cleanup. A successful rollback proves recovery; it does not accept the failed candidate.

### Evidence

The target emits canonical JSON with schema identifier `tc-fitness/runtime-evidence/v1`. The
receipt binds:

- contract digest;
- source commit and image or artifact digest;
- host, deployment, run and attempt identities;
- runtime user and configuration identity;
- ordered transaction events;
- every required filesystem, access and behavioural observation;
- recovery and cleanup results;
- diagnostic artifact references and SHA-256 digests; and
- a timezone-aware capture timestamp.

The caller supplies the expected commit, artifact, host and runtime identity independently. The
evidence validator recomputes referenced artifact digests and enforces the configured freshness
window. Missing, stale, skipped, conflicting or exit-code-only evidence fails.

## Shared fitness functions

`tc-fitness` exposes four independent opt-in checks:

1. `core:runtime_filesystem_contract`
2. `core:runtime_access_matrix`
3. `core:deployment_transaction_contract`
4. `core:runtime_evidence_contract`

They share strict JSON loading, duplicate-key rejection, canonical hashing, identity validation
and actionable finding output through one private implementation module. An absent configuration
block preserves existing consumer behaviour. A present block activates the check; missing or
malformed configured inputs then fail.

The checks use hard adoption: baselines cannot suppress contract or evidence defects. Every
finding states the source, JSON pointer, violated invariant, `fix:`, `next:` and `run:`.

## Pipeline execution

The SDLC deployment graph invokes the catalogue-compatible
`tc-fitness-runtime-contract` executable before authentication and after target
execution. The same engine code validates local fixtures and live receipts.
The existing Azure VM reusable remains the compatibility transport while the
Cloudflare SSH and Azure paths converge on the typed request and receipt.

The target packages the receipt and each allowlisted diagnostic into a bounded archive, uploads it
to the contract's private content-addressed evidence store with its managed identity, and returns a
versioned locator through the protected output marker. The runner downloads that exact version with
WIF, verifies locator identity, length and archive digest, rejects unsafe archive members, then
recomputes every referenced diagnostic digest from the downloaded bytes. It publishes the verified
secret-safe archive as the immutable workflow artifact. A target-reported hash without transferred
bytes is not evidence.

The reusable exposes compact status, receipt digest and artifact identity outputs. The consumer
owns product probe commands and rollback commands. The shared layer verifies their declared
identity, ordering, evidence and terminal result.

The first implementation uses the existing Python and shell runtime. Goss remains an optional
future collector adapter for generic host resources. The contract and receipt semantics remain
independent of collector tooling.

## Test strategy

Each historical failure becomes a sabotage fixture that fails before its implementation change.
The minimum fixture catalogue includes:

- host, cluster and profile roots that overlap after physical resolution;
- root and profile homes used interchangeably;
- a stale executable path;
- a parent directory without traverse access;
- a writable file whose parent denies delete or rename;
- root-created state consumed by a non-root runtime identity;
- missing shared-group, setgid, ACL or umask inheritance;
- a secret readable by an unauthorised identity;
- an escaping or cyclic symlink;
- mutation before a recovery point;
- a probe executed as the wrong user or against the wrong root;
- cutover before a successful behavioural probe;
- cutover failure without diagnostics, rollback and restored-runtime verification;
- rollback success represented as candidate success;
- truncated output or a self-reported diagnostic hash without a retained, runner-verified artifact;
- cleanup omitted on failure or cancellation;
- a recovery point removed before its configured retention expires;
- evidence bound to another commit, image, host or runtime user; and
- missing, stale, skipped or tampered evidence.

Unit and contract tests use real temporary files and public check entrypoints. Consumer integration
tests materialise a Linux filesystem and execute the access matrix as real identities. Production
qualification exercises the exact candidate and records the live receipt.

Critical build and deployment surfaces bind their executable tests through the
[testing strategy's `core:behavioural_evidence`
contract](testing-strategy.md#behavioural-evidence-integrity). Structural
assertions remain useful policy checks, but they do not satisfy an executable
evidence claim.

## Adoption and release

Delivery follows this order:

1. Add the checks to a candidate `tc-fitness` release.
2. Bind that engine into a candidate coordinated `tc-pipelines` release.
3. Run valid and sabotaged reference consumer contracts through the candidate graph.
4. Publish one SDLC release catalogue after qualification.
5. Upgrade the consumer declaration and generated lock together.
6. Run shared checks beside the existing compatibility checks.
7. Remove an overlapping local check after verdict and diagnostic parity is recorded.
8. Run production deployment and product PVT against the exact qualified digest.

Retention is a consumer value. The Hermes deployment uses `172800` seconds, or 48 hours.
