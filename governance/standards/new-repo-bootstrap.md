# New Repository Bootstrap

Bootstrap installs the released `tc-pipelines` AI SDLC product and the repository
governance required to use it. The product architecture is
[`ai-sdlc-product-architecture.md`](ai-sdlc-product-architecture.md).

## Target command

```bash
tc-sdlc adopt --repo three-cubes/<name> --release <version>
```

The command reads the coordinated release catalogue and produces one reviewable
change. It performs local rendering and verification. Remote repository settings,
secrets and protected environments are reconciled through explicitly reported
hosted operations.

## Rendered product contract

The adoption change contains:

- `sdlc.yaml` with project, toolchain, fitness profile and target declarations;
- generated `tc-sdlc.lock` binding the package, image, workflow, schema and
  compatible `tc-fitness` identities;
- stable Make targets for bootstrap, preparation, affected checks, complete
  checks, qualification and deployment;
- a thin GitHub workflow caller;
- branch rulesets and code-owner routing;
- dependency-update configuration;
- repository authoring entrypoints and resolver;
- secret scanning and Git hooks;
- release callers when the repository publishes artefacts;
- deployment callers when the repository owns a runtime target.

The repository adds its product source, tests, generators, qualification
journeys and deployment values to the declaration. Shared behaviour is added to
`tc-pipelines` or `tc-fitness` and released before adoption.

## Fitness configuration

Every adopted repository declares:

- a warm `smoke` profile;
- a complete `full` profile;
- a scheduled `nightly` profile when soak, mutation or compatibility work exists;
- the repository-specific configuration consumed by `tc-fitness`;
- the compatible engine identity supplied by the SDLC release catalogue.

`tc-sdlc` schedules the profile. `tc-fitness` evaluates it and emits structured
findings. The consumer owns product-specific thresholds and test commands.

## Verification

Adoption verification exercises behaviour from an empty checkout:

1. resolve and verify the release catalogue;
2. materialise the canonical environment;
3. validate `sdlc.yaml` and `tc-sdlc.lock`;
4. run preparation twice and confirm the second run is clean;
5. execute the affected graph;
6. execute the complete graph;
7. confirm the thin workflow emits the required status contexts;
8. verify branch rulesets reference contexts the workflow emits;
9. verify release and deployment entrypoints when configured.

The adoption change is complete when local and hosted task identities match and
the repository's required checks pass.

## Repository governance

The standard branch model uses protected `main`, merge commits, short-lived
feature branches, resolved review conversations and required status contexts.
Ordinary product changes merge on green. Human code-owner review covers the
environment, task graph, fitness policy, CI, release, deployment and governance
control plane.

GitHub App identities perform remote writes. Local commits use canonical
`three-cubes-agent[bot]` metadata. The credential contract is
[`../agent-sdlc-access-and-hitl.md`](../agent-sdlc-access-and-hitl.md).

## Secrets and hosted configuration

Runtime secrets remain in the approved secret store. GitHub variables and
short-lived workload identity select public deployment identifiers and grant
the minimum hosted capability. The repository contains templates and secret
names rather than hydrated values.

The adoption command reports each one-time hosted operation and verifies its
readback. Repository rulesets, environment reviewers, workload identities and
third-party project creation remain visible administrative changes.

## Existing bootstrap compatibility

`governance/scripts/bootstrap-repo-governance.sh` remains the current
compatibility entrypoint until `tc-sdlc adopt` implements the complete contract.
It renders the existing governance, `tc-fitness` and reusable-workflow surfaces.

During the executable-foundation tranche it becomes a wrapper around
`tc-sdlc adopt`. Its current flags and output remain covered by contract tests
through the declared migration window. New product capabilities enter the
package and schema rather than expanding the shell interface.

Repository merge methods remain an administrator-owned compatibility setting.
Apply and verify them explicitly during the current bootstrap:

```bash
gh api --method PATCH repos/three-cubes/<name> \
  -F allow_merge_commit=true \
  -F allow_squash_merge=false \
  -F allow_rebase_merge=false
governance/scripts/check-repository-merge-settings.sh three-cubes/<name>
```

## Adoption sequence

1. Create the repository and product ownership record.
2. Run `tc-sdlc adopt` against a released catalogue.
3. Add product projects, tests and qualification journeys to `sdlc.yaml`.
4. Run bootstrap, preparation, affected and complete checks.
5. Apply the reviewed repository governance and hosted identity changes.
6. Open the adoption PR and verify required contexts.
7. Exercise release and deployment rollback paths when configured.
8. Remove compatibility files after their consumer count reaches zero.

The detailed migration states and completion evidence are in
[`../../docs/MIGRATION.md`](../../docs/MIGRATION.md).
