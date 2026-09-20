# Task 3 implementation report

Date: 2026-09-21

## Outcome

Implemented the resource-aware `runGraph(graph, selection, options)` scheduler,
terminal process diagnostics and durable run evidence for Tranche 2 Task 3. The
implementation consumes the graph produced by the unchanged two-argument
`buildGraph` interface and preserves all Task 1 and Task 2 tests.

The built package now provides:

- canonical task resource declarations for CPU, memory, ports and exclusive
  resources;
- task-owned phase, no-progress and heartbeat budgets;
- CPU and memory admission against cgroup-aware host capacity plus port and
  exclusive-resource mutual exclusion;
- concurrent execution of independent ready tasks without declared-resource
  oversubscription;
- dependency ordering, failure propagation and queued-task cancellation;
- POSIX process-group termination with TERM/grace/KILL escalation and Windows
  descendant termination through `taskkill`;
- live start, heartbeat, bounded/redacted output, cancellation and terminal
  events;
- distinct `stalled`, `cancelled`, phase-budget failure and process failure
  outcomes;
- command-free process-group diagnostics containing PID, parent PID, state,
  elapsed time, CPU and resident memory observations;
- canonical, deterministic run receipts written through a synced temporary
  file and atomic replacement.

No workflow-wide timeout was introduced.

## Files

- `packages/tc-sdlc/src/runtime/index.ts`
- `packages/tc-sdlc/src/evidence/index.ts`
- `packages/tc-sdlc/src/schema/types.ts`
- `packages/tc-sdlc/src/schema/declaration.ts`
- `packages/tc-sdlc/src/preset/index.ts`
- `packages/tc-sdlc/src/graph/identity.ts`
- `packages/tc-sdlc/src/index.ts`
- `schemas/sdlc-v1.schema.json`
- `packages/tc-sdlc/test/runtime.test.ts`

The `tc.sdlc/v1` schema change is additive: existing targets remain valid and
receive canonical default resources and budgets. Explicit declarations are
closed and validated. Resources and budgets participate in task identity.

## Public contract

```ts
runGraph(
  graph: SdlcGraph,
  selection: readonly TaskIdentity[],
  options: RunOptions,
): Promise<RunReceipt>
```

`RunOptions.capacity` is the ordinary public deterministic injection boundary.
Without it, runtime capacity is resolved from host CPU/memory and cgroup v2 or
v1 limits where present. `resolveHostCapacity` accepts a public host snapshot so
capacity parsing can be verified without a test-only seam.

The package retains `buildGraph.length === 2`; the packed public package reports
`runGraph.length === 3`.

## TDD evidence

Every runtime test imports `../dist/index.js` and crosses the built public
package or real child-process boundary. Tests use real processes and files; no
mocks, monkeypatches, source-form assertions, suppressions, baselines,
grandfathering or test-only production seams were added.

Observed RED to GREEN sequence:

1. Resource and budget declaration was rejected by the schema
   (`SCHEMA_INVALID`); after the schema/type/preset slice, the graph carried the
   values and resource changes altered identity.
2. The public runtime call failed because `runGraph` was absent; after the first
   runtime/evidence slice, dependency execution and durable evidence passed.
3. Two rendezvous tasks failed under serial execution; admission-aware
   concurrent execution made both succeed.
4. Port and exclusive-resource sabotage overlapped two real claimants (2 failed,
   5 passed at RED); lock admission produced 7 passing admission cases at that
   stage.
5. An oversized CPU/memory task raised `RUN_GRAPH_INVALID`; it now produces a
   terminal `resource_capacity_exceeded` receipt without starting.
6. A failed dependency blocked execution but emitted no public terminal event;
   skipped dependants now emit and retain it while independent work completes.
7. With selection validation deliberately disabled, duplicate and unknown
   identities both executed/resolved; restored validation rejects both before
   execution.
8. A quiet interval emitted no heartbeat; the task-owned heartbeat loop now
   emits between progress outputs and before terminal state.
9. A no-progress process incorrectly succeeded; it now captures diagnostics,
   terminates its whole process group and records `stalled`.
10. A progressing process exceeded its phase budget but succeeded; it now
    records `phase_budget_exceeded` as failed, distinct from stall.
11. AbortSignal cancellation initially let a descendant survive/succeed; the
    process-group lifecycle now records `cancelled` and cleans descendants.
12. Large secret-bearing stdout/stderr was initially unbounded
    (`outputTruncated === false`); output is now byte-bounded and chunk-safe
    redacted in both live events and durable evidence.
13. When receipt ordering was deliberately changed to completion order, three
    ordering/determinism tests failed; canonical graph ordering restored
    identical serialisation across capacity 1 and capacity 2.
