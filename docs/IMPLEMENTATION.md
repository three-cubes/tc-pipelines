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

## Definition of done and evidence status

This ledger is the canonical progress view for the AI SDLC delivery. A row is
`VERIFIED` only when its implementation is committed and its behavioural tests
have passed against that commit. Work in another worktree, a successful probe,
or a structural assertion does not complete a row.

States:

- `VERIFIED` — committed implementation plus terminal behavioural evidence;
- `IN PROGRESS` — implementation or evidence is incomplete or not integrated;
- `NOT STARTED` — depends on an earlier release boundary.

### Foundation PR acceptance

| ID | Acceptance criterion | State | Verified evidence | Remaining work |
|---|---|---|---|---|
| F1 | One versioned declaration, catalogue and generated lock reject stale or partial upgrades. | VERIFIED | Task 1 independently reviewed at `a64ddea`; public CLI and schema tests exercise validation and lock generation. | None. |
| F2 | One deterministic graph computes dependency-closed affected work and stable task identities. | VERIFIED | Task 2 independently reviewed at `5029696`; graph tests cover downstream closure and identity invariants. | None. |
| F3 | Resource-aware execution runs independent tasks concurrently and retains terminal diagnostics for failure, stall and cancellation. | VERIFIED | Task 3 independently reviewed at `227a7bb`; runtime tests exercise resource admission, process termination and terminal receipts. | None. |
| F4 | Preparation is deterministic and reaches a fixed point; evaluation is read-only; reusable evidence is identity-bound. | VERIFIED | Task 4 independently reviewed at `ea61ca0`, `8aad84b` and `631422e`; preparation, evaluation, cache and sabotage tests pass. | None. |
| F5 | Native macOS/Linux bootstrap owns exact Node, pnpm, Python and uv execution state without ambient user configuration. | VERIFIED | Bootstrap and lifecycle implementation through `896bd4c`; package suite 131/131, Darwin integration 19/19 and Docker lifecycle probes 2/2 passed. Independent review reproduced both final recovery regressions against the parent and passed the fixes. | None for the native bootstrap boundary. |
| F6 | Concurrent bootstrap, state invalidation and maintenance preserve one valid current/predecessor state across crash, alias and replacement races. | VERIFIED | Bootstrap lifecycle implementation through `8e0bc391`; build, package suite 151/151, focused public recovery 3/3, Darwin integration 25/25 and Docker lifecycle 2/2 passed. Independent review reproduced referenced and pre-reference corruption, invalid authority and live-lease cases through the public CLI and found no material issue. | None. |
| F7 | Python-only, pnpm-only and mixed consumers use real locked dependencies through the packed public CLI. | VERIFIED | Disposable-consumer implementation through `4eaa0234`; build, package suite 151/151 and packed public journeys 5/5 passed. Independent review verified exact Python and Node dependencies, mixed downstream closure, local dependency-shadow resistance, hostile launcher-environment isolation, executable packaging from paths containing spaces and zero-download offline frozen replay from an isolated seeded store. | None. |
| F8 | `tc-fitness` `0.17.1` runs once as an independently executable, repository-scoped graph task and a version mismatch is rejected. | VERIFIED | Implementation at `062e16e`; direct packed acceptance at `03e136a` and `dcf742f` uses genuine bootstrap state, validates owned and nested evidence, proves exactly one fitness task, preserves the checkout and verifies scratch removal. The exact-head fast suite passed 153/153 and the full repository gate passed 1,991/1,991. | None. |
| F9 | Native, canonical-image and hosted runs bind the same source, lock, input and task identities. | IN PROGRESS | The exact multi-platform image producer completed one local-registry qualification; that image-only proof is retained but is not release admission. | Run every disposable consumer on native and exact-image boundaries; add hosted identity evidence; parse terminal receipts and compare recomputed identities. |
| F10 | Warm affected feedback is under 60 seconds and concurrency honours detected CPU and declared resources. | IN PROGRESS | Scheduler resource semantics are verified by Task 3. | Measure the retained consumer result rather than a self-reported value; prove one-core/multi-core determinism, maximum safe workers, observed peak concurrency and the hard warm-loop budget. |
| F11 | The immutable amd64/arm64 image is published by digest with provenance, SBOM and installed-tool verification. | IN PROGRESS | The image-only producer published and re-used an exact local-registry index with both platform probes passing. | Integrate the reviewed producer; rerun the exact image proof after Task 6 and release-transport changes; retain cleanup results. |
| F12 | Public components are accepted at their own command and receipt boundaries; native, image and hosted composers then prove handoffs; release admission derives every claim from retained qualification evidence. | IN PROGRESS | Bootstrap, preparation, `check`, `check-all` and fitness have direct packed acceptance through `769042d`. Native consumer composition passes 17/17 without detached receipt races. | Implement and accept image production, image qualification and hosted composition; then prove their receipt handoffs through release admission. |
| F13 | Only a successful image plus functional qualification may generate the catalogue and Dev Container files. | IN PROGRESS | Unqualified tracked catalogue and Dev Container authority was removed at `318656a`; generation now requires both receipt inputs on the release branch. | Complete validator integration and prove failed, stale or altered inputs cannot create either output. |
| F14 | A trusted bot writes exactly the two generated outputs to the unchanged PR head with an exact Git lease. | IN PROGRESS | Event selection, output allowlist, bot identity and lease-safe transport have focused tests on the release branch. | Integrate the workflow; verify immutable credential code, normal Git hooks, post-hook byte checks, early-failure evidence and real hosted writeback. |
| F15 | All commands clean owned scratch and containers while retaining required release and failure evidence. | IN PROGRESS | Native lifecycle cleanup and recovery are verified through Task 5; image producer cleanup passed its local-registry run. | Assert registry, builder, container, image and state cleanup in the final exact-image journey and preserve referenced release artefacts. |
| F16 | The consolidated branch passes the repository's complete local admission path with a clean worktree. | IN PROGRESS | F1–F8 have passing behavioural evidence on independently reviewed component commits. The exact head passes 153 package tests, direct evaluation and fitness acceptance, the 1,991-test repository gate and the Docker builder. | Complete F9–F15, then pass Darwin integration, exact-image qualification, Python assurance and the complete local admission path on the exact head. |
| F17 | PR CI evaluates that exact head once, retains terminal evidence and has no unresolved review conversations. | IN PROGRESS | PR #157 exists as the single foundation PR. Its remote head predates the accepted Task 5 work. | Push once after F6–F16 pass locally; resolve review findings; obtain green required checks and review. |

