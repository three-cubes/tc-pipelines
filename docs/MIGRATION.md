# AI SDLC Consumer Migration

This guide moves a repository from copied scripts and direct reusable-workflow
assembly to the released `tc-pipelines` SDLC product. The product contract lives
in
[`governance/standards/ai-sdlc-product-architecture.md`](../governance/standards/ai-sdlc-product-architecture.md).

## Migration states

| State | Consumer result |
|---|---|
| Declared | `sdlc.yaml` describes toolchains, projects, fitness profiles and product targets. |
| Locked | `tc-sdlc.lock` binds package, image, workflow, schema and `tc-fitness` identities. |
| Local | Stable Make commands execute through the released package. |
| Hosted | Thin GitHub workflows execute the same task graph in the canonical image. |
| Qualified | One immutable application digest passes local and hosted product journeys. |
| Deployed | Production applies that digest and records PVT, rollback and cleanup evidence. |
| Converged | Superseded consumer orchestration and independent pins are removed. |

Migrate one complete vertical before broad fleet adoption. `tc-agent-zone` is
the reference vertical because it exercises the full Python, TypeScript, Go,
container, state-harvest and VM deployment surface.

## 1. Inventory the consumer

Record:

- language package and workspace boundaries;
- generated inputs and outputs;
- current local commands;
- workflow jobs and triggers;
- fitness configuration and profiles;
- container build inputs and outputs;
- product qualification journeys;
- runtime state, secrets and ownership requirements;
- deployment and rollback commands;
- current workflow, action, fitness and toolchain pins.

Classify each item as shared SDLC behaviour or product behaviour using
[`RESOLVER.md`](../RESOLVER.md). Promote shared behaviour into `tc-pipelines` or
`tc-fitness` before consumer adoption.

## 2. Add the declaration and lock

Add `sdlc.yaml` at the repository root. Declare real projects and dependencies;
represent Python workspaces, pnpm packages, Go modules, generators, images and
qualification journeys as graph nodes.

Generate `tc-sdlc.lock` from one released catalogue. Commit the declaration and
lock together. The upgrade command owns later changes to package, image,
workflow and `tc-fitness` identities.

## 3. Adopt stable local commands

Route the repository Makefile through `tc-sdlc`:

```make
.PHONY: bootstrap prepare check check-all qualify deploy

bootstrap:
	tc-sdlc bootstrap

prepare:
	tc-sdlc prepare

check:
	tc-sdlc check --affected

check-all:
	tc-sdlc check --all

qualify:
	tc-sdlc qualify

deploy:
	tc-sdlc deploy
```

Keep product-specific commands behind graph targets. The shared command names
remain consistent across repositories.

Run preparation twice. The first run applies required deterministic changes;
the second run produces no diff. Run affected and complete checks and retain
their task identities.

## 4. Move hosted CI to the graph

Replace consumer job implementation with a thin call to the released workflow.
The hosted layer supplies:

- GitHub event and exact integration identity;
- runner allocation;
- short-lived credentials;
- protected environment decisions;
- retained task and release evidence.

The graph supplies task selection, ordering, concurrency and commands. Validate
one representative change for each language and generator boundary. Compare
task identity and lock digest with the local run.

Remove post-merge evaluation when the merge queue or exact-integration evidence
proves the admitted tree and the post-merge work produces no distinct release
outcome.

The existing Azure compatibility caller inherits workflow permissions. A caller
that uses WIF and no GHCR token declares:

```yaml
permissions:
  contents: read
  id-token: write
```

The hosted job adds package access only when it opts into the documented token
transport. The coordinated deployment path replaces this caller after the typed
SSH/Azure transport passes the same acceptance journeys.

## 5. Integrate tc-fitness

Bind the consumer's `smoke`, `full` and `nightly` profiles in `sdlc.yaml`.
Retain the native `tc-fitness` configuration as the check catalogue and policy
source. The released SDLC catalogue supplies the compatible engine version.

Verify:

- affected checks run in the warm local graph;
- complete checks run for release admission;
- nightly checks retain failures and diagnostics;
- task sharding preserves coverage and fitness semantics;
- a change to the engine version arrives through the coordinated SDLC upgrade.

## 6. Qualify one immutable candidate

Build the application image once and record its digest. Run local and hosted
qualification against that digest. Exercise:

- clean startup and dependency health;
- required files, directories, symlinks and permissions;
- secrets and environment resolution;
- persistent-state harvest and restore;
- representative product journeys;
- failure diagnostics and cleanup.

Qualification produces the candidate receipt consumed by deployment.

## 7. Adopt the deployment transaction

Converge host prerequisites through the shared Ansible roles. Keep product
Compose definitions, state mappings, agent definitions and PVT journeys in the
consumer.

Exercise these paths before production reliance:

1. status and preflight;
2. repeated host convergence with zero second-run changes;
3. successful candidate start and PVT;
4. failed health check and predecessor restoration;
5. failed PVT and predecessor restoration;
6. interrupted operation and lock recovery;
7. cleanup with active and predecessor images retained.

The Cloudflare SSH and Azure transports accept the same typed operation and
return the same receipt. Select transport through deployment configuration.

## 8. Remove superseded surfaces

Produce a removal inventory that names each old file, its replacement and the
evidence that the replacement has passed. Remove items after their consumer
count reaches zero.

Typical removal candidates include:

- copied workflow jobs;
- consumer-specific tool installation;
- shell task schedulers;
- independent workflow and fitness repin scripts;
- VM-side application builds;
- untyped deployment payloads;
- duplicate full post-merge checks;
- manual cleanup commands replaced by lifecycle policy.

## Rollback during migration

The generated lock identifies the previous coordinated SDLC release. Revert the
declaration and lock together and execute the previous released environment.
For application deployment, select the previous qualified image digest and its
state receipt.

Retain the current compatibility workflow until the corresponding package/image
path has passed its consumer acceptance journey. This provides a bounded rollback
path while keeping one documented target architecture.

## Migration completion evidence

A consumer is converged when:

- the declaration and lock are committed;
- local and hosted task identities match;
- the affected loop meets the 60-second target;
- the complete graph is green;
- `tc-fitness` runs through the graph;
- one candidate digest passes local qualification, hosted qualification and
  production PVT;
- rollback has been exercised;
- superseded orchestration is removed;
- the release and deployment receipts are retained and linked from the change.
