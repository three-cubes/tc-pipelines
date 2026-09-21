# AI SDLC Implementation Roadmap

This roadmap delivers the architecture in
[`governance/standards/ai-sdlc-product-architecture.md`](../governance/standards/ai-sdlc-product-architecture.md).
It records the executable tranches, dependencies and exit evidence. Product
boundaries and requirements live in the standard; this document records delivery.

## Current state

| Capability | Current implementation | Target implementation |
|---|---|---|
| Environment | Consumer-managed uv, pnpm, Go, shell and runner setup | Versioned canonical OCI/Dev Container image plus catalogue-driven native bootstrap |
| Orchestration | Make, shell, `tc-fitness` configuration and workflow YAML collectively order work | Nx task graph supplied by `@three-cubes/tc-sdlc` |
| Fitness | `tc-fitness` invoked directly by Python reusable workflows and consumer Makefiles | Version-compatible `tc-fitness` profiles executed as graph tasks |
| CI | Reusable workflows contain substantial task orchestration | Thin workflows provide events, runners, credentials and protected environments |
| Releases | Workflow and package pins advance through separate mechanisms | One release catalogue and generated consumer lock |
| Deployment | Azure workflow transports consumer-authored scripts and performs infrastructure smoke | Qualified digest, typed transaction, host convergence, product PVT and rollback receipt |
| Consumer adoption | Governance bootstrap copies several executable fragments | One declaration, one generated lock and thin stable commands |

The migration retains the current workflows until their replacement passes the
same consumer acceptance journeys.

The current Azure compatibility caller maps the job token through the reusable's
declared secret only when protected GHCR transport is selected:

```yaml
jobs:
  deploy:
    secrets:
      ghcr-actions-token: ${{ secrets.GITHUB_TOKEN }}
```

This mapping remains contract-tested until the deployment graph replaces the
legacy apply path.

## Delivery rules

- Each tranche produces working software and terminal verification evidence.
- `tc-agent-zone` is the first complete vertical consumer.
- The current entrypoint remains available until its replacement passes local,
  CI and consumer acceptance checks.
- Shared behaviour lands in `tc-pipelines`; evaluation behaviour lands in
  `tc-fitness`; product behaviour remains in the consumer.
- Tranche PRs group coherent deliverables. Cross-repository dependency releases
  use separate PRs because each repository has an independent protected trunk.
- Deletion follows proven parity and a recorded consumer inventory.

## Tranche 1 — Product contract

**Status:** in progress

**Deliverables**

- canonical AI SDLC architecture;
- repository resolver and ownership boundaries;
- README, standards, migration and cost documentation aligned to that architecture;
- `tc-fitness` defined as a core pipeline component;
- superseded architectural instructions removed;
- implementation acceptance fixtures specified.

**Exit evidence**

- every canonical index points to one product architecture;
- repository searches return no active statement that workflows and composite
  actions alone are the product;
- current commands remain accurately documented as migration surfaces;
- the full `tc-pipelines` self-gate passes.

**Elapsed target:** 1–2 working days.

## Tranche 2 — Executable foundation

**Status:** in progress

**Deliverables**

- `packages/tc-sdlc/` with the Nx preset, CLI, schema loader and graph executors;
- `images/sdlc/` with the canonical Dev Container/OCI image;
- `sdlc.yaml` schema and generated `tc-sdlc.lock`;
- `bootstrap`, `prepare`, `check` and `check-all` commands;
- release catalogue generation;
- Python-only, pnpm-only and mixed-language acceptance fixtures.

### Implementation contract

The tranche lands as one coherent release candidate. Tasks below are ordered by
their public interfaces; implementation follows test-driven development and
each task remains independently executable before the next consumes it.

**Global constraints**

- Node `24`, pnpm `11.22.0`, Nx and `@nx/devkit` `23.2.1`, TypeScript
  `7.0.2`, Vitest `5.0.1`, `yaml` `2.9.1`, Ajv `8.20.0` and `@types/node`
  `24.13.6` are exact pins.
- Python is `3.13`, uv is `0.12.5`, and the coordinated fitness engine is
  `three-cubes-fitness` `0.16.1`.
- Runtime package dependencies use exact versions. Internal workspace
  dependencies use `workspace:*` and resolve through the root
  `pnpm-lock.yaml`.
- Public schemas are versioned and reject unknown fields. Generated locks and
  receipts are canonical, deterministic and POSIX-path serialised.
- Behavioural tests invoke public package or process interfaces. Runtime and
  end-to-end tiers use no monkeypatching, mocks or test-only production seams.
