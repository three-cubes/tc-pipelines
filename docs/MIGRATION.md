# AI SDLC Consumer Migration

This guide moves a repository onto the released SDLC product,
`@three-cubes/tc-sdlc` v4: Nx with the tc-sdlc plugin, mise for the toolchain,
one uv workspace and one pnpm workspace, and `tc-fitness` as a graph task. The
product contract lives in
[`governance/standards/ai-sdlc-product-architecture.md`](../governance/standards/ai-sdlc-product-architecture.md).
v4 replaces v3's `sdlc.yaml`, `tc-sdlc.lock` and `tc-sdlc` CLI; a repository on v3
migrates by adopting v4 and then deleting them (step 9).

## What a migrated repository holds

| File | Holds | Written by |
|---|---|---|
| `mise.toml` | Every tool version (uv, Node, pnpm) and the workspace Python (`UV_PYTHON`) | `init`; `nx sync` keeps it on the release catalogue |
| `nx.json` | The `@three-cubes/tc-sdlc` and `@nxlv/python` plugins, cacheable task defaults and the `@three-cubes/tc-sdlc:sync` generator | `init` |
| `package.json` | Nx, `@nx/devkit` and `@three-cubes/tc-sdlc` as dev dependencies | `init` |
| `.npmrc` | The `@three-cubes` scope on GitHub Packages, authenticated by `NODE_AUTH_TOKEN` | `init` |
| `pyproject.toml` | `[tool.uv.workspace]` members and the `[tool.tc_fitness]` gate | the repository |
| `pnpm-workspace.yaml` | The pnpm workspace members | the repository |
| `uv.lock`, `pnpm-lock.yaml` | The one lock of each workspace | uv and pnpm |
| `.github/workflows/quality-gate.yml` | The thin hosted gate | `init` |

## 1. Inventory the consumer

Record the package and workspace boundaries, generated inputs and outputs,
current local commands, workflow jobs and triggers, the fitness configuration,
container builds, qualification journeys, runtime state and secrets, deployment
and rollback commands, and every workflow, action, fitness and toolchain pin.
Classify each item as shared SDLC behaviour or product behaviour using
[`RESOLVER.md`](../RESOLVER.md).

## 2. One uv workspace and one pnpm workspace

Make each language one workspace at the repository root: every Python package a
member of `[tool.uv.workspace]` with one `uv.lock`, every Node package a member of
`pnpm-workspace.yaml` with one `pnpm-lock.yaml`. Delete per-package locks,
virtual environments and version files. The plugin infers projects only from
workspace members.

## 3. Adopt the plugin

GitHub Packages serves `@three-cubes/tc-sdlc`. Give the install a token that can
read the org's packages: locally `export NODE_AUTH_TOKEN=$(gh auth token)` with
the `read:packages` scope; in CI the job token, once the package's settings
grant the repository Actions access. Then:

```bash
printf '@three-cubes:registry=https://npm.pkg.github.com\n//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}\n' > .npmrc
pnpm add -D -w @three-cubes/tc-sdlc
test -f nx.json || echo '{}' > nx.json
pnpm exec nx g @three-cubes/tc-sdlc:init
```

`init` registers the plugins and the sync generator in `nx.json`, adds the Nx
packages at the catalogue's versions, and writes `mise.toml`, `.npmrc` and the
gate workflow where the repository has none. It leaves an existing file to its
owner and says so. Then install from the locks:

```bash
mise install
uv lock && uv sync --locked --all-packages
pnpm install
```

## 4. Check the project graph

`pnpm exec nx show projects` lists what the plugin inferred:

- each uv member with tests is a project named by its `[project].name`, with a
  `test` target that runs its pytest suite;
- each pnpm member is a project, with its `package.json` scripts as targets;
- a project outside both workspaces keeps a `project.json`;
- every project is tagged `layer:<its first path segment>` and `lang:python` or
  `lang:typescript`.

Represent generators, images and qualification journeys as targets of the
project that owns them.

## 5. Integrate tc-fitness

A `pyproject.toml` that declares `[tool.tc_fitness]` gains a `fitness` target
with one configuration per tier: `nx run <project>:fitness:smoke`, `:full` and
`:nightly`. Before it runs the tier, the `@three-cubes/tc-sdlc:fitness` executor
rejects an installed `three-cubes-fitness` that differs from the catalogue's
`fitnessVersion` (or, without one, from the version `uv.lock` resolves). Keep the
native `tc-fitness` configuration as the check catalogue and policy source.

