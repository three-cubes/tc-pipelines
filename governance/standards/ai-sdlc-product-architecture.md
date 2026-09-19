---
type: standard
context: three-cubes
status: active
owner: platform
tags: [sdlc, developer-environment, ci, fitness, release, deployment]
---

# AI SDLC Product Architecture

This standard defines the shared environment and execution product delivered by
`tc-pipelines`. It is the canonical architecture for local development, cloud
sandboxes, CI, release qualification and production deployment across Three
Cubes repositories.

## Outcome

A repository declares its product graph and product-specific behaviour once.
The released `tc-pipelines` product supplies the tools and orchestration that
execute that declaration on macOS, Linux, supported cloud sandboxes and GitHub
Actions.

The product provides:

- one versioned development and CI environment;
- one dependency-aware task graph;
- one preparation phase for deterministic mechanical changes;
- one fitness engine integrated into that graph;
- one evidence contract from local verification through production;
- one immutable build, qualification, deployment and rollback path;
- one coordinated upgrade that updates every SDLC component together.

## Product boundary

| Home | Owns |
|---|---|
| `tc-pipelines` | SDLC package, canonical development image, task orchestration, reusable workflows, release/deployment protocols, evidence schemas, governance templates and adoption tooling. |
| `tc-fitness` | Executable fitness engine, shared check catalogue, evaluation semantics and structured findings. |
| Consumer repository | Product source, product tests, product graph declaration, generated artefacts, build inputs, runtime configuration, qualification journeys and deployment values. |
| Runtime target | Secrets, persistent state, target observations, deployment receipts and operational evidence. |

`tc-pipelines` invokes `tc-fitness` as a first-class task in the SDLC graph.
The pipeline owns when and where the fitness evaluation runs. `tc-fitness` owns
how declared checks execute and report findings. A coordinated SDLC release
records the compatible `tc-fitness` version.

The local published-surface inventory and disposable consumer lab live in
`assurance/` and run through `make assurance`. Their evidence levels and
admission boundaries follow the
[CORE assurance contract](core-assurance-contract.md); local consumer execution
does not establish hosted adapter or release-admission proof.

## Released surfaces

One `tc-pipelines` release publishes a coordinated set of surfaces:

| Surface | Contract |
|---|---|
| `@three-cubes/tc-sdlc` | Nx preset, executors, generators, schema validation and the `tc-sdlc` command. |
| `ghcr.io/three-cubes/tc-sdlc` | Canonical Linux development and CI image with the reviewed toolchain. |
| GitHub reusable workflows | Thin hosted entrypoints that execute the released SDLC package in the canonical image. |
| Governance library | Standards, rulesets, repository skeletons and adoption tooling. |
| Release catalogue | Package version, workflow commit, image digest, schema version and compatible `tc-fitness` version. |

GitHub workflow syntax requires literal commit references. The SDLC upgrade
command reads the release catalogue and materialises those references together
with the package version and image digest. Consumers review one coordinated
upgrade rather than maintaining independent pins.

## Consumer contract

Each consumer carries a small `sdlc.yaml` declaration and a generated
`tc-sdlc.lock`. The declaration names product tasks and product-specific
commands. The lock binds the complete released SDLC toolchain.

```yaml
schema: tc.sdlc/v1
project: example-product

toolchains:
  python: "3.13"
  node: "24"
  packageManager: "pnpm@11.22.0"

fitness:
  config: pyproject.toml
  profiles:
    smoke: smoke
    full: full
    soak: nightly

targets:
  prepare:
    executor: tc-sdlc:prepare
  check:
    executor: tc-sdlc:affected-check
    dependsOn: [prepare]
  qualify:
    executor: tc-sdlc:container-qualify
    dependsOn: [check]
  deploy:
    executor: tc-sdlc:deploy
    dependsOn: [qualify]
```

The Makefile remains the stable human and agent interface:

| Command | Result |
|---|---|
| `make bootstrap` | Materialise the released environment and dependencies. |
| `make prepare` | Apply deterministic generators, formatting, lock and manifest repairs. |
| `make check` | Run the affected local graph, including the configured `tc-fitness` profile. |
| `make check-all` | Run the complete verification graph. |
| `make qualify` | Build and exercise the release candidate locally. |
| `make deploy` | Submit a qualified immutable candidate to the protected deployment path. |

Repositories may add product-specific targets. The shared commands retain the
same meaning across the fleet.

## Environment model

The canonical Linux image is the authoritative environment for CI and release
evidence. It pins Python, uv, Node, pnpm, Go, Bash and the reviewed infrastructure
clients. A Dev Container definition starts that image for local and compatible
cloud development.

Native macOS and Linux bootstrap uses the same release catalogue and lock for a
low-latency inner loop. Native execution proves product behaviour within the
declared platform scope. The canonical image supplies cross-environment release
evidence.

Platform-specific tests form explicit tasks. A macOS bootstrap task verifies
the native developer boundary. Linux container tasks verify the production
user-space boundary. Live service journeys verify external runtime boundaries.

## Task and preparation model

The Nx project and task graph represents dependencies between Python packages,
pnpm workspaces, Go modules, generated artefacts, container builds, fitness
profiles and qualification journeys.

Every task declares:

- inputs that affect its result;
- outputs it produces;
- dependencies that must complete first;
- resource constraints and safe concurrency;
- cache eligibility;
- the evidence emitted on success or failure.

`prepare` contains deterministic mutating work such as formatting, generator
refresh, lock synchronisation and manifest generation. Evaluation tasks operate
on the prepared tree and leave it unchanged. CI runs preparation first and
reports a patch when committed content was stale. Local preparation applies the
same changes directly.

