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

**Status:** planned after Tranche 1 review

**Deliverables**

- `packages/tc-sdlc/` with the Nx preset, CLI, schema loader and graph executors;
- `images/sdlc/` with the canonical Dev Container/OCI image;
- `sdlc.yaml` schema and generated `tc-sdlc.lock`;
- `bootstrap`, `prepare`, `check` and `check-all` commands;
- release catalogue generation;
- Python-only, pnpm-only and mixed-language acceptance fixtures.

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
