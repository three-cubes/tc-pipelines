# Task 5 implementation report

Date: 2026-09-21

## Outcome

Implemented the native-bootstrap and immutable-catalogue-generation first slice
of Tranche 2 Task 5 on the independently approved Task 4 foundation at
`6bff6ae`.

The slice adds:

- a public `bootstrap(options)` library API and `tc-sdlc bootstrap` CLI command;
- explicit caller-owned state roots, with no implicit `HOME` state;
- normal public host capability input for deterministic platform, architecture,
  `PATH` and offline behaviour;
- macOS and Linux capability discovery for catalogue-declared Node, pnpm,
  Python and uv versions;
- owned, verified executable copies and launchers that continue to work after
  the discovery `PATH` and original host executables disappear;
- canonical graph planning from a recomputed lock-bound filesystem inventory;
- bounded canonical atomic bootstrap receipts;
- canonical atomic release-catalogue generation from immutable workflow commit
  and OCI digest inputs; and
- coordinated `three-cubes-fitness` 0.17.0 authority at immutable commit
  `73d7ffc4b563849edcd607b377fbb3ee4ba6da32`.

No final `release/catalogue.json`, release number, image digest or published
artefact was invented. The existing package metadata version remains a build
input only; the generator requires an explicit release candidate version and
the behavioural fixtures use `3.0.0` rather than silently reusing `2.2.0`.
Canonical OCI/Dev Container construction and publication remain outside this
first slice.

## Public contracts

```ts
bootstrap(options: BootstrapOptions): Promise<BootstrapReceipt>
serialiseBootstrapReceipt(receipt: BootstrapReceipt): string
generateReleaseCatalogue(input: ReleaseCatalogueGeneration): ReleaseCatalogue
writeReleaseCatalogue(path: string, catalogue: ReleaseCatalogue): void
```

`BootstrapOptions.stateRoot` is required and must be an absolute path outside
the checkout. `BootstrapOptions.host` is the ordinary injectable environment
adapter; production defaults use `process.platform`, `process.arch` and
`process.env.PATH`. No test-only seam or hidden home-directory default exists.

`CANONICAL_SDLC_TOOLCHAINS` exports Node `24`, pnpm `11.22.0`, Python `3.13`
and uv `0.12.5`. `CANONICAL_SDLC_FITNESS` exports the coordinated
`three-cubes-fitness` version `0.17.0`.

## Design decisions

### State ownership and integrity

The caller selects a dedicated state root. Bootstrap rejects relative roots,
roots inside the checkout, root or nested state symlinks, non-directory roots,
foreign non-empty roots and mismatched ownership markers. It does not read or
derive state from `HOME`.

Each lock/platform/architecture state is materialised into a unique staging
directory and atomically renamed into its final immutable key. Existing partial
state is rejected without repair. Warm-state validation recomputes canonical
manifest, executable, launcher and adapter digests and rejects corruption.

Discovered host executables are copied into the owned release state, reprobed
there and executed only through launchers that bind the owned tool directory.
Warm offline bootstrap therefore does not trust a second read from the original
host path and remains usable when that path is empty or the original tools have
been deleted.

### Planning and evidence

Every bootstrap invocation calls `assertCurrentLock`, resolves the canonical
content inventory, calls `bindGraphLock` and then the exact two-argument
`buildGraph`. Task identities therefore bind the same canonical content inputs
as preparation and evaluation. Checkout location, platform and architecture do
not enter task identity; one-byte input changes do.

Receipts contain release, lock digest, platform, architecture, state key,
adapter digests, task identities and bounded diagnostics. They contain neither
absolute state paths nor discovery paths and are written through the existing
fsync-and-rename canonical evidence writer.

### Catalogue generation

`generateReleaseCatalogue` takes an explicit semantic release version, exact
40-character workflow commit and exact `sha256:` OCI digest. Schema validation
rejects branch names, tags used as workflow refs, mutable image tags,
placeholders and incomplete entries. Package, schema, fitness and toolchain
authorities are emitted together, then `writeReleaseCatalogue` validates again
before an atomic canonical write.

This generator is available through `tc-sdlc catalogue`; the implementation and
tests write only temporary catalogues and do not fabricate the repository's
final release catalogue.

## TDD evidence

All tests import the built `dist/index.js` package or execute the built CLI and
use real executable files, process boundaries and filesystem state. No mock,
monkeypatch, source-form assertion, test-only seam, baseline, suppression or
threshold reduction was introduced.

Initial bootstrap RED:

```text
pnpm --filter @three-cubes/tc-sdlc build
pnpm --filter @three-cubes/tc-sdlc exec vitest run test/bootstrap.test.ts
```

