# Task 4 implementation report

Date: 2026-09-21

## Outcome

Implemented Tranche 2 Task 4 preparation, evaluation and evidence reuse on the
approved Task 3 scheduler. `prepare`, `check` and `check-all` are public library
and CLI surfaces. They plan through the existing lock/graph APIs and execute
only through `runGraph`; no second scheduler was introduced.

The implementation adds:

- required target `mode` (`prepare` or `evaluate`) and `trustBoundary`
  (`portable`, `hosted`, `live` or `deployment`) semantics;
- mode and trust-boundary binding in canonical task identity;
- one canonical filesystem inventory for graph inputs, receipts and cache
  admission, including content digest, permission mode and symlink identity;
- two-pass preparation with declared-output enforcement and true fixed-point
  proof;
- affected and complete evaluate modes with full source immutability checks;
- separate versioned scheduler, preparation and evaluation receipts;
- explicit preparation-phase proof before evaluate tasks may treat prepare
  prerequisites as satisfied;
- content-addressed output caching for succeeded portable evaluate tasks only;
- Ed25519 signing and allowlisted external producer-policy admission;
- public `prepare`, `check` and `check-all` CLI commands.

## Public contracts

New public functions include:

```ts
resolveInputInventory(root, declaration): TaskInputDigests
prepare(options): Promise<PreparationReceipt>
check(options): Promise<EvaluationReceipt>
checkAll(options): Promise<EvaluationReceipt>
signEvaluationReceipt(receipt, signer): SignedEvaluationReceipt
admitEvaluationReceipt(signed, candidate, policy): true
storeEvaluationCache(root, cacheRoot, receipt): { key: string }
restoreEvaluationCache(root, cacheRoot, key, candidate): true
```

Task 3 `RunReceipt` remains unchanged and terminal scheduler evidence is nested
inside, not conflated with, `PreparationReceipt` and `EvaluationReceipt`.
`buildGraph` remains the exact two-argument interface and `runGraph` remains the
exact three-argument interface.

## Design decisions

### Explicit task semantics

Every `tc.sdlc/v1` target now requires `mode` and `trustBoundary`. This package
is unreleased, so every fixture was migrated and no compatibility default was
added. Both values are copied to `GraphTask` and included in task identity.
Prepare tasks may not depend on evaluate tasks.

### Canonical input inventory

`resolveInputInventory` validates and normalises the declaration, walks the
repository deterministically, excludes `.git`, and records sorted repository-
relative records containing SHA-256 content, permission mode and symlink target.
Broken, non-file and escaping symlinks fail closed. The same records are passed
to `bindGraphLock`, retained in evaluation evidence and used for cache identity.

### Preparation and phase proof

Preparation runs only prepare-mode tasks. It snapshots the complete tree,
executes once, rejects mutations outside declared output selectors, executes
again, and succeeds only if the second pass makes no content, add, delete, mode
or symlink change. Both scheduler receipts and bounded mutation evidence are
written canonically and atomically even for stale lock, task failure,
undeclared mutation and non-fixed-point outcomes.

The evaluate graph omits prepare-mode tasks only after validating a succeeded
`PreparationReceipt` bound to the exact final tree, declaration, catalogue and
lock and proving an empty second pass. Missing, failed, non-fixed or stale-tree
preparation evidence rejects before any evaluation event. This is why the
phase-filtered graph does not recreate Task 3's omitted-dependency defect: the
excluded prerequisite has explicit, exact fixed-point evidence, while all
evaluate-to-evaluate dependencies remain in the graph and are enforced by
`runGraph`.

### Evaluation and source identity

Evaluation requires a real Git commit and an empty porcelain status including
untracked files. It binds commit, tree digest, declaration, catalogue, lock,
environment class, producer, task identity, canonical input inventory, trust
boundary and output inventory. `check` uses dependency-closed
`selectAffected`; `checkAll` passes every evaluate task exactly once to the same
scheduler. Any tracked, untracked, mode, symlink or content mutation records a
failed evaluation receipt.

### Signed admission and cache policy

Evaluation signatures use Node's Ed25519 implementation and caller-provided key
capability. There is no package-owned key path. CI admission requires a valid
signature, current validity interval, exact candidate match and producer/key
allowlist supplied separately from declaration and lock. Unsigned, unknown,
bad-signature, future, expired, stale-candidate, failed, cancelled, stalled,
hosted, live and deployment evidence cannot satisfy admission.

Unsigned local succeeded evidence may warm the cache, but only for evaluate-
mode portable tasks with declared regular-file outputs. Cache store revalidates
current output bytes and metadata. Restore revalidates canonical candidate,
manifest, content and metadata and rejects traversal, symlink output and
corruption before writeback.

