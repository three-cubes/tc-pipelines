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

The coordinated release is `3.0.0`. After the third final review remediation
it binds source commit `0ae8c5ec01ca33f4db497b60c5d3159263a36828` and OCI index digest
`sha256:edd6cff09e62212679c4afb2186a77fed7aca026b182c363d72b8c8d34eac122`.
Nothing was pushed or published. In particular, no claim is made that the
catalogue's GHCR reference is remotely available: no authenticated registry
read was performed.

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
aggregate manifest digest, every canonical dependency input path/content digest
and the state-owned environment path.

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

The final real two-architecture OCI build produced:

```text
manifest list sha256:edd6cff09e62212679c4afb2186a77fed7aca026b182c363d72b8c8d34eac122
source commit 0ae8c5ec01ca33f4db497b60c5d3159263a36828
artifact artifacts/task5-release-0ae8c5e/image.oci.tar
build evidence artifacts/task5-release-0ae8c5e/build-receipt.json
verification evidence artifacts/task5-release-0ae8c5e/verification.json
```

The Dev Container and release catalogue both contain the manifest-list digest.
The release catalogue also binds package, workflow commit, schemas, fitness,
toolchains and bootstrap distribution provenance as one entry.

### 4. Frozen dependency materialisation

Bootstrap parses the pnpm lock importer graph and binds the root manifest,
`pnpm-workspace.yaml`, every importer manifest, `.npmrc` when present and every
declared patch file. It copies that exact graph into managed state and performs
one frozen workspace install, preserving workspace protocols and patches.
`uv.lock` and `pyproject.toml` are bound and materialised into the state-owned
Python environment. Installed workspace links, a patched package, `yaml==2.9.1`,
`attrs==26.1.0`, repository `nx` and the real `three-cubes-fitness==0.17.0` git
dependency are executed. Warm offline reuse validates every input digest; a
member-manifest or patch-byte change cannot reuse the old environment.

### 5. One executable remediation command

Every missing-prerequisite failure contains exactly one diagnostic and one
command:

- macOS: one `/bin/bash -lc` command installs the three Homebrew formulae and
  exact pnpm 11.22.0;
- Linux: one `docker pull ghcr.io/three-cubes/tc-sdlc@sha256:...` command uses
  the catalogue digest.

The macOS command is shell-syntax checked and the Linux executable is proven
available in the behavioural suite.

## Earlier independent-review remediation

The final five findings were reproduced and closed as follows:

1. The Homebrew pnpm Corepack shim failed with an empty/trap HOME and offline
   networking (`env: node: No such file or directory`, then an `ENOTDIR`
   Corepack config failure). The state launcher now invokes the resolved
   Corepack pnpm module with the validated Node executable and binds HOME,
   XDG config and Corepack cache to managed state. The public integration test
   runs the launcher with `PATH=/usr/bin:/bin`, a file-valued HOME and
   `COREPACK_ENABLE_NETWORK=0`; it reports 11.22.0.
2. The root-only pnpm materialisation omitted workspace importers and patches.
   A real fixture with two workspace-protocol members, an external dependency
   and a patch now proves complete graph installation. The receipt lists all
   six metadata inputs; one-byte member-manifest and patch changes both produce
   a distinct state key and fail offline reuse.
3. The canonical image initially failed `git --version` before it could resolve
   the repository's immutable uv git dependency. The final image contains git
   and make. Image verification bootstraps the actual repository pnpm and uv
   locks, imports `nx`, executes `three-cubes-fitness==0.17.0`, and repeats the
   bootstrap offline from verified warm state.
4. The generated Dev Container initially lacked `workspaceMount`. A behavioural
   verifier now substitutes an editor-opened source tree, starts the container
   with the generated bind semantics and reads an exact marker at `/workspace`.
5. The ordinary suite failed on Linux with five macOS-assumption failures. The
   six real Homebrew tests are now an explicit `test:integration:darwin` suite;
   ordinary tests contain portable bootstrap ownership/lock behavior. The
   Docker `package-tests` stage ran all 109 ordinary tests on Linux/arm64, and
   the final amd64 image executed public declaration/catalogue/lock behavior as
   Linux x64 while preserving `buildGraph/2` and `runGraph/3`.

An additional cross-location RED found that aggregate dependency manifest
digests accidentally included internal absolute `sourcePath` values. A public
relocation regression failed offline reuse before the fix. Manifest digests now
hash only canonical relative path/content-digest pairs; native and image
dependency evidence is byte-identical.

