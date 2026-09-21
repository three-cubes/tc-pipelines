import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { cpSync, existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, readlinkSync, realpathSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, posix } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "vitest";
import { parse, stringify } from "yaml";

const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const fixtureRoot = fileURLToPath(new URL("../../../assurance/fixtures/sdlc/python", import.meta.url));
const candidateCatalogue = fileURLToPath(new URL("../../../release/catalogue.json", import.meta.url));
const childTimeoutMs = 120_000;

function hash(bytes: string | Buffer): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

function canonical(value: unknown): string {
  const keys = new Set<string>();
  JSON.stringify(value, (key, child: unknown) => { keys.add(key); return child; });
  return `${JSON.stringify(value, [...keys].sort(), 2)}\n`;
}

function directoryArtifactDigest(root: string): string {
  const rootMetadata = lstatSync(root);
  expect(rootMetadata.isDirectory()).toBe(true);
  expect(rootMetadata.isSymbolicLink()).toBe(false);
  const entries: Record<string, unknown>[] = [
    { path: ".", type: "directory", mode: rootMetadata.mode & 0o7777 },
  ];
  const visit = (directory: string, prefix: string): void => {
    for (const name of readdirSync(directory).sort()) {
      const path = join(directory, name);
      const relativePath = prefix === "" ? name : posix.join(prefix, name);
      const metadata = lstatSync(path);
      if (metadata.isSymbolicLink()) {
        entries.push({ path: relativePath, type: "symlink", target: readlinkSync(path) });
      } else if (metadata.isDirectory()) {
        entries.push({ path: relativePath, type: "directory", mode: metadata.mode & 0o7777 });
        visit(path, relativePath);
      } else {
        expect(metadata.isFile()).toBe(true);
        entries.push({ path: relativePath, type: "file", mode: metadata.mode & 0o7777, digest: hash(readFileSync(path)) });
      }
    }
  };
  visit(root, "");
  return hash(canonical(entries));
}

function inventory(root: string): unknown[] {
  return readdirSync(root).sort().map((name) => {
    const path = join(root, name);
    const metadata = lstatSync(path);
    return [name, metadata.mode & 0o777, metadata.isSymbolicLink()
      ? { link: readlinkSync(path) }
      : metadata.isDirectory() ? inventory(path) : hash(readFileSync(path))];
  });
}

function childEnvironment(home: string): NodeJS.ProcessEnv {
  mkdirSync(home, { recursive: true, mode: 0o700 });
  return {
    PATH: process.env.PATH,
    HOME: home,
    TMPDIR: process.env.TMPDIR,
    TMP: process.env.TMP,
    TEMP: process.env.TEMP,
    LANG: process.env.LANG,
    LC_ALL: process.env.LC_ALL,
    GIT_CONFIG_NOSYSTEM: "1",
    GIT_CONFIG_GLOBAL: "/dev/null",
    GIT_TERMINAL_PROMPT: "0",
  };
}

function installPackedCli(): string {
  const packageDirectory = mkdtempSync(join(tmpdir(), "tc-sdlc-bootstrap-package-"));
  const environment = childEnvironment(join(packageDirectory, "home"));
  execFileSync("pnpm", ["pack", "--pack-destination", packageDirectory], {
    cwd: packageRoot,
    env: environment,
    encoding: "utf8",
    timeout: childTimeoutMs,
  });
  const archives = readdirSync(packageDirectory).filter((name) => name.endsWith(".tgz"));
  expect(archives).toHaveLength(1);
  const installation = mkdtempSync(join(tmpdir(), "tc-sdlc-bootstrap-installation-"));
  execFileSync("pnpm", ["add", "--ignore-scripts", "--lockfile=false", join(packageDirectory, archives[0]!)], {
    cwd: installation,
    env: environment,
    encoding: "utf8",
    timeout: childTimeoutMs,
  });
  return join(installation, "node_modules", ".bin", "tc-sdlc");
}

function invoke(cli: string, cwd: string, environment: NodeJS.ProcessEnv, command: string, args: readonly string[]) {
  const result = spawnSync(cli, [command, ...args], {
    cwd,
    env: environment,
    encoding: "utf8",
    timeout: childTimeoutMs,
  });
  expect(result.error).toBeUndefined();
  expect(result.status, result.stderr || result.stdout).toBe(0);
  return result;
}

