# SDLC Cost and Resource Control

This document defines how the shared AI SDLC product limits developer time,
GitHub Actions consumption, build work, storage and VM waste. The architecture
is
[`governance/standards/ai-sdlc-product-architecture.md`](../governance/standards/ai-sdlc-product-architecture.md).

## Cost model

Track cost per completed change and per qualified release. Raw runner minutes or
VM size alone do not describe value when work is duplicated or repeatedly fails
at a late boundary.

Record:

- local cold bootstrap and warm affected-check duration;
- hosted task duration and runner class;
- task cache hit and miss counts;
- tasks repeated before and after merge;
- container builds per candidate digest;
- release qualification and deployment duration;
- failed deployment stage and failure classification;
- retained image, build-cache, snapshot and evidence storage;
- cleanup result and expired bytes removed.

## Execution controls

### Run affected work during development

The local and PR paths execute the affected task graph. Dependency edges add
downstream consumers whose behaviour can change. The complete graph runs for
release admission and scheduled broad evaluation.

This produces a warm local target under 60 seconds while retaining complete
release evidence.

### Execute each outcome once

PR validation proves the affected feature tree. Exact-integration validation
proves the admitted merge. Release work builds the immutable artefact and
records its digest. Production deployment consumes that digest.

Post-merge work has a distinct output such as a release receipt, published
artefact or deployment. Equivalent test work reuses trusted exact-integration
evidence rather than rerunning the same task graph.

### Use all declared resources

The task graph schedules independent projects concurrently. Language runners
schedule work inside a project. Each task declares CPU, memory, ports and shared
resources so concurrency increases throughput without introducing order-dependent
tests.

Measure CPU and memory utilisation during representative full runs. Adjust task
boundaries and resource declarations before increasing runner or VM size.

### Cache pure tasks

Cache a task when its complete inputs and outputs are declared and it has no
secret, live-state or time-dependent result. Package-manager caches accelerate
dependency materialisation. Task caches accelerate deterministic compilation,
linting, tests and generated outputs.

Production observations, deployment decisions, secrets and PVT results always
execute at the live boundary. Cache identity forms part of task evidence; cache
contents do not replace release or production receipts.

## GitHub Actions controls

- one thin workflow hosts the task graph for a change;
- concurrency cancels superseded commits on the same branch;
- independent hosted jobs execute concurrently within the repository budget;
- PR jobs run affected work;
- exact integration runs release-admission work;
- scheduled soak runs broad tasks omitted from the inner loop;
- production jobs consume published artefacts;
- logs remain bounded and full diagnostics are retained as named artefacts;
- every scheduled workflow has an owner, purpose, frequency and recent-success
  measure.

Review workflow usage monthly by repository, workflow, job and conclusion.
Investigate repeated cancellations, repeated failures at the same stage and jobs
whose output duplicates another retained result.

## Container controls

- build one image per release candidate;
- address candidates and predecessors by immutable digest;
- use layer and build caches with declared inputs;
- qualify before production;
- retain the active and immediate predecessor images;
- remove failed and unreferenced images after the evidence window;
- remove builder cache older than 48 hours when no active build references it;
- report reclaimed bytes in the cleanup receipt.

Application source is compiled in the build environment. The VM pulls and runs
the qualified image.

## VM and disk controls

The deployment transaction records disk use before and after apply. Lifecycle
policy retains:

- active runtime state;
- current and predecessor application images;
- the configured rollback window;
- retained release and incident evidence;
- persistent product data declared by the consumer.

Lifecycle policy expires:

- unreferenced container images;
- build cache;
- incomplete deployment staging directories;
- expired snapshots and protected-path archives;
- downloaded release bundles;
- temporary diagnostics already copied to retained evidence storage.

The default operational cleanup window is 48 hours. Product or incident policy
may retain named evidence longer. Cleanup is a deployment outcome with a receipt,
not an operator memory task.

## Snapshot and rollback cost

Container-only releases use the predecessor digest plus a protected-state
receipt when that combination provides complete recovery. Host or infrastructure
changes use a recovery point appropriate to the changed state. Snapshot expiry
is recorded when the snapshot is created and enforced by lifecycle cleanup.

Recovery policy is selected by the deployment contract and verified before
mutation. The policy reflects the state at risk rather than applying a VM disk
snapshot to every container change.

## Runner placement

GitHub-hosted runners provide isolated general-purpose execution. Existing
trusted hosts provide value when a task requires private network access, large
warm caches or specialised hardware. A self-hosted runner carries patching,
isolation, availability and secret-boundary obligations.

Choose runner placement from measured task cost and required connectivity. The
canonical image keeps the user-space environment consistent across placements.

## Cost acceptance criteria

- a PR executes the affected graph once;
- an admitted merge repeats only work with a distinct integration or release
  outcome;
- a candidate image is built once;
- production performs no application build;
- superseded branch runs cancel automatically;
- warm affected feedback meets the 60-second target;
- runner CPU is used by independent eligible tasks;
- scheduled workflows have recent successful evidence or are removed;
- cleanup runs after deployment and reports reclaimed storage;
- active and predecessor recovery artefacts remain available;
- monthly reporting attributes hosted and Azure consumption to repository and
  purpose.
