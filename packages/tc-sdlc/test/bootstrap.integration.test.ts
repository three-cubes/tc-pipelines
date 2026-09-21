import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { cpSync, existsSync, lstatSync, mkdtempSync, readFileSync, readdirSync, readlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
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

function inventory(root: string): unknown[] {
  return readdirSync(root).sort().map((name) => {
    const path = join(root, name);
    const metadata = lstatSync(path);
    return [name, metadata.mode & 0o777, metadata.isSymbolicLink()
      ? { link: readlinkSync(path) }
      : metadata.isDirectory() ? inventory(path) : hash(readFileSync(path))];
  });
}

function childEnvironment(): NodeJS.ProcessEnv {
  return {
    ...Object.fromEntries(Object.entries(process.env).filter(([name]) => !name.toUpperCase().startsWith("GIT_"))),
    GIT_CONFIG_NOSYSTEM: "1",
    GIT_CONFIG_GLOBAL: "/dev/null",
    GIT_TERMINAL_PROMPT: "0",
  };
}

function installPackedCli(): string {
  const packageDirectory = mkdtempSync(join(tmpdir(), "tc-sdlc-bootstrap-package-"));
  execFileSync("pnpm", ["pack", "--pack-destination", packageDirectory], {
    cwd: packageRoot,
    encoding: "utf8",
    timeout: childTimeoutMs,
  });
  const archives = readdirSync(packageDirectory).filter((name) => name.endsWith(".tgz"));
  expect(archives).toHaveLength(1);
  const installation = mkdtempSync(join(tmpdir(), "tc-sdlc-bootstrap-installation-"));
  execFileSync("pnpm", ["add", "--ignore-scripts", "--lockfile=false", join(packageDirectory, archives[0]!)], {
    cwd: installation,
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

  const environment = childEnvironment();
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
  expect(first.dependencies[0]).toMatchObject({
    manager: "uv",
    lockDigest: expect.stringMatching(/^sha256:[a-f0-9]{64}$/),
    manifestDigest: expect.stringMatching(/^sha256:[a-f0-9]{64}$/),
    environment: expect.any(String),
    installedDigest: expect.stringMatching(/^sha256:[a-f0-9]{64}$/),
  });
  expect(existsSync(join(stateRoot, first.stateKey))).toBe(true);
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
  expect(inventory(root)).toEqual(before);
}, 180_000);