Exit 1: 0/5 passed. The public `bootstrap` export did not exist and the built
CLI rejected `bootstrap` as an unknown command.

Incremental bootstrap GREEN reached 5/5. Additional sabotage then produced a
focused 3/5 RED: warm state failed after original host tools were removed and a
nested `releases` symlink was followed. Managed executable copies and
component-wise symlink rejection returned the suite to 5/5.

Catalogue-generation RED:

```text
pnpm --filter @three-cubes/tc-sdlc exec vitest run \
  test/catalogue-generation.test.ts
```

Exit 1: generation and CLI boundaries were absent. GREEN: 5/5, including
moving workflow ref, moving image tag and unresolved-ref rejection before any
output write.

The built-public sabotage suite covers:

- trap `HOME` with a real file;
- missing and wrong `PATH` capabilities;
- warm offline and cold offline behaviour;
- removal of all originally discovered host executables;
- exact version mismatch;
- foreign, symlinked, nested-symlinked and in-checkout state;
- corrupted launcher and missing state manifest without automatic repair;
- stale lock rejection;
- bounded diagnostic count and truncation evidence;
- deterministic task identity across checkout, host platform and architecture;
- task-identity change on content change;
- canonical receipt bytes and runnable managed launchers; and
- unresolved or moving release catalogue inputs.

## Verification

Focused and complete package:

```text
pnpm --filter @three-cubes/tc-sdlc build
pnpm --filter @three-cubes/tc-sdlc test
```

Exit 0: 6 files and 112 tests passed, preserving every Task 1–4 contract.

Frozen locks:

```text
corepack pnpm install --frozen-lockfile
git diff --exit-code -- pnpm-lock.yaml uv.lock
```

Exit 0. The workspace was already current and both locks remained unchanged.

Python suite:

```text
uv sync --frozen
uv run --no-sync pytest -q
```

The isolated worktree initially had no environment, so the first no-sync
attempt terminated before collection because `pytest` was absent. After exact
frozen hydration, the first full run exposed the stale direct-CI fitness-ref
assertion: 1 failed and 1,973 passed. The focused parity regression then passed
6/6 after requiring the approved immutable commit in both `pyproject.toml` and
CI. Final result: exit 0, 1,974 passed in 81.25 seconds.

Full repository fitness gate:

```text
uv run --no-sync tc-fitness run
```

Exit 0: 1,974 tests passed in 109.88 seconds, followed by PASS for actionlint,
yamllint, licence and branch naming; 5 ran and 0 skipped.

Packed clean consumer:

```text
corepack pnpm --filter @three-cubes/tc-sdlc pack --pack-destination <temp>
corepack pnpm --dir <empty-consumer> add <tarball>
node --input-type=module <public export probe>
```

Exit 0. The tarball contains bootstrap declarations and JavaScript. A clean
consumer imported all bootstrap/catalogue exports, generated a 0.17.0-bound
catalogue, and confirmed `bootstrap/1`, preserved `buildGraph/2` and preserved
`runGraph/3`.

Diff and packaging audit:

```text
git diff --check 6bff6ae..HEAD
find packages -name pnpm-lock.yaml -print
```

Exit 0 without diff errors and no package-local lock exists.

## Commits

- `dcf31b3c79b45341e17288d510e2ba3511a6b522` — coordinate Python 3.13 and
  immutable fitness 0.17.0 authorities;
- `04cea980a443aec27f42e062d92502277b373aa2` — public native bootstrap and CLI;
- `deedb62e0eb79642745ddfea95898949ae0c5879` — immutable catalogue generator;
- `b55e1cdc5b8c883b4300d59309f0568bae8a794d` — owned executable snapshots and
  nested symlink defence; and
- `8174ddd2aa8a0a535a30b232d9865e92e99d4ace` — direct-CI fitness authority
  parity.

All commits are authored by `three-cubes-agent[bot]`. The approved Task 4 source
and controller-owned `docs/IMPLEMENTATION.md` were not edited.

## Self-review

- Bootstrap consumes the current release catalogue and generated lock rather
  than maintaining another version source.
- Planner identities use the existing canonical lock/graph/input APIs; there is
  no parallel graph implementation.
- Managed launchers use the same owned bytes that warm validation hashes and
  probes, closing discovery-path substitution and warm-offline drift.
- State writes are outside the checkout, owned, staged and atomic; existing or
  suspicious state fails closed.
- Catalogue generation requires immutable inputs and does not publish or imply
  a final release.
- Task 1–4 public arities and behaviour remain unchanged.

No known blocker remains for independent review of this first slice. The
canonical image, Dev Container digest selection and final release-catalogue
publication remain explicitly deferred until their real built artefacts exist.