14. Receipt replacement failure left its temporary file; failure cleanup now
    removes it, and circular/unserialisable evidence creates no output.
15. Three cgroup capacity cases failed because the public resolver was absent;
    cgroup v2, cgroup v1 and unlimited host fallback then passed (22 tests at
    that stage).
16. With budget coherence validation deliberately disabled, an invalid
    `noProgressMs > phaseMs` declaration was accepted; restored graph validation
    rejects it with `GRAPH_BUDGET_INVALID` (23 tests).
17. The corrected queued-abort sabotage observed a `start` event for a task that
    was waiting behind the running allocation; the scheduler now cancels it
    terminally without spawning it (24 tests).
18. Stall evidence lacked an observed process-group resource sample; the final
    receipt test failed until bounded command-free `ps` data was captured before
    termination. The complete focused suite remained 24/24 GREEN.

## Acceptance coverage

| Requirement | Built-public behavioural evidence |
|---|---|
| CPU and memory admission | real exclusive-file claimant under constrained CPU and memory; oversized task never starts |
| Port and exclusive contention | two claimants with the same declared port or exclusive resource cannot overlap |
| Concurrent independent work | real rendezvous succeeds only if both ready tasks run concurrently |
| Dependency ordering/failure | dependent observes predecessor artefact; failed predecessor skips dependant while independent task succeeds |
| Operator cancellation | AbortSignal cancels the process group, removes descendants and prevents queued task start |
| No-progress stall | task records `stalled`, observed process/resource diagnostics and no surviving grandchild |
| Phase budget | progressing task records failed `phase_budget_exceeded`, not stalled |
| Event ordering | start, output, heartbeat, output and terminal are observed at the public callback |
| Bounded secret-safe evidence | stdout/stderr and event payloads are bounded; explicit secret is absent from receipt and callback data |
| Deterministic receipt | canonical serialisation is byte-identical at scheduler capacities 1 and 2 |
| Durable evidence failures | atomic replacement failure rejects and cleans the temporary; circular data rejects without a file |
| Selection validation | duplicate and unknown task identities reject before execution |
| Host capacity | public resolver proves cgroup v2, cgroup v1 and unlimited fallback behaviour |

## Verification

Focused built-public runtime verification:

```text
pnpm --filter @three-cubes/tc-sdlc build
pnpm --filter @three-cubes/tc-sdlc exec vitest run test/runtime.test.ts
```

Exit 0: 1 file, 24 tests passed.

Package build and complete package suite:

```text
pnpm build
pnpm test
```

Exit 0: 3 files, 80 tests passed, including the 10 Task 1 CLI tests and all
Task 2 graph tests.

Frozen dependency and lock verification:

```text
corepack pnpm install --frozen-lockfile
git diff --exit-code -- pnpm-lock.yaml
```

Exit 0: workspace already up to date; root lock unchanged.

Repository Python suite:

```text
uv run --no-sync pytest -q
```

Exit 0: 1,974 passed in 107.19 seconds.

Full fitness gate:

```text
uv run --no-sync tc-fitness run
```

Exit 0: 1,974 tests passed in 106.27 seconds, followed by PASS for
`contract-tests`, `actionlint`, `yamllint`, `license` and `branch-naming`; the
self gate reported 5 ran, 0 skipped.

Packed-consumer verification:

```text
corepack pnpm --filter @three-cubes/tc-sdlc pack --pack-destination <temp>
corepack pnpm --dir <empty-consumer> add <tarball>
node --input-type=module <public export/arity probe>
```

Exit 0. A clean consumer imported `buildGraph`, `runGraph`,
`resolveHostCapacity`, `serialiseRunReceipt` and `writeRunReceipt`; the probe
reported `buildGraph/2` and `runGraph/3`. The tarball contains runtime/evidence
JavaScript and declaration files.

Diff and package-lock audit:

```text
git diff --check
git diff --cached --check
find packages -name pnpm-lock.yaml -print
```

Both diff checks exited 0 without output and no package-local lockfile exists.

## Self-review

- All Task 3 behaviours are covered through exported package functions and real
  process boundaries.
- Receipts contain no wall-clock timestamps, completion-order collections or
  command lines; task and process samples use deterministic ordering.
- Output evidence is bounded before event retention and redacted across chunk
  boundaries.
- Stall diagnostics are captured before group termination; phase expiry and
  operator cancellation remain distinct terminal states.
- No controller-owned implementation plan or progress file was edited.
- No Task 1 or Task 2 public behaviour was removed or narrowed.

No implementation blocker or known acceptance gap remains.