The foundation PR is usable when F1–F17 are `VERIFIED`. A generated catalogue
or Dev Container file by itself is not completion; both must be the output of
the same successful image and functional qualification chain.

### End-to-end adoption and production acceptance

These rows start after the foundation release is published. They track the
program outcome and are not hidden inside the foundation PR's completion claim.

| ID | Acceptance criterion | State | Dependency |
|---|---|---|---|
| A1 | Publish the coordinated `tc-pipelines` release: package, immutable workflow commit, image digest, schemas and compatible `tc-fitness` version. | NOT STARTED | F1–F17. |
| A2 | Adopt the released product in `tc-agent-zone` with one `sdlc.yaml`, one generated lock and stable Make entrypoints. | NOT STARTED | A1. |
| A3 | Represent Python, pnpm, Go, generators, fitness and qualification journeys in the consumer graph; remove duplicate orchestration and duplicate post-merge evaluation after parity. | NOT STARTED | A2. |
| A4 | Build a Hermes candidate once, harvest and bind current learning artefacts, and qualify the candidate before production mutation. | NOT STARTED | A3. |
| A5 | Deploy the qualified digest, run product PVT, cut over, retain rollback authority and restore successor learning/state. | NOT STARTED | A4. |
| A6 | Finish with terminal `KNOWN_GOOD` evidence, automated cleanup and a repeatable second release without tactical VM patches. | NOT STARTED | A5. |

## Tranche 1 — Product contract

**Status:** in progress

The bootstrap lifecycle, consumer graph and repository-scoped fitness target
are independently executable and verified through F8. Native consumer
qualification is implemented and accepted as a separate composition journey.
Image production, image qualification, release admission, release generation,
writeback and hosted composition remain incomplete.

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
  `three-cubes-fitness` `0.17.1`.
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

**Status:** native bootstrap complete and independently reviewed through
`896bd4c`; immutable image publication remains in progress and cannot publish
the release catalogue until Task 6 functional qualification succeeds.