Content-addressed caching applies to pure tasks whose outputs are fully declared.
Secrets, live observations, deployment decisions and production evidence always
execute against their real boundary.

## Fitness integration

`tc-fitness` is a required graph task, not a separate CI convention. The
consumer's SDLC declaration selects named fitness profiles. The SDLC release
catalogue supplies a compatible engine version, and `tc-sdlc upgrade` updates
the engine pin with the rest of the environment.

The normal profiles are:

| Profile | Purpose | Budget |
|---|---|---:|
| `smoke` | Changed-surface feedback during editing and PR preparation. | under 60 seconds warm |
| `full` | Complete repository verification for release admission. | repository-defined and measured |
| `nightly` | Soak, mutation and broad live or compatibility evaluation. | scheduled, retained and actionable |

Profile membership and findings remain owned by `tc-fitness`. Graph scheduling,
environment selection and evidence handoff remain owned by `tc-pipelines`.

## CI and release flow

```text
local prepare/check
        |
        v
PR affected graph -----> exact integration graph
                              |
                              v
                    immutable candidate digest
                              |
                              v
                       local/CI qualification
                              |
                              v
                    protected production deploy
                              |
                              v
                    PVT, promote or rollback
```

PR validation runs affected tasks. Exact integration validation runs the graph
required for release admission. A successful candidate build publishes one
immutable image digest and provenance record. Qualification and deployment
consume that digest.

GitHub Actions hosts the graph; workflow YAML does not reproduce it. Workflow
jobs provide credentials, protected environments and hosted runner allocation.
The task definitions remain executable locally.

## Deployment boundary

`tc-pipelines` owns the generic transaction:

1. acquire the deployment lock;
2. verify candidate identity and evidence;
3. capture the product-defined persistent-state recovery point;
4. converge host prerequisites;
5. pull and start the qualified digest;
6. execute health and product verification journeys;
7. promote the candidate or restore the predecessor;
8. retain a complete receipt;
9. remove expired deployment artefacts.

Ansible defines repeatable host state. Docker Compose defines a single-host
container application. Consumer adapters define product state, knowledge
harvesting, runtime configuration and PVT journeys. The transport may use the
Cloudflare SSH boundary or an approved cloud control-plane path; both consume
the same typed deployment request and return the same receipt.

## Evidence contract

Every stage records:

- repository and commit identity;
- SDLC release and lock digest;
- task and input hash;
- toolchain and dependency lock identities;
- candidate image digest;
- completed checks and terminal status;
- retained diagnostic and receipt locations;
- production runtime identity;
- PVT, rollback and cleanup result.

Cache hits retain the original task identity and input hash. A cache record
accelerates execution; production qualification is established by the retained
candidate and runtime receipts.

## Adoption and compatibility

The migration preserves current reusable workflows while the released package,
image and graph are introduced. Each consumer moves through these states:

1. **Declared** — add `sdlc.yaml` and generate the coordinated lock.
2. **Local** — run preparation and affected checks through `tc-sdlc`.
3. **CI** — reusable workflows execute the same graph in the canonical image.
4. **Qualification** — build and exercise one immutable candidate locally and in CI.
5. **Deployment** — production consumes the qualified digest and receipt.
6. **Converged** — remove superseded consumer scripts, copied workflows and independent pins.

Compatibility shims have an owner, consumer list and removal condition in the
implementation roadmap. A released consumer contract remains supported until
its declared migration window closes.

## Acceptance criteria

The product reaches the target state when:

- a clean supported environment bootstraps with one command;
- local and CI resolve the same task definitions and SDLC lock;
- the warm affected loop completes within 60 seconds;
- preparation completes deterministic maintenance before evaluation;
- independent tasks consume available cores within declared resource limits;
- `tc-fitness` runs as a version-compatible graph task;
- a release candidate is built once and promoted by digest;
- local qualification, CI qualification and deployment consume that digest;
- VM configuration converges idempotently;
- rollback and cleanup are exercised and evidenced;
- a consumer upgrade changes one coordinated SDLC release;
- consumer repositories contain product behaviour and thin SDLC declarations.

## External design basis

The architecture uses established tool boundaries:

- [Development Containers](https://containers.dev/overview) define a reusable
  development environment for local and hosted execution.
- [Nx multi-language projects](https://nx.dev/docs/features/multi-language-support),
  [task execution](https://nx.dev/docs/features/run-tasks) and
  [affected selection](https://nx.dev/docs/features/ci-features/affected) provide
  the cross-language project graph, scheduling and incremental execution.
- [uv project environments](https://docs.astral.sh/uv/guides/projects/) provide
  Python version, dependency lock and environment materialisation.
- [pytest-xdist distribution](https://pytest-xdist.readthedocs.io/en/stable/distribution.html)
  provides intra-project Python test scheduling.
- [Ansible playbooks](https://docs.ansible.com/projects/ansible/latest/playbook_guide/playbooks_intro.html)
  provide declarative, idempotent host convergence.
- [Docker Compose production operation](https://docs.docker.com/compose/how-tos/production/)
  and [health ordering](https://docs.docker.com/compose/how-tos/startup-order/)
  provide the single-host application lifecycle.
- [GitHub artifact attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)
  bind build provenance to immutable artefact digests where the repository plan
  supports them.

These tools provide the environment, graph, language execution, host convergence
and artefact primitives. `tc-pipelines` packages them into the Three Cubes SDLC
contract; it does not reimplement their engines.
