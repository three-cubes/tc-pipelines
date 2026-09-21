import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { cpSync, existsSync, lstatSync, mkdtempSync, readFileSync, readdirSync, readlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import Ajv2020 from "ajv/dist/2020.js";
import { expect, test } from "vitest";
import { parse, stringify } from "yaml";

const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const fixtureRoot = fileURLToPath(new URL("../../../assurance/fixtures/sdlc/python", import.meta.url));
const candidateCatalogue = fileURLToPath(new URL("../../../release/catalogue.json", import.meta.url));

function hash(bytes: string | Buffer): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

// Independent canonical JSON oracle: collect keys for JSON.stringify's ordered replacer.
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

function installPackedCli() {
  const archiveRoot = mkdtempSync(join(tmpdir(), "fitness-package-"));
  execFileSync("pnpm", ["pack", "--pack-destination", archiveRoot], { cwd: packageRoot, encoding: "utf8" });
  const archives = readdirSync(archiveRoot).filter((name) => name.endsWith(".tgz"));
  expect(archives).toHaveLength(1);
  const installation = mkdtempSync(join(tmpdir(), "fitness-install-"));
  execFileSync("pnpm", ["add", "--ignore-scripts", "--lockfile=false", join(archiveRoot, archives[0]!)], {
    cwd: installation, encoding: "utf8",
  });
  return {
    cli: join(installation, "node_modules", ".bin", "tc-sdlc"),
    schemas: join(installation, "node_modules", "@three-cubes", "tc-sdlc", "dist", "schemas"),
  };
}

test("the packed fitness command runs only its genuine bootstrapped fitness task and owns terminal evidence", () => {
  const { cli, schemas } = installPackedCli();
  const directory = mkdtempSync(join(tmpdir(), "fitness-acceptance-"));
  const root = join(directory, "checkout");
  cpSync(fixtureRoot, root, { recursive: true });
  const declarationPath = join(root, "sdlc.yaml");
  const declaration = parse(readFileSync(declarationPath, "utf8"));
  // Give the public command already-normalised fixture inputs, without its normaliser.
  for (const target of Object.values(declaration.targets) as { inputs: string[] }[]) target.inputs.sort();
  writeFileSync(declarationPath, stringify(declaration));

  const environment = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith("GIT_")));
  environment.GIT_CONFIG_NOSYSTEM = "1";
  environment.GIT_CONFIG_GLOBAL = "/dev/null";
  const git = (...args: string[]) => execFileSync("git", args, { cwd: root, env: environment, encoding: "utf8" });
  git("init", "--quiet");
  git("config", "user.name", "SDLC fixture");
  git("config", "user.email", "fixture@example.invalid");
  git("config", "commit.gpgsign", "false");
  git("config", "core.hooksPath", "/dev/null");

  const invoke = (command: string, args: string[]) => spawnSync(cli, [command, ...args], {
    cwd: root, env: environment, encoding: "utf8", timeout: 120_000,
  });
  const succeeds = (command: string, args: string[]) => {
    const result = invoke(command, args);
    expect(result.error).toBeUndefined();
    expect(result.status, result.stderr || result.stdout).toBe(0);
    return result;
  };
  const cataloguePath = join(directory, "catalogue.json");
  const lockPath = join(root, "tc-sdlc.lock");
  succeeds("catalogue", ["--input", candidateCatalogue, "--output", cataloguePath]);
  succeeds("lock", ["--declaration", declarationPath, "--catalogue", cataloguePath, "--output", lockPath]);
  git("add", ".");
  git("commit", "--quiet", "-m", "fixture inputs");
  const stateRoot = join(directory, "state");
  const bootstrapPath = join(directory, "bootstrap.json");
  const common = ["--declaration", declarationPath, "--catalogue", cataloguePath, "--lock", lockPath,
    "--root", root, "--state-root", stateRoot];
  succeeds("bootstrap", [...common, "--receipt", bootstrapPath]);
  const bootstrap = JSON.parse(readFileSync(bootstrapPath, "utf8"));
  expect(bootstrap).toMatchObject({ schema: "tc.sdlc/bootstrap-receipt/v1", status: "succeeded" });
  const before = inventory(root);

  const receiptPath = join(directory, "fitness.json");
  const result = succeeds("fitness", [...common, "--bootstrap-receipt", bootstrapPath, "--receipt", receiptPath]);
  expect(JSON.parse(result.stdout)).toMatchObject({ command: "fitness", status: "ok", receipt: receiptPath,
    receiptSchema: "tc.sdlc/fitness-receipt/v1" });
  const validate = new Ajv2020({ strict: true, allErrors: true }).compile(
    JSON.parse(readFileSync(join(schemas, "fitness-receipt-v1.schema.json"), "utf8")),
  );
  const receipt = JSON.parse(readFileSync(receiptPath, "utf8"));
  expect(validate(receipt), JSON.stringify(validate.errors)).toBe(true);
  const catalogue = JSON.parse(readFileSync(cataloguePath, "utf8"));
  const lock = JSON.parse(readFileSync(lockPath, "utf8"));
  const bindings = {
    declarationDigest: hash(canonical(declaration)), catalogueDigest: hash(canonical(catalogue)), lockDigest: hash(canonical(lock)),
  };
  expect(receipt).toMatchObject({
    schema: "tc.sdlc/fitness-receipt/v1", status: "succeeded", reason: null, ...bindings,
    task: { key: "tc-sdlc-python-consumer:fitness", identity: expect.stringMatching(/^sha256:[a-f0-9]{64}$/) },
    engine: { distribution: "three-cubes-fitness", expectedVersion: catalogue.release.fitness.version,
      observedVersion: catalogue.release.fitness.version, environmentDigest: expect.stringMatching(/^sha256:[a-f0-9]{64}$/) },
    config: { path: "pyproject.toml", digest: hash(readFileSync(join(root, "pyproject.toml"))) },
    profile: { name: "full", tier: "full" }, gateOutcome: "passed", exitCode: 0,
    runReceiptDigest: hash(readFileSync(`${receiptPath}.run`)),
  });
  const pythonDependency = bootstrap.dependencies.find((dependency: { manager: string }) => dependency.manager === "uv");
  expect(pythonDependency).toBeDefined();
  expect(receipt.engine.executableDigest).toBe(hash(readFileSync(join(stateRoot, bootstrap.stateKey, pythonDependency.environment, "bin", "tc-fitness"))));

  const run = JSON.parse(readFileSync(`${receiptPath}.run`, "utf8"));
  expect(run).toMatchObject({ schema: "tc.sdlc/run-receipt/v1", status: "succeeded", reason: null, scratchCleanup: "removed",
    declarationDigest: bindings.declarationDigest, lockDigest: bindings.lockDigest, selection: [receipt.task.identity],
    bootstrapContext: { bootstrapReceiptDigest: hash(readFileSync(bootstrapPath)), stateDigest: bootstrap.stateDigest,
      stateKey: bootstrap.stateKey, lockDigest: bindings.lockDigest, fitness: lock.fitness },
  });
  expect(run.scratchId).toMatch(/^tc-sdlc-run-[A-Za-z0-9]+$/);
  expect(existsSync(join(tmpdir(), run.scratchId))).toBe(false);
  expect(receipt.bootstrapContextDigest).toBe(hash(canonical(run.bootstrapContext)));
  expect(run.tasks).toHaveLength(1);
  const task = run.tasks[0];
  expect(task).toMatchObject({ ...receipt.task, status: "succeeded", exitCode: 0, reason: null,
    executionContextDigest: receipt.bootstrapContextDigest, missingEvidence: [] });
  expect(task.events.filter((event: { type: string }) => event.type === "start")).toHaveLength(1);
  expect(task.events.filter((event: { type: string }) => event.type === "terminal")).toHaveLength(1);
  expect(task.evidence).toHaveLength(1);
  expect(task.evidence[0]).toMatchObject({ path: "fitness.json", mediaType: "application/json" });
  const nested = JSON.parse(task.evidence[0].content);
  expect(validate(nested), JSON.stringify(validate.errors)).toBe(true);
  expect(receipt).toEqual({ ...nested, ...bindings, runReceiptDigest: hash(readFileSync(`${receiptPath}.run`)) });
  expect(inventory(root)).toEqual(before);
  expect(existsSync(join(root, "generated", "value.txt"))).toBe(false);

  // A direct invalid upstream input must still yield this component's own receipt.
  const malformedBootstrap = join(directory, "malformed-bootstrap.json");
  writeFileSync(malformedBootstrap, "{}\n");
  const failedPath = join(directory, "failed-fitness.json");
  const failed = invoke("fitness", [...common, "--bootstrap-receipt", malformedBootstrap, "--receipt", failedPath]);
  expect(failed.error).toBeUndefined();
  expect(failed.status).not.toBe(0);
  const failure = JSON.parse(readFileSync(failedPath, "utf8"));
  expect(validate(failure), JSON.stringify(validate.errors)).toBe(true);
  expect(failure).toMatchObject({ status: "failed", reason: "fitness_bootstrap_context_invalid", ...bindings,
    bootstrapContextDigest: null, task: { key: null, identity: null }, gateOutcome: "notRun", exitCode: null,
    runReceiptDigest: null, engine: { observedVersion: null, executableDigest: null, environmentDigest: null },
  });
  expect(existsSync(`${failedPath}.run`)).toBe(false);
  expect(inventory(root)).toEqual(before);
}, 180_000);
