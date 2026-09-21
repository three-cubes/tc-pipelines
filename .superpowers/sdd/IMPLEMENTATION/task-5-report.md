# Task 5 implementation report

Date: 2026-09-21

## Outcome

Task 5 is implemented from approved Task 4 foundation `6bff6ae`. The previous
PATH-discovery/copied-executable design was removed after independent review.
The implemented boundary is now:

- macOS uses explicit architecture-specific Homebrew prerequisites from the
  fixed Homebrew prefix and formula Cellars. Node 24, Python 3.13 and pnpm
  11.22.0 are probed from those fixed locations. Homebrew uv is only the
  installer for the complete catalogue-hashed uv 0.12.5 wheel environment;
- Linux bootstrap is accepted only inside the catalogue-selected canonical
  image, proven by `/etc/tc-sdlc-release.json` plus fixed `/usr/local/bin`
  executables. An arbitrary host `PATH` is never capability authority;
- the release-owned environment is materialised below an explicit state root
  outside the checkout. pnpm and uv install from the checked-in frozen locks,
  and neither `node_modules` nor `.venv` is written into the checkout;
- `images/sdlc/Dockerfile` builds the non-root canonical image for both
  `linux/amd64` and `linux/arm64`; package compilation runs on `BUILDPLATFORM`
  while the final toolchains are built for each target architecture;
- generated `.devcontainer/devcontainer.json` and `release/catalogue.json`
  select a real immutable multi-platform image digest; and
- native macOS and native arm64 canonical-image execution report the same
  release, lock digest, task identity, dependency-lock identities and exact
  toolchain versions.

The coordinated release is `3.0.0`. It binds source commit
`4078c28d5680eff3c8fd2264256ad91c1ec28fea` and OCI index digest
`sha256:73decf541ad1a15dda01b451b64c6da5b0d58b666898fdf3b7052f187141bb93`.
Nothing was pushed or published.

## Public contracts and authorities

The built package exports:

```ts
bootstrap(options: BootstrapOptions): Promise<BootstrapReceipt>
serialiseBootstrapReceipt(receipt: BootstrapReceipt): string
generateReleaseCatalogue(input: ReleaseCatalogueGeneration): ReleaseCatalogue
writeReleaseCatalogue(path: string, catalogue: ReleaseCatalogue): void
```

`BootstrapHost` contains only `platform`, `architecture` and `offline`; it has
no injectable PATH. `BootstrapOptions.stateRoot` is an explicit absolute path
outside the checkout. `BootstrapDependencyEvidence` binds manager, lock digest,
manifest digest and the state-owned environment path.

Canonical versions are Node 24 (image patch 24.21.0), pnpm 11.22.0, Python
3.13 (image patch 3.13.15), uv 0.12.5 and `three-cubes-fitness` 0.17.0 at
immutable commit `73d7ffc4b563849edcd607b377fbb3ee4ba6da32`.

## Review finding remediation

### 1. No trust learned from arbitrary PATH

macOS capability locations are fixed by architecture (`/opt/homebrew` on
arm64, `/usr/local` on x64), resolved through the `node@24`, `python@3.13` and
`uv` formula Cellars, probed for declared versions and content-digested into
the state receipt. Linux accepts only the canonical image marker and fixed
image paths. The former `host.path` contract was deleted.

### 2. No copied lone executables

Bootstrap does not copy Node, pnpm, Python or uv binaries. State launchers bind
the validated complete Homebrew/image installations. On macOS the complete uv
0.12.5 wheel is fetched from the catalogue URL, SHA-256 checked, installed into
a state-owned virtual environment and reprobed. The catalogue has a separate
real PyPI wheel URL and digest for darwin/linux x arm64/x64.

### 3. Canonical image, Dev Container and catalogue

The image uses digest-pinned Python 3.13.15 and uv 0.12.5 bases, SHA-256-pinned
official Node 24.21.0 archives for both architectures and exact pnpm 11.22.0.
It installs the packed `@three-cubes/tc-sdlc` 3.0.0 package and runs as UID
1000. `generate-release.mjs` rejects unresolved refs, moving image refs,
nonexistent commits and the old 2.2.0 version before atomically rendering both
release files.

The real two-architecture OCI build produced:

```text
linux/amd64 manifest sha256:d991e0480a18221dd21e31308fdc16b2a50fb243896f5498ed250a0c0d0b737f
linux/arm64 manifest sha256:a4b127fb12c2bdc5f765a32ae59de2a7fa3b8c7ea98855f8a41b4a61ad3f21f7
manifest list sha256:73decf541ad1a15dda01b451b64c6da5b0d58b666898fdf3b7052f187141bb93
```

The Dev Container and release catalogue both contain the manifest-list digest.
The release catalogue also binds package, workflow commit, schemas, fitness,
toolchains and bootstrap distribution provenance as one entry.

### 4. Frozen dependency materialisation

Bootstrap discovers `pnpm-lock.yaml`/`package.json` and
`uv.lock`/`pyproject.toml` pairs. It binds both lock and manifest digests into
the state key, copies the pnpm manifest and lock into managed state before a
frozen install, and directs uv's project environment into managed state.
Installed `yaml==2.9.1` and `attrs==26.1.0` are executed in both native and
canonical-image verification. Warm offline reuse validates the state and a
manifest-only change cannot reuse the old environment.

### 5. One executable remediation command

Every missing-prerequisite failure contains exactly one diagnostic and one
command:

- macOS: one `/bin/bash -lc` command installs the three Homebrew formulae and
  exact pnpm 11.22.0;
- Linux: one `docker pull ghcr.io/three-cubes/tc-sdlc@sha256:...` command uses
  the catalogue digest.

The macOS command is shell-syntax checked and the Linux executable is proven
available in the behavioural suite.

