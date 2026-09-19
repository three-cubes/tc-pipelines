# SDLC Release Workflow

This standard defines how a reviewed integration commit becomes one immutable
release. It implements the release portion of
[`ai-sdlc-product-architecture.md`](ai-sdlc-product-architecture.md) and uses the
candidate and evidence contract in
[`ci-release-deployment-architecture.md`](ci-release-deployment-architecture.md).

## Release outcome

A release produces:

- one version allocated from the repository's declared version scheme;
- one protected tag bound to the admitted commit;
- one set of package or container artefacts;
- content digests and build provenance;
- generated release notes;
- one candidate receipt;
- one terminal publish result.

Application artefacts are built once. Qualification, publication and deployment
consume the recorded digests.

## Trunk flow

```text
feature PR
   |
   v
exact integration validation
   |
   v
allocate version and build candidate
   |
   v
protected publish
   |
   v
deployment or package availability receipt
```

The feature PR carries product behaviour and user-visible release-note input.
The release graph allocates and materialises release metadata after the exact
integration commit is known. This removes release-only PRs and hand-maintained
version choreography.

## Version allocation

The consumer declaration selects its version scheme:

- semantic version for reusable packages and SDLC products;
- calendar version for products that publish by date;
- repository-native version where an external contract requires it.

The release allocator serialises allocation, reads the protected tag set and
reserves the next valid version. The candidate receipt records the scheme,
allocated version and source commit. A repeated run for the same commit returns
the existing identity.

Package metadata and version files are generated release outputs where the
ecosystem requires them. Source code reads installed package metadata or the
candidate receipt. Contributors do not maintain duplicate fallback versions.

## Release notes

Feature PRs provide user-visible notes through structured PR metadata or an
`Unreleased` section when the product needs curated wording. The release task
collects the merged entries, links work items and produces the final versioned
notes.

The release receipt records the input commit and release-note digest. A rerun
for the same candidate verifies that digest before confirming the existing
GitHub Release.

## Package release

The candidate graph:

1. creates a clean source archive or package build environment;
2. installs from locked dependencies;
3. runs the complete package and consumer contract graph;
4. builds the package once;
5. verifies package contents, metadata, import and CLI surfaces;
6. records artefact digests and provenance;
7. publishes after the protected environment decision.

Reference consumer fixtures install the built package artefact, rather than a
source checkout, before publication.

## Container release

The candidate graph:

1. builds one OCI image;
2. records the image digest and source identity;
3. generates provenance and the configured SBOM;
4. runs local and hosted qualification against that digest;
5. publishes the qualified digest;
6. dispatches protected deployment with the candidate receipt.

Tags provide human-readable discovery. Digests provide execution identity.

## Coordinated tc-pipelines release

A `tc-pipelines` release binds:

- `@three-cubes/tc-sdlc` package version;
- canonical SDLC image digest;
- GitHub workflow commit;
- schema version;
- compatible `tc-fitness` version.

The published release catalogue is the input to generated consumer upgrades.
See [`supply-chain-pinning.md`](supply-chain-pinning.md).

## Failure and retry

Every stage is idempotent for one candidate identity. A retry verifies existing
tags, packages, images and releases by digest before confirming them. A digest
mismatch stops publication and records the conflicting identity.

Failed builds and qualification runs retain bounded diagnostics. Unpublished
artefacts expire through lifecycle cleanup. Published immutable artefacts remain
available for rollback according to product retention policy.

## Current compatibility path

The current preparation receipt, version source, CHANGELOG promotion and
`release-on-merge.yml` workflows remain supported during migration. They become
executors in the release graph before their standalone orchestration is removed.

Repositories with a durable `develop` branch may retain that policy until they
adopt exact-integration candidate allocation. The target release flow uses one
protected trunk and short-lived feature branches.

## Acceptance criteria

- the admitted commit is the candidate source;
- version allocation is unique and repeatable;
- release metadata requires no release-only PR;
- packages and images build once;
- qualification consumes built artefacts;
- every published artefact has a digest and provenance;
- reruns confirm or reject existing state deterministically;
- one release catalogue drives `tc-pipelines` consumer upgrades;
- the release receipt links work item, commit, artefact and terminal result.