- No baseline, grandfathering, suppression or compatibility-only bypass may
  satisfy a Tranche 2 acceptance condition.

### Task 1 — Declaration, release catalogue and generated lock

**Status:** complete and independently reviewed (`a64ddea`)

**Files**

- `packages/tc-sdlc/src/schema/` owns `sdlc.yaml`, release-catalogue and lock
  validation.
- `packages/tc-sdlc/src/lock/` resolves one catalogue entry into
  `tc-sdlc.lock`.
- `packages/tc-sdlc/src/cli.ts` exposes `validate` and `lock`.
- `schemas/` publishes the three versioned JSON schemas.
- `packages/tc-sdlc/src/catalogue/` creates and validates catalogue entries
  that bind the package, workflow commit, image digest, schema and compatible
  `tc-fitness` release. The first repository catalogue is published by Task 5
  after the canonical image digest exists.

**Interfaces**

```ts
export type SdlcDeclaration = Readonly<{
  schema: "tc.sdlc/v1";
  project: string;
  toolchains: Readonly<Record<string, string>>;
  fitness: Readonly<Record<string, string>>;
  projects: readonly ProjectDeclaration[];
  targets: Readonly<Record<string, TargetDeclaration>>;
}>;

export function loadDeclaration(path: string): SdlcDeclaration;
export function resolveLock(
  declaration: SdlcDeclaration,
  catalogue: ReleaseCatalogue,
): SdlcLock;
export function writeLock(path: string, lock: SdlcLock): void;
```

The lock is canonical JSON and binds the declaration digest, catalogue release,
package version, workflow commit, image digest, schema version, fitness version
and toolchain versions. A stale, hand-edited or partially upgraded lock fails
before task planning.

### Task 2 — Deterministic graph and affected selection

**Status:** complete and independently reviewed (`5029696`)

**Files**

- `packages/tc-sdlc/src/graph/` owns project discovery, dependency closure,
  affected selection and task identity.
- `packages/tc-sdlc/src/executors/` owns the Nx executors consumed by graph
  targets.
- `packages/tc-sdlc/src/preset/` maps a declaration to an Nx project graph.

**Interfaces**

```ts
export function bindGraphLock(
  declaration: SdlcDeclaration,
  lock: SdlcLock,
  catalogue: ReleaseCatalogue,
  inputs: TaskInputDigests,
  options?: GraphLockBindingOptions,
): SdlcLock;
export function buildGraph(
  declaration: SdlcDeclaration,
  lock: SdlcLock,
): SdlcGraph;
export function selectAffected(
  graph: SdlcGraph,
  changedPaths: readonly string[],
): readonly TaskIdentity[];
export function taskIdentity(
  task: TaskDeclaration,
  inputs: readonly InputDigest[],
  lockDigest: string,
): string;
```

`bindGraphLock` proves catalogue and content-input authority before graph
construction. `buildGraph` recomputes the lock and refuses an unbound or stale
lock. Selection includes changed projects, generator outputs and downstream
consumers. Task identity is independent of checkout location, operating-system
path syntax, filesystem case policy, worker count and execution order.

### Task 3 — Resource-aware execution and terminal diagnostics

**Status:** complete and independently reviewed (`227a7bb`)

**Files**

- `packages/tc-sdlc/src/runtime/` owns resource admission, execution,
  cancellation and event recording.
- `packages/tc-sdlc/src/evidence/` owns task receipts and retained diagnostics.

**Interfaces**

```ts
export function runGraph(
  graph: SdlcGraph,
  selection: readonly TaskIdentity[],
  options: RunOptions,
): Promise<RunReceipt>;
```

Each task declares CPU, memory, ports and exclusive resources. The scheduler
runs independent tasks up to measured host capacity without oversubscribing a
declared resource. Each task emits start, heartbeat, output, cancellation and
terminal events. Phase budgets are task-owned and measured; a no-progress
condition captures process and resource diagnostics, terminates the process
group and records `stalled`, while an operator cancellation records
`cancelled`. No workflow-wide timeout substitutes for task state.

### Task 4 — Preparation, evaluation and evidence reuse

**Status:** complete and independently reviewed (`ea61ca0`, `8aad84b`, `631422e`)

**Files**

