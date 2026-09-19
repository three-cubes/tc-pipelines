# tc-pipelines

`tc-pipelines` is the shared Three Cubes AI SDLC product. It provides the
versioned development environment, task orchestration, CI workflows, release
and deployment protocols, evidence contracts and governance templates used by
Three Cubes repositories.

The canonical architecture is
[`governance/standards/ai-sdlc-product-architecture.md`](governance/standards/ai-sdlc-product-architecture.md).
[`RESOLVER.md`](RESOLVER.md) routes changes to their canonical home.

Run `make assurance` for the [published-surface inventory and disposable consumer
lab](assurance/README.md). It retains local behavioural evidence separately from
hosted adapter and release-admission proof.

## Product model

```text
consumer sdlc.yaml + product tests
                 |
                 v
       tc-pipelines SDLC release
       ├── @three-cubes/tc-sdlc
       ├── canonical OCI development image
       ├── reusable GitHub workflows
       ├── release/deployment protocols
       └── governance library
                 |
                 v
          tc-fitness evaluation
                 |
                 v
       immutable candidate + evidence
                 |
                 v
       production PVT or rollback
```

`tc-fitness` is a core component of the SDLC product. `tc-pipelines` supplies
the environment, task graph and evidence handoff. `tc-fitness` supplies the
executable check catalogue and evaluation semantics. A coordinated
`tc-pipelines` release records the compatible `tc-fitness` version.

Consumer repositories retain their source, product tests, qualification
journeys and deployment values. They consume the shared product through one
small declaration, one generated lock, thin Make targets and thin hosted
workflow callers.

## Current delivery state

The repository currently ships the reusable workflows, composite actions,
release/deployment contracts, governance library and `tc-fitness` integration.
The executable-foundation tranche adds the `tc-sdlc` package, canonical image,
task graph and coordinated release catalogue described by the architecture.

Current workflows remain supported during that migration. Their responsibilities
move behind the shared package and task graph before the old entrypoints are
removed.

Track the delivery order and exit criteria in
[`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md). Follow
[`docs/MIGRATION.md`](docs/MIGRATION.md) when moving a consumer.

## Stable consumer commands

The target consumer interface is:

| Command | Purpose |
|---|---|
| `make bootstrap` | Materialise the released environment and dependencies. |
| `make prepare` | Apply deterministic generators, formatting, locks and manifest repairs. |
| `make check` | Run affected checks, including the configured `tc-fitness` profile. |
| `make check-all` | Run the complete verification graph. |
| `make qualify` | Build and exercise the immutable release candidate. |
| `make deploy` | Submit the qualified candidate to the protected deployment path. |

Until the executable foundation is released, existing consumers continue to
use their current `make check` and reusable-workflow callers. Migration replaces
those internals while retaining these stable command names.

## Repository contents

| Path | Purpose |
|---|---|
| `governance/standards/` | Canonical AI SDLC, development, testing, release and deployment standards. |
| `governance/skeletons/` | Consumer repository declarations and authoring entrypoints. |
| `.github/workflows/` | Hosted workflow entrypoints and current migration-layer orchestration. |
| `actions/` | Reusable CI composite actions. |
| `.github/actions/` | Hosted deployment composite actions. |
| `infra/` | Shared cloud identity and infrastructure modules. |
| `tools/` | Trusted host and platform tooling. |
| `packages/tc-sdlc/` | Shared SDLC package; introduced by the executable-foundation tranche. |
| `images/sdlc/` | Canonical development image; introduced by the executable-foundation tranche. |

## tc-fitness integration

Consumers declare their fitness configuration in `sdlc.yaml` and the native
`tc-fitness` configuration file. `tc-sdlc` resolves the compatible engine from
the coordinated release and executes the selected profile as a graph task.

The standard profiles are:

| Profile | Purpose |
|---|---|
| `smoke` | Warm affected feedback under 60 seconds. |
| `full` | Complete repository verification and release admission. |
| `nightly` | Soak, mutation and broad compatibility evaluation. |

The current migration-layer Python workflow runs `uv run tc-fitness run` from
the consuming repository's `[tool.tc_fitness]` or `.tc-fitness.toml`
configuration. This remains the compatibility path until the task graph owns
the invocation.

## Hosted workflow surfaces

The current reusable workflows remain supported while their implementation is
moved behind `tc-sdlc`:

| Surface | Purpose |
|---|---|
| `python-quality-gate.yml` | Current Python and `tc-fitness` compatibility gate. |
| `meta-quality-gate.yml` | Workflow/action repository hygiene. |
| `docker-build-publish.yml` | Build and publish an immutable container image. |
| `actions/prepare-release-metadata` | Prepare release metadata on the candidate branch: update the version source and uv lock, promote changelog notes and commit the preparation receipt. |
| `release-on-merge.yml` and `release.yml` | Publish the already prepared release from the exact reviewed merge commit. Both validate the committed preparation receipt; neither prepares it. |
| `azure-vm-deploy.yml` | Current Azure VM deployment compatibility path. |
| `.github/actions/prune-azure-vm-snapshots` | Delete expired recovery snapshots for the current Azure compatibility path; each snapshotting consumer schedules it. |
| `mutation-gate.yml` | Diff-scoped mutation evaluation. |
| `fresh-install-smoke.yml` | Clean environment installation exercise. |
| `independent-verifier.yml` | Independent evidence verification. |

New workflow logic belongs in the task graph when it can run locally. Hosted
workflow YAML owns GitHub credentials, protected environments, runner allocation
and GitHub event handling.

## Release and deployment

A release candidate is built once and identified by an immutable OCI digest.
Local qualification, CI qualification and production deployment consume that
digest. GitHub records build provenance; deployment records the runtime identity,
PVT result, rollback result and cleanup result.

The generic deployment transaction belongs here. Product state, knowledge
harvesting, runtime configuration and PVT journeys belong in the consumer.
Ansible converges host prerequisites and Docker Compose applies the qualified
single-host application stack.

The current container-only deployment path uses the protected-state and
predecessor-image recovery contract documented in
[`snapshot-before-apply.md`](governance/standards/snapshot-before-apply.md) while
the typed Ansible/Compose transaction is implemented.

The complete contract is
[`governance/standards/ci-release-deployment-architecture.md`](governance/standards/ci-release-deployment-architecture.md).

## Governance and identity

Ordinary work merges on a green gate. Changes to SDLC control-plane files are
reviewed by the human code owner. Agents create local commits with canonical
`three-cubes-agent[bot]` metadata; trusted brokers and GitHub Actions use
short-lived GitHub App credentials for remote writes.

The access contract is
[`governance/agent-sdlc-access-and-hitl.md`](governance/agent-sdlc-access-and-hitl.md).
The canonical standards index is
[`governance/STANDARDS.md`](governance/STANDARDS.md).

## Contributing

Read, in order:

1. [`AGENTS.md`](AGENTS.md)
2. [`RESOLVER.md`](RESOLVER.md)
3. [`governance/STANDARDS.md`](governance/STANDARDS.md)
4. the standard governing the surface being changed

Run the current self-gate with:

```bash
make check
```

The repository will move its own self-gate behind `tc-sdlc` during the
executable-foundation tranche. Verification evidence requires a complete
terminal result from the current command.

## Versioning

Consumers pin immutable release identities. The coordinated release catalogue
binds the npm package version, canonical image digest, workflow commit, schema
version and compatible `tc-fitness` version. The upgrade command updates these
surfaces in one reviewable change.

Existing direct workflow SHA pins remain valid during migration and are removed
after each consumer reaches the converged state.

## Licence

Apache-2.0. See [`LICENSE`](LICENSE).