## 6. Run the gate locally and hosted

Locally, the affected loop is:

```bash
pnpm exec nx affected -t test typecheck build lint
pnpm exec nx run <root project>:fitness:smoke
```

Keep stable `make` commands as thin aliases for these when the repository has
them. The gate workflow `init` writes runs the same commands in CI: it checks the
pins with `nx sync:check`, takes the affected range from `nrwl/nx-set-shas`,
restores the Nx cache (a pull request reads `main`'s cache and never writes it),
and runs every fitness target at the full tier. To retain run evidence, set the
plugin's `receipts` option to a directory and upload it: each Nx run then writes
its task hashes and outcomes, the commit and the lockfile digests.

## 7. Qualify one immutable candidate

Build the application image once and record its digest. Run local and hosted
qualification against that digest. Exercise:

- clean startup and dependency health;
- required files, directories, symlinks and permissions;
- secrets and environment resolution;
- persistent-state harvest and restore;
- representative product journeys;
- failure diagnostics and cleanup.

Qualification produces the candidate receipt consumed by deployment.

## 8. Adopt the deployment transaction

Converge host prerequisites through the shared Ansible roles. Keep product
Compose definitions, state mappings, agent definitions and PVT journeys in the
consumer.

Exercise these paths before production reliance:

1. status and preflight;
2. repeated host convergence with zero second-run changes;
3. successful candidate start and PVT;
4. failed health check and predecessor restoration;
5. failed PVT and predecessor restoration;
6. interrupted operation and lock recovery;
7. cleanup with active and predecessor images retained.

The target deployment contract gives the Cloudflare SSH and Azure transports
the same typed operation and receipt. This transport parity is not implemented
yet; it is a deployment-transaction tranche deliverable.

The current compatibility surfaces remain distinct:

- `cloudflare-access-ssh` accepts a `tc.deploy.request.v1` operation and
  validates the returned deployment receipt;
- `azure-vm-deploy.yml` accepts Azure-specific inputs plus a YAML list of
  `{vm-name, apply-script, smoke-units}` targets and returns its current
  preflight, snapshot and optional apply outputs.

Use the current Azure caller contract documented in `README.md` until the
shared request-and-receipt interface has executable contract tests and consumer
acceptance evidence. Do not switch transports by configuration before then.

The existing Azure compatibility caller inherits workflow permissions. A caller
that uses WIF and no GHCR token declares:

```yaml
permissions:
  contents: read
  id-token: write
```

The hosted job adds package access only when it opts into the documented token
transport. The coordinated deployment path replaces this caller after the typed
SSH/Azure transport passes the same acceptance journeys.

## 9. Upgrade, and remove superseded surfaces

An upgrade is one coordinated change: bump `@three-cubes/tc-sdlc`, run
`pnpm exec nx sync`, commit. The sync generator moves the `mise.toml` tool
versions, every workflow pin of a catalogue action and the plugin's
`fitnessVersion` to the installed release catalogue, and `nx sync:check` fails in
the gate until they match.

Then produce a removal inventory that names each old file, its replacement and
the evidence that the replacement passed, and remove each item:

- v3's `sdlc.yaml`, `tc-sdlc.lock` and `tc-sdlc` CLI calls;
- copied workflow jobs and calls to reusables the gate workflow replaces;
- consumer-specific tool installation and per-package locks or environments;
- shell task schedulers and affected-set scripts;
- independent workflow, toolchain and fitness repin scripts;
- duplicate full post-merge checks.

## Rollback during migration

Revert the `@three-cubes/tc-sdlc` bump and run `pnpm exec nx sync`: the pins
return to the previous release's catalogue. For application deployment, select
the previous qualified image digest and its state receipt.

## Migration completion evidence

A consumer is converged when:

- `nx show projects` holds every package, each with its layer and language tags;
- `nx sync:check` passes and the gate workflow is green;
- an unchanged `nx affected` run is served from the Nx cache;
- every fitness target passes at the full tier through the executor;
- one candidate digest passes local qualification, hosted qualification and
  production PVT, and rollback has been exercised;
- the superseded surfaces are removed and recorded.