- `packages/tc-sdlc/src/tasks/prepare.ts` runs deterministic mutating work.
- `packages/tc-sdlc/src/tasks/check.ts` runs read-only affected evaluation.
- `packages/tc-sdlc/src/tasks/check-all.ts` runs the release-admission graph.
- `packages/tc-sdlc/src/cache/` owns content-addressed pure-task results.
- `packages/tc-sdlc/src/inputs/` resolves one canonical digest inventory for
  graph planning, execution receipts and cache admission.

`prepare` applies formatting, generators, lock refresh and manifest refresh once,
then proves a second execution is a fixed point. `check` and `check-all` reject
tree mutation. A successful local task receipt can satisfy CI only when its
source tree, lock, task, inputs, environment class and producer identity match;
hosted-only and live boundaries still execute at their owning trust boundary.

`check` and `check-all` are selection modes over the Task 3 scheduler, not
separate runners. `check` supplies the dependency-closed result from
`selectAffected`; `check-all` supplies every graph task exactly once.

Three evidence contracts remain separate:

- the scheduler run receipt records execution and diagnostics;
- the preparation receipt records a bounded, fixed-point mutation for trusted
  writeback;
- the evaluation receipt binds source tree, declaration, catalogue, lock, task,
  canonical input digests, environment class, producer identity and output
  digests for cache or CI admission.

A local evaluation receipt may warm the content-addressed cache. It satisfies a
required CI result only when an allowed producer authenticates it and every
bound identity matches the candidate. Hosted credentials, security checks,
deployment work and mutable network or live-system checks always execute at
their owning trust boundary.

### Task 5 — Native bootstrap and canonical Linux image

**Files**

- `packages/tc-sdlc/src/bootstrap/` resolves capabilities and materialises the
  catalogue-owned toolchain on macOS or Linux.
- `images/sdlc/` builds the canonical OCI and Dev Container environment.
- `.devcontainer/` selects the image by immutable digest.
- `release/catalogue.json` records the built package, workflow commit, image
  digest, schema and compatible `tc-fitness` release as one complete entry.

Bootstrap consumes the release catalogue and generated lock. It reports missing
host capabilities with one actionable command and does not depend on state under
a particular user's home directory. Native macOS/Linux and the canonical image
must report the same SDLC release, lock digest and task identities.

The developer-environment lifecycle is part of these commands, not an optional
operator chore. Each command removes its own scratch in `finally`; bootstrap,
prepare and evaluation also recover interrupted, owner-marked scratch older than
48 hours and bind that outcome into their terminal receipt. `tc-sdlc maintain`
provides dry-run and apply receipts for the same bounded policy. It never scans
foreign roots or deployment data. Deletion workers revalidate and atomically
re-quarantine complete roots before synchronous removal, so path replacement
cannot redirect an asynchronous recursive delete. Worker terminal budgets and
observed peak concurrency are recorded in maintenance evidence. Materialised
bootstrap states carry stable local-consumer references: maintenance retains
every current state and immediate predecessor and expires only old states made
explicitly unreferenced by valid producer metadata. Bootstrap references bind
the exact state filesystem identity; after atomic publication bootstrap
revalidates that identity and rolls back only its unchanged publication if
state moved. Maintenance moves an identity-matched candidate into quarantine,
refreshes references, and restores the candidate when a matching reference
appeared during the move. A changed identity never grants deletion authority.
Cleanup setup failures retain the candidate and terminate in a canonical failed
maintenance receipt. The release-image producer uses a named tc-sdlc BuildKit
builder and state-owned Docker configuration with explicit daemon routing;
release artefacts remain retained until catalogue/current/predecessor or incident
references provide deletion authority. Task 5 emits that retention declaration
but deliberately implements no successful-release artefact collector: until a
canonical reference inventory exists, successful artefacts are retained.

### Task 6 — Disposable consumers and hosted adapter

**Files**

- `assurance/fixtures/sdlc/` contains Python-only, pnpm-only and mixed-language
  consumers.
- `assurance/run.py` invokes the released CLI instead of compatibility command
  arrays for these cases.
- `.github/workflows/hosted-assurance.yml` provides runner allocation and hosted
  identity while executing the same CLI contract.

Each fixture proves clean bootstrap, preparation fixed point, affected closure,
full graph execution, stable identity across worker counts, and retained failure
evidence. Sabotage cases change one declaration, lock, input, output, environment
or receipt boundary and must be rejected for that boundary.

**Behavioural evidence**

1. Start each fixture from an empty checkout.
2. Bootstrap the released environment.
3. Run preparation twice and observe no second-run changes.
4. Change one project and observe the expected affected graph.
5. Run the same task identity natively, in the canonical image and in a hosted workflow.
6. Record matching lock, input and task identities.