## Second final-review remediation

All five reproduced findings were first exercised through the public built
package or executable boundary:

1. A sandboxed warm Darwin bootstrap denied
   `/Users/danmcmahon/.cache/node/corepack` and returned
   `host_prerequisite_missing`. Capability probes now run with a state-owned
   HOME, XDG cache/config and `COREPACK_HOME`; the same sandboxed command now
   returns `status: ok, reused: true` without reading the ambient account.
2. Adding a package selected by `pnpm-workspace.yaml` but absent from the lock
   initially reached host discovery and returned `offline_cold`. Workspace
   package globs are now expanded independently, every matching `package.json`
   is inventoried, and exact equality with lock importers is required before
   host discovery or reuse. The sabotage now fails with
   `dependency_lock_invalid` and `PNPM_WORKSPACE_LOCK_MISMATCH`.
3. The prior receipt had no installed-tree content binding, and deleting
   `dependencies/node/node_modules` still returned `reused: true`. State schema
   v6 records `installedDigest` for every complete dependency materialisation.
   Any execution-relevant byte or mode change or deletion now returns
   `state_corrupt`; valid unchanged warm state still reuses offline.
4. Release building previously left a 677 MiB directory in the account home
   and only a `/private/tmp` pointer. `release:image` now requires a new,
   caller-selected direct child of repository-owned `artifacts/`, stages and
   atomically publishes it, refuses overwrite and records its exact evidence
   path and retention owner. Verification likewise requires explicit scratch
   and evidence paths and removes scratch in `finally`. After the replacement
   above passed verification, the superseded 32cc home artifact, pointer and
   intermediate replacement were deleted.
5. The Darwin integration suite no longer assumes x64 is foreign. It derives
   the unavailable architecture from the real fixed Homebrew capability paths
   and skips only the missing-capability assertion if both architectures are
   completely installed.

The first Linux image `package-tests` run then exposed one additional real
packaging RED: the public artifact commands were absent from the Docker build
context and two tests failed with `MODULE_NOT_FOUND`. The Dockerfile now copies
both release boundary scripts into the builder; the Linux stage passes all 112
portable tests.

## Third final-review remediation

The three rereview findings were reproduced through the built public bootstrap
API before implementation:

1. The uv evidence had no `installedDigest`; deleting or renaming an installed
   Python module was therefore accepted as warm reuse. State schema v6 now
   content- and mode-digests the complete Python environment. Only runtime
   `__pycache__`, `.pyc` and `.pyo` churn is excluded. Public tests execute
   `attrs`, prove cache creation does not break reuse, then independently rename
   its package and delete an imported `attr._make` module. Both import failures
   are rejected as `state_corrupt`, and exact restoration re-enables offline
   reuse.
2. Workspace staging previously copied only member manifests, leaving pnpm's
   workspace links pointed at packages without runnable exports. Every workspace
   member must now declare a non-empty, explicit, non-glob `files` inventory.
   Bootstrap rejects traversal, missing paths, symlinks and unsupported entries,
   binds each declared file into dependency identity and stages only that
   inventory. The checkout source export and installed workspace export both
   execute; a source-byte change produces a distinct offline-cold state key;
   an undeclared `.cache` file is neither bound nor copied.
3. Installed-tree digests previously omitted permission modes. They now bind
   root, directory and regular-file modes as well as bytes, link targets and
   traversal shape. Changing an installed `node_modules/.bin/yaml` launcher
   from executable to `0644` is rejected as `state_corrupt`.

The controller-provided rereview confirmed that five older artifacts totalling
approximately 1.35 GiB had already been permanently removed and their absence
verified. This report does not attribute that cleanup to this implementation
run. After the new `edd6` artifact passed end-to-end verification, this run also
removed the superseded `f78e72f` repository artifact and the old 4 KiB rereview
evidence directory. Only `artifacts/task5-release-0ae8c5e` remains, and both the
image verifier and Dev Container verifier left their caller-selected scratch
root absent.

## State, evidence and planning invariants

- State roots must be absolute, outside the checkout, non-symlinked and either
  empty or marked by the canonical ownership record. Foreign and partial state
  fail closed.
- Nested symlink traversal is rejected. Completion `state.json` is the last
  materialisation write; receipt writes use the existing canonical fsync and
  rename path.
- Warm reuse reprobes host prerequisites inside the managed probe environment,
  checks launcher, executable and adapter digests, exact state bindings and the
  content and mode digest of every installed dependency tree. Python runtime
  bytecode caches are the only excluded installed-tree paths.
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