## TDD evidence

All new tests import the built `dist/index.js` package or execute the built CLI
and use real files, Git repositories, child processes and generated Ed25519
keys. No mock, monkeypatch, test-only seam, source-form assertion, baseline,
suppression or threshold reduction was added.

Initial task semantics RED:

```text
pnpm --filter @three-cubes/tc-sdlc build
pnpm --filter @three-cubes/tc-sdlc exec vitest run \
  test/graph.test.ts -t 'requires task mode'
```

Exit 1: the schema rejected both new properties as unknown. GREEN required both
properties, rejected omission and proved a trust-boundary change alters task
identity. The complete package then passed 84 tests at that slice.

Initial Task 4 public boundary RED:

```text
pnpm --filter @three-cubes/tc-sdlc exec vitest run test/task4.test.ts
```

Exit 1: 6/6 tests failed because `resolveInputInventory`, `prepare`, `check` and
`checkAll` were absent. Incremental GREEN reached 6/6, then expanded through
the sabotage matrix to the final 16/16.

The final built-public suite covers:

- content, mode and symlink inventory plus symlink escape rejection;
- fixed-point preparation and durable execution/undeclared/non-fixed failure;
- undeclared add, delete, mode and symlink mutation;
- stale lock failure evidence;
- affected evaluation, check-all exactly once and phase isolation;
- missing, failed, non-fixed and stale-tree preparation proof;
- evaluation mutation and bounded mutation evidence;
- dirty tracked/untracked source rejection;
- one-byte source, declaration, catalogue, lock, task, input, shared-input,
  environment and output mismatch;
- unknown producer, unsigned evidence, bad signature, expiry, failed,
  cancelled and stalled scheduler evidence;
- hosted-boundary admission/cache rejection;
- corrupted source output and corrupted cached output;
- cache path/key controls;
- location and discovery-order stable inventory/task identity;
- built CLI `prepare`, `check` and `check-all` flows.

## Verification

Focused Task 4:

```text
pnpm --filter @three-cubes/tc-sdlc build
pnpm --filter @three-cubes/tc-sdlc exec vitest run test/task4.test.ts
```

Exit 0: 1 file and 16 tests passed.

Complete package:

```text
pnpm build
pnpm test
```

Exit 0: 4 files and 100 tests passed, preserving every Task 1–3 test.

A loaded rerun exposed two Task 3 tests that assumed the first heartbeat could
not precede child output. Focused reproduction passed twice when unloaded,
confirming scheduling sensitivity. Assertions were corrected to retain the
required start/output/terminal order and require at least one heartbeat between
the two deliberate progress outputs without forbidding an earlier heartbeat.
The focused pair and complete 100-test suite then passed.

Frozen dependency and lock verification:

```text
corepack pnpm install --frozen-lockfile
git diff --exit-code -- pnpm-lock.yaml
```

Exit 0: workspace already current; root lock unchanged.

Repository Python suite, final integrated state:

```text
uv run --no-sync pytest -q
```

Exit 0: 1,974 passed in 145.87 seconds.

Full fitness gate, final integrated state:

```text
uv run --no-sync tc-fitness run
```

Exit 0: 1,974 passed in 379.43 seconds, followed by PASS for contract tests,
actionlint, yamllint, licence and branch naming; 5 ran and 0 skipped.

Packed-consumer verification:

```text
corepack pnpm --filter @three-cubes/tc-sdlc pack --pack-destination <temp>
corepack pnpm --dir <empty-consumer> add <tarball>
node --input-type=module <public export and arity probe>
```

Exit 0. The clean consumer imported graph/runtime, canonical input, task,
signing and cache APIs and reported `buildGraph/2` and `runGraph/3`. The tarball
contains JavaScript and declarations for `tasks`, `inputs`, `cache` and Task 4
evidence/signing.

Diff and packaging audit:

```text
git diff --check
git diff --cached --check
find packages -name pnpm-lock.yaml -print
```

Both diff checks exit 0 without output and no package-local lock exists.

## Self-review

- Preparation and evaluation both delegate process execution to Task 3
  `runGraph`; no alternate scheduler or workflow timeout exists.
- Preparation evidence is required before cross-phase dependency removal and is
  bound to exact final state.
- Mutation evidence is bounded by `maxMutations` with total count and truncation
  flags while validation still examines the complete mutation set.
- Candidate and signature policy are outside candidate-controlled declaration
  and lock.
- Cache admission is narrower than evaluation: only successful portable
  evaluate tasks with declared verified outputs qualify.
- Controller-owned `docs/IMPLEMENTATION.md` and progress files are unchanged.

No known Task 4 acceptance gap or implementation blocker remains.