test("the packed bootstrap command owns reproducible state and terminal receipts", () => {
  const cli = installPackedCli();
  const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-bootstrap-acceptance-"));
  const root = join(directory, "checkout");
  cpSync(fixtureRoot, root, { recursive: true });
  const declarationPath = join(root, "sdlc.yaml");
  const declaration = parse(readFileSync(declarationPath, "utf8"));
  for (const target of Object.values(declaration.targets) as { inputs: string[] }[]) target.inputs.sort();
  writeFileSync(declarationPath, stringify(declaration));

  const environment = childEnvironment(join(directory, "home"));
  const git = (...args: string[]) => execFileSync("git", args, {
    cwd: root,
    env: environment,
    encoding: "utf8",
    timeout: childTimeoutMs,
  });
  git("init", "--quiet");
  git("config", "user.name", "SDLC bootstrap fixture");
  git("config", "user.email", "fixture@example.invalid");
  git("config", "commit.gpgsign", "false");
  git("config", "core.hooksPath", "/dev/null");

  const cataloguePath = join(directory, "catalogue.json");
  const lockPath = join(root, "tc-sdlc.lock");
  invoke(cli, root, environment, "catalogue", ["--input", candidateCatalogue, "--output", cataloguePath]);
  invoke(cli, root, environment, "lock", ["--declaration", declarationPath, "--catalogue", cataloguePath, "--output", lockPath]);
  git("add", ".");
  git("commit", "--quiet", "-m", "fixture inputs");
  const before = inventory(root);

  const stateRoot = join(directory, "state");
  const firstPath = join(directory, "bootstrap-first.json");
  const secondPath = join(directory, "bootstrap-second.json");
  const common = [
    "--declaration", declarationPath,
    "--catalogue", cataloguePath,
    "--lock", lockPath,
    "--root", root,
    "--state-root", stateRoot,
  ];
  invoke(cli, root, environment, "bootstrap", [...common, "--receipt", firstPath]);
  const first = JSON.parse(readFileSync(firstPath, "utf8"));
  const catalogue = JSON.parse(readFileSync(cataloguePath, "utf8"));
  const lock = JSON.parse(readFileSync(lockPath, "utf8"));
  expect(Object.keys(first).sort()).toEqual([
    "adapters", "architecture", "dependencies", "diagnostics", "diagnosticsCount",
    "diagnosticsTruncated", "lockDigest", "platform", "reason", "recovery", "release",
    "reused", "schema", "stateDigest", "stateKey", "status", "taskIdentities",
  ].sort());
  expect(first).toMatchObject({
    schema: "tc.sdlc/bootstrap-receipt/v1",
    status: "succeeded",
    reason: null,
    release: catalogue.release.version,
    lockDigest: hash(canonical(lock)),
    platform: process.platform,
    architecture: process.arch,
    reused: false,
    stateDigest: expect.stringMatching(/^sha256:[a-f0-9]{64}$/),
    stateKey: expect.any(String),
    diagnostics: [],
    diagnosticsCount: 0,
    diagnosticsTruncated: false,
    recovery: { schema: "tc.sdlc/automatic-recovery/v1", status: "succeeded" },
  });
  expect(first.taskIdentities.length).toBeGreaterThan(0);
  for (const identity of first.taskIdentities) expect(identity).toMatch(/^sha256:[a-f0-9]{64}$/);
  expect(first.adapters.map((adapter: { name: string }) => adapter.name).sort()).toEqual(["node", "pnpm", "python", "uv"]);
  for (const adapter of first.adapters) {
    expect(adapter).toMatchObject({
      version: expect.any(String),
      provider: expect.any(String),
      executableDigest: expect.stringMatching(/^sha256:[a-f0-9]{64}$/),
      launcherDigest: expect.stringMatching(/^sha256:[a-f0-9]{64}$/),
      adapterDigest: expect.stringMatching(/^sha256:[a-f0-9]{64}$/),
      launcher: expect.any(String),
    });
  }
  expect(first.dependencies).toHaveLength(1);
  const expectedDependencyInputs = ["pyproject.toml", "uv.lock"].map((path) => ({
    path,
    digest: hash(readFileSync(join(root, path))),
  }));
  expect(first.dependencies[0]).toMatchObject({
    manager: "uv",
    lockDigest: hash(readFileSync(join(root, "uv.lock"))),
    manifestDigest: hash(canonical(expectedDependencyInputs.filter((input) => input.path !== "uv.lock"))),
    environment: "dependencies/python",
    inputs: expectedDependencyInputs,
    installedDigest: expect.stringMatching(/^sha256:[a-f0-9]{64}$/),
  });
  const dependencyBinding = first.dependencies.map(({ installedDigest: _installedDigest, ...binding }: Record<string, unknown>) => binding);
  const dependencyDigest = hash(canonical(dependencyBinding));
  const expectedStateKey = `releases/${first.lockDigest.slice("sha256:".length)}/${dependencyDigest.slice("sha256:".length)}/${first.platform}-${first.architecture}`;
  expect(first.stateKey).toBe(expectedStateKey);
  const stateDirectory = join(stateRoot, first.stateKey);
  const statePath = join(stateDirectory, "state.json");
  expect(existsSync(statePath)).toBe(true);
  const stateBytes = readFileSync(statePath);
  const state = JSON.parse(stateBytes.toString("utf8"));
  expect(first.stateDigest).toBe(hash(stateBytes));
  expect(state).toMatchObject({
    schema: "tc.sdlc/bootstrap-state/v6",
    release: first.release,
    lockDigest: first.lockDigest,
    dependencyDigest,
    platform: first.platform,
    architecture: first.architecture,
    dependencies: first.dependencies,
  });
  expect(state.adapters.map(({ executable: _executable, ...adapter }: Record<string, unknown>) => adapter)).toEqual(first.adapters);
  const declaredVersions: Record<string, string> = {
    node: declaration.toolchains.node,
    pnpm: declaration.toolchains.packageManager.replace(/^pnpm@/, ""),
    python: declaration.toolchains.python,
    uv: declaration.toolchains.uv,
  };
  for (const adapter of state.adapters) {
    expect(adapter.version).toBe(declaredVersions[adapter.name]);
    expect(["homebrew", "canonical-image", "catalogue-distribution"]).toContain(adapter.provider);
    const launcher = join(stateRoot, adapter.launcher);
    expect(existsSync(launcher)).toBe(true);
    expect(lstatSync(launcher).isSymbolicLink()).toBe(false);
    expect(hash(readFileSync(launcher))).toBe(adapter.launcherDigest);
    expect(existsSync(adapter.executable)).toBe(true);
    const independentlyObservedExecutableDigest = adapter.name === "pnpm" && adapter.provider === "catalogue-distribution"
      ? directoryArtifactDigest(dirname(dirname(adapter.executable)))
      : hash(readFileSync(adapter.executable));
    expect(adapter.executableDigest).toBe(independentlyObservedExecutableDigest);
    expect(adapter.adapterDigest).toBe(hash(canonical({
      name: adapter.name,
      version: adapter.version,
      provider: adapter.provider,
      executableDigest: independentlyObservedExecutableDigest,
      launcherDigest: hash(readFileSync(launcher)),
    })));
  }
  expect(JSON.parse(readFileSync(join(stateRoot, ".tc-sdlc-owner.json"), "utf8"))).toEqual({
    owner: "@three-cubes/tc-sdlc",
    schema: "tc.sdlc/state-owner/v1",
  });
  const committedReferences = readdirSync(join(stateRoot, "references")).filter((name) => name.endsWith(".json"));
  expect(committedReferences).toHaveLength(1);
  const reference = JSON.parse(readFileSync(join(stateRoot, "references", committedReferences[0]!), "utf8"));
  const identity = lstatSync(stateDirectory, { bigint: true });
  expect(reference).toMatchObject({
    schema: "tc.sdlc/bootstrap-reference/v2",
    owner: "@three-cubes/tc-sdlc",
    phase: "committed",
    consumer: declaration.project,
    consumerRoot: realpathSync(root),
    currentStateKey: first.stateKey,
    currentStateIdentity: {
      device: identity.dev.toString(),
      inode: identity.ino.toString(),
      birthtimeNanoseconds: identity.birthtimeNs.toString(),
    },
  });
  expect(readdirSync(join(stateRoot, "references", "pending"))).toEqual([]);
  expect(readdirSync(join(stateRoot, "references", "locks"))).toEqual([]);
  expect(inventory(root)).toEqual(before);

  invoke(cli, root, environment, "bootstrap", [...common, "--receipt", secondPath]);
  const second = JSON.parse(readFileSync(secondPath, "utf8"));
  expect(second).toMatchObject({
    schema: "tc.sdlc/bootstrap-receipt/v1",
    status: "succeeded",
    reason: null,
    reused: true,
    stateKey: first.stateKey,
    stateDigest: first.stateDigest,
    taskIdentities: first.taskIdentities,
    adapters: first.adapters,
    dependencies: first.dependencies,
  });
  expect(hash(readFileSync(statePath))).toBe(first.stateDigest);
  expect(lstatSync(stateDirectory, { bigint: true }).ino.toString()).toBe(identity.ino.toString());
  expect(readdirSync(join(stateRoot, "references", "pending"))).toEqual([]);
  expect(readdirSync(join(stateRoot, "references", "locks"))).toEqual([]);
  expect(inventory(root)).toEqual(before);

  const coldStateRoot = join(directory, "cold-state");
  const failedPath = join(directory, "bootstrap-failed.json");
  const failed = spawnSync(cli, ["bootstrap", ...common.slice(0, -2), "--state-root", coldStateRoot, "--offline", "true", "--receipt", failedPath], {
    cwd: root,
    env: environment,
    encoding: "utf8",
    timeout: childTimeoutMs,
  });
  expect(failed.error).toBeUndefined();
  expect(failed.status).toBe(1);
  expect(JSON.parse(failed.stderr)).toMatchObject({
    schema: "tc.sdlc/command-error/v1",
    command: "bootstrap",
    status: "error",
    error: { code: "BOOTSTRAP_FAILED" },
  });
  const failure = JSON.parse(readFileSync(failedPath, "utf8"));
  expect(failure).toMatchObject({
    schema: "tc.sdlc/bootstrap-receipt/v1",
    status: "failed",
    reason: "offline_cold",
    release: first.release,
    lockDigest: first.lockDigest,
    stateDigest: null,
    reused: false,
    diagnostics: [expect.objectContaining({ code: "BOOTSTRAP_OFFLINE_COLD" })],
    diagnosticsCount: 1,
    diagnosticsTruncated: false,
  });
  expect(inventory(root)).toEqual(before);
}, 180_000);