Final built-public macOS integration result:

```text
Test Files  1 passed (1)
Tests       6 passed (6)
```

The suite covers arbitrary PATH, trap HOME, real Homebrew provenance, exact
catalogue uv, cold/warm offline behaviour, root and workspace dependency
execution, offline Corepack use, launcher corruption, manifest/patch drift,
foreign/symlink/in-checkout state, stale lock, relocation stability, canonical
receipt bytes, exact version constraints and both remediation commands.
Catalogue tests cover moving/unresolved refs and atomic output.

## Verification

Package build, complete tests and frozen pnpm lock:

```text
pnpm --filter @three-cubes/tc-sdlc build
pnpm --filter @three-cubes/tc-sdlc test
pnpm --filter @three-cubes/tc-sdlc test:integration:darwin
pnpm install --frozen-lockfile

Portable: 6 files and 112 tests passed. Explicit macOS integration: 1 file and
6 tests passed. Frozen lock already up to date; all exit 0.
```

Canonical image:

```text
docker buildx build --platform linux/amd64,linux/arm64 --output type=oci,...
exit 0; real manifest list digest recorded above.

docker buildx build --platform linux/amd64,linux/arm64 \
  --target package-tests --file images/sdlc/Dockerfile .
exit 0; Linux package stage contains and passes all 112 portable tests.

arm64 image smoke: UID 1000, Node 24.21.0, pnpm 11.22.0,
Python 3.13.15 and uv 0.12.5; exit 0.
amd64 image smoke under QEMU: the same versions and built CLI; exit 0.
```

`images/sdlc/verify.mjs` executed a fresh native macOS bootstrap and a fresh
arm64 canonical-image bootstrap, ran installed Node/Python dependencies and
the actual repository dependency closure, then repeated both image bootstraps
with networking disabled. Exit 0 with:

```text
release 3.0.0
lockDigest sha256:f9a8c2eacfcbb193c962154134d27b475e6d0f54c1a191b43afacd1c457f1915
taskIdentity sha256:9defe947ef9a47082cc615368e3641907a5df88aa5a53ba65aea1a265f36f208
nativePlatform darwin
imagePlatform linux
```

Both native and image receipts contain uv and pnpm `installedDigest` values.
The repository pnpm evidence additionally inventories the complete declared
`packages/tc-sdlc/dist` workspace export before executing `nx`; the repository
uv environment executes `three-cubes-fitness==0.17.0`. Both image bootstraps
then reuse the exact verified trees with networking disabled.

The Linux/amd64 image separately reported Node 24.21.0, pnpm 11.22.0, Python
3.13.15, uv 0.12.5, git 2.39.5 and GNU make 4.3, then executed the public
declaration/catalogue/lock path with `process.arch === "x64"`; exit 0.

The generated Dev Container verification launched the final local image with
the rendered `workspaceMount` semantics and read the exact opened-tree marker
from `/workspace`; exit 0.

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
- `19842e9` — initial generated immutable release catalogue and Dev Container;
- `29b7d20` — final-review launcher, workspace, image, Dev Container and
  portable-test remediation;
- `d2b133f` — regenerated immutable catalogue and Dev Container bound to the
  first remediated source and OCI index;
- `5dc3b0e` — managed prerequisite probes, independent workspace closure,
  installed-tree binding and explicit artifact/evidence retention contract;
- `f78e72f` — include release-boundary executables in Linux package tests;
- `b0f9621` — regenerate the immutable catalogue and Dev Container for source
  `f78e72f` and the verified `1d5d` OCI index;
- `0ae8c5e` — bind Python environments, explicit workspace source exports and
  installed execution modes;
- `3798bdd` — regenerate the immutable catalogue and Dev Container for source
  `0ae8c5e` and the verified `edd6` OCI index.

Earlier Task 5 coordination commits remain in history. All Task 5 commits are
authored by `three-cubes-agent[bot]`. `docs/IMPLEMENTATION.md` was not edited.

## Self-review

All findings from the independent reviews are addressed in production
behavior and built-public tests. Task 1-4 package behavior and the exact
two-argument `buildGraph` API remain intact. The worktree contains no
package-local lock, untracked release placeholder or simulated toolchain. No
known implementation blocker remains; the explicit remaining evidence
limitation is amd64 hosted hardware qualification, which belongs to Task 6
rather than this local arm64
workstation.