The canonical `produce-image` component is complete and independently reviewed
with packed-CLI failure-contract and disposable-registry acceptance. It publishes one
multi-platform candidate, verifies the remote digest plus subject-bound
provenance/SBOM, and reuses only source-matching registry evidence. Independent
review found no remaining Critical or Important issues, and the exact clean-head
repository gate passes with the image suites inside the canonical fitness graph.
Image qualification and release admission stay separate Task 6 boundaries.

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
On macOS, Homebrew supplies the reviewed Node, Python and uv prerequisites;
bootstrap invokes Corepack with an owned `COREPACK_HOME` to materialise the
exact declared pnpm distribution beneath the immutable release state. The
launcher executes that state-owned distribution directly. Ambient Corepack
selection is neither read nor mutated, and the complete distribution digest is
bound into bootstrap state evidence.

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
explicitly unreferenced by valid producer metadata. The first released
`tc.sdlc/bootstrap-reference/v2` contract separates committed consumer
references from identity-bound pending transactions. Bootstrap publishes a
pending transaction, acquires a kernel-held per-consumer recovery boundary,
then creates the commit lock by hard-linking a fully fsynced owner marker. The
recovery boundary is a deterministic localhost listener in the non-ephemeral
10000-29999 range; bootstrap and maintenance never scan an alternative port,
and an unrelated collision terminates safely as busy. The operating system
releases the listener on process death. The owner revalidates the exact state
inside that boundary, atomically commits v2, then releases only unchanged lock
and pending evidence. The lock binds PID and operating-system process-start
identity: a live or ambiguous owner is never displaced, while a proven-dead
owner is recovered with exact identity and byte checks. Maintenance moves an
identity-matched candidate into quarantine, refreshes both pending and
committed authorities, and restores the candidate when either matching
authority appeared during the move or before interrupted-quarantine recovery.
Dead pending transactions are
retained as authority for that run and expire only after their owner is proven
absent and the 48-hour window has elapsed. Proven-dead linked lock/marker pairs
and orphan pre-link markers follow the same 48-hour policy, with removals
recorded separately as reference metadata in the maintenance receipt. Device
and inode provide stable move authority; birthtime remains richer evidence but
cannot veto a proven same-file rename on filesystems where it changes with
ctime. A changed stable identity
never grants deletion authority.
Cleanup setup failures retain the candidate and terminate in a canonical failed
maintenance receipt. The release-image producer uses a named tc-sdlc BuildKit
builder and state-owned Docker configuration with explicit daemon routing;
release artefacts remain retained until catalogue/current/predecessor or incident
references provide deletion authority. Task 5 emits that retention declaration
but deliberately implements no successful-release artefact collector: until a
canonical reference inventory exists, successful artefacts are retained.

### Task 6 — Component acceptance and qualification composition

**Status:** in progress

Native bootstrap, preparation, evaluation and fitness acceptance plus native
consumer composition are complete through `769042d`. Image production, image
and hosted composition, release admission, generation and writeback remain
open.

**Files**

- each package component owns its public command, receipt schema, validation and
  direct packed-command acceptance;
- `packages/tc-sdlc/src/qualification/` owns the native consumer composer and
  its aggregate receipt only;
- `assurance/fixtures/sdlc/` contains Python-only, pnpm-only and mixed-language
  consumers used to exercise the public command.
- `assurance/run.py` independently verifies the released command and retained
  evidence; release code does not import or invoke the assurance harness.
- `.github/workflows/hosted-assurance.yml` provides runner allocation and hosted
  identity while executing the same CLI contract.

The canonical component interfaces, receipt ownership and dependency graph are
defined in
[`ai-sdlc-product-architecture.md`](../governance/standards/ai-sdlc-product-architecture.md#capability-and-composition-model).
Task 6 accepts `bootstrap`, `prepare`, `check`, `check-all` and `fitness`
directly before accepting their native consumer composition. Each component
test invokes its packed public command with genuine upstream evidence and stops
at the receipt owned by that component. Malformed receipt tests supply the bad
receipt directly to its consumer. They never use a detached process to alter an
artefact while the composer is running. The native, image and hosted journeys
run only after every component they compose has direct acceptance evidence.

The native consumer journey proves clean bootstrap, preparation fixed point,
affected closure, full graph execution, stable identity across worker counts and
aggregate terminal evidence. Component suites own boundary sabotage for their
declaration, lock, input, output, environment and receipt contracts. The journey
keeps only sequencing and handoff failures that can be triggered deterministically.

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