## State, evidence and planning invariants

- State roots must be absolute, outside the checkout, non-symlinked and either
  empty or marked by the canonical ownership record. Foreign and partial state
  fail closed.
- Nested symlink traversal is rejected. Completion `state.json` is the last
  materialisation write; receipt writes use the existing canonical fsync and
  rename path.
- Warm reuse reprobes host prerequisites, checks launcher, executable and
  adapter digests, exact state bindings and dependency environment presence.
- Bootstrap calls `assertCurrentLock`, the canonical input resolver,
  `bindGraphLock`, and the exact two-argument `buildGraph`. There is no second
  lock, input or graph implementation.
- Receipts are canonical, bounded and omit HOME, absolute state paths, process
  output and discovered host paths.

## TDD evidence

Initial review RED against the built package:

```text
test/bootstrap-review.test.ts: 0/2 passed
- arbitrary Linux PATH produced PATH-derived capability failures instead of
  the canonical-image remediation;
- real Homebrew bootstrap observed host uv 0.12.15 rather than materialising
  the exact catalogue-owned uv 0.12.5 environment.
```

The first GREEN was 4/4 against real Homebrew and the built CLI. Dependency
isolation sabotage then exposed a real defect: pnpm installed the dependency
but also wrote workspace metadata in the checkout, and a later container run
mistook that metadata for completed state. A new public regression asserted no
checkout `node_modules`/`.venv`, actual dependency execution and manifest-bound
state. It failed before the state-owned-manifest change and now passes. A fifth
test covers schema-level version sabotage and the macOS remediation command.

Final built-public focused result:

```text
Test Files  1 passed (1)
Tests       5 passed (5)
```

The suite covers arbitrary PATH, trap HOME, real Homebrew provenance, exact
catalogue uv, cold/warm offline behaviour, dependency execution, launcher
corruption, manifest drift, foreign/symlink/in-checkout state, stale lock,
canonical receipt bytes, exact version constraints and both remediation
commands. Catalogue tests cover moving/unresolved refs and atomic output.

## Verification

Package build, complete tests and frozen pnpm lock:

```text
pnpm --filter @three-cubes/tc-sdlc build
pnpm --filter @three-cubes/tc-sdlc test
pnpm install --frozen-lockfile

6 files passed; 112 tests passed; lock already up to date; exit 0.
```

Canonical image:

```text
docker buildx build --platform linux/amd64,linux/arm64 --output type=oci,...
exit 0; real manifest list digest recorded above.

arm64 image smoke: UID 1000, Node 24.21.0, pnpm 11.22.0,
Python 3.13.15 and uv 0.12.5; exit 0.
amd64 image smoke under QEMU: the same versions and built CLI; exit 0.
```

`images/sdlc/verify.mjs` executed a fresh native macOS bootstrap and a fresh
arm64 canonical-image bootstrap, ran installed Node and Python dependencies,
then repeated the image bootstrap with networking disabled. Exit 0 with:

```text
release 3.0.0
lockDigest sha256:60cffc4857582a899250d151151ddbc50a2206b57769294eb928326677ef583b
taskIdentity sha256:491f46293fa05e044a70337fb791e102336420dd6a076e51895ecde6896b94c1
nativePlatform darwin
imagePlatform linux
```

Python and repository fitness:

```text
uv sync --frozen
uv run --no-sync pytest -q
1974 passed, 9 pre-existing temporary-cleanup warnings, exit 0.

uv run --no-sync tc-fitness run
1974 passed; contract-tests, actionlint, yamllint, licence and branch naming
all PASS; 5 ran, 0 skipped; exit 0.
```

Packed consumer:

```text
pnpm --filter @three-cubes/tc-sdlc pack --pack-destination <temp>
npm install --ignore-scripts --prefix <empty-consumer> <tarball>
node --input-type=module <public export probe>
```

Exit 0. The clean consumer imported bootstrap and catalogue generation,
confirmed `bootstrap/1`, preserved `buildGraph/2` and `runGraph/3`, and observed
the coordinated fitness and package-manager versions.

Release rendering was repeated with the exact source commit and image digest;
the canonical files were unchanged. Public catalogue loading then proved the
Dev Container image and environment values exactly match the release entry.

## Emulation limitation

The complete amd64 bootstrap was additionally attempted under arm64 Docker
QEMU. pnpm completed and materialised the requested dependency, then emulated
Node 24 aborted in libuv with `uv__io_poll: Assertion errno == EEXIST` and left
a QEMU core file. The same failure reproduced when the Docker build compiled
the package under target-architecture emulation; moving architecture-neutral
compilation to `BUILDPLATFORM` fixed the two-architecture build. Native arm64
image end-to-end execution and amd64 image runtime/tool smoke pass. This report
does not misrepresent the failed QEMU-only full bootstrap as amd64 hardware
qualification; hosted amd64 execution remains Task 6 evidence.

## Commits

- `3774e78` — explicit host/canonical-image bootstrap, dependencies, image and
  generators;
- `4078c28` — native build-platform packaging for the multiarchitecture image;
- `19842e9` — generated immutable release catalogue and Dev Container.

Earlier Task 5 coordination commits remain in history. All Task 5 commits are
authored by `three-cubes-agent[bot]`. `docs/IMPLEMENTATION.md` was not edited.

## Self-review

All five independent-review findings are addressed in production behavior and
built-public tests. Task 1-4 package behavior and the exact two-argument
`buildGraph` API remain intact. The worktree contains no package-local lock,
untracked release placeholder or simulated toolchain. No known implementation
blocker remains; the explicit remaining evidence limitation is amd64 hosted
hardware qualification, which belongs to Task 6 rather than this local arm64
workstation.