**Exit criteria**

- clean bootstrap works on supported macOS and Linux paths;
- the canonical image executes every fixture;
- warm affected feedback completes within 60 seconds for the reference fixture;
- `tc-fitness` executes as a graph task with the catalogue-declared version;
- task concurrency uses declared CPU and resource limits.

**Elapsed target:** 3–5 working days.

## Tranche 3 — tc-agent-zone vertical adoption

**Status:** depends on Tranche 2 release

**Deliverables**

- `tc-agent-zone/sdlc.yaml` and generated lock;
- Python, pnpm, Go, generator and fitness projects represented in the graph;
- preparation separated from read-only evaluation;
- existing Make commands routed through `tc-sdlc`;
- one thin PR workflow executing the affected graph;
- duplicate post-merge evaluation removed after exact-integration evidence is live.

**Behavioural evidence**

- affected changes select their direct and dependent projects;
- generator input changes refresh the declared output before evaluation;
- isolated tasks remain deterministic across worker counts and execution order;
- local and hosted runs report the same task and lock identities;
- a complete graph run preserves current coverage, security and fitness obligations.

**Exit criteria**

- the ordinary local loop no longer enters consumer-specific orchestration scripts;
- PR CI executes the graph once;
- exact integration evidence promotes without repeating equivalent work;
- existing tests and gates retain their behavioural coverage.

**Elapsed target:** 3–4 working days.

## Tranche 4 — Immutable release qualification

**Status:** depends on Tranche 3

**Deliverables**

- one container build task producing an OCI digest and provenance receipt;
- local Compose qualification consuming that digest;
- production-shaped filesystem, permissions, secrets and dependency checks;
- knowledge-harvest input and output identities in the qualification receipt;
- retained failure diagnostics with bounded secret-safe output.

**Exit criteria**

- one candidate digest passes local and hosted qualification;
- qualification never rebuilds the candidate;
- representative Hermes journeys exercise real container boundaries;
- failure cases retain actionable evidence and leave the host clean.

**Elapsed target:** 3–4 working days.

## Tranche 5 — Repeatable VM deployment

**Status:** depends on Tranche 4

**Deliverables**

- Ansible roles for host users, groups, shared filesystem permissions, Docker,
  Cloudflare SSH, scoped sudo and cleanup timers;
- Molecule tests proving host convergence and idempotence;
- Docker Compose deployment by qualified digest;
- typed harvest, apply, health, PVT, promotion and rollback operations;
- SSH and Azure transports implementing the same request and receipt contract;
- automatic cleanup of expired images, build cache and deployment artefacts.

**Exit criteria**

- a second host convergence reports no changes;
- a failed health or PVT journey restores the predecessor digest;
- harvested learning persists across cutover and its identity is recorded;
- production PVT passes against the deployed digest;
- cleanup retains the active, predecessor and evidence window and removes expired data.

**Elapsed target:** 4–5 working days.

## Tranche 6 — Fleet convergence and removal

**Status:** depends on a successful tc-agent-zone production deployment

**Deliverables**

- adopt the released product in `tc-fitness`, kairix and remaining consumers;
- automated coordinated upgrade PRs;
- remove superseded workflow orchestration, copied scripts and independent pins;
- publish fleet timing, cache and failure-classification measures.

**Exit criteria**

- each active repository uses a released SDLC catalogue and generated lock;
- consumer repositories retain only product-specific build and deployment logic;
- every compatibility surface has zero consumers before removal;
- scheduled and PR workflows have distinct documented outcomes;
- CI and infrastructure consumption are observable by repository and task.

**Elapsed target:** 3–5 working days after the first production proof.

## Expected elapsed delivery

| Milestone | Target |
|---|---:|
| Importable foundation and reference fixture | within 5 working days of approved Tranche 1 |
| tc-agent-zone local and CI vertical | within 10 working days |
| Qualified Hermes production deployment | within 15 working days |
| Fleet convergence and old-path removal | within 20 working days |

Independent fixture, image and deployment preparation can overlap. Contract
changes, coordinated releases and production mutations remain ordered.

## Measures

Record these values for every tranche:

- cold bootstrap duration;
- warm affected-check duration;
- full graph duration;
- CPU utilisation and peak memory;
- cache hit rate by task;
- CI minutes per merged change;
- duplicate hosted task executions;
- failures classified as product, test, environment or external dependency;
- release qualification duration;
- deployment, PVT and rollback duration;
- retained and expired disk consumption.

Measurements guide optimisation after redundant work has been removed.
