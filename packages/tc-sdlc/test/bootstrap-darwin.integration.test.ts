import * as sdlc from "../dist/index.js";
import { bootstrapKernelBoundaryPort } from "../dist/bootstrap/kernel-boundary.js";
import { execFileSync, spawn, spawnSync } from "node:child_process";
import {
  chmodSync,
  cpSync,
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  realpathSync,
  renameSync,
  rmSync,
  statSync,
  symlinkSync,
  unlinkSync,
  utimesSync,
  writeFileSync,
} from "node:fs";
import { homedir, tmpdir } from "node:os";
import { createConnection, createServer } from "node:net";
import { dirname, join, posix } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, test } from "vitest";

const consumer = fileURLToPath(
  new URL("./fixtures/bootstrap-consumer", import.meta.url),
);
const workspaceConsumer = fileURLToPath(
  new URL("./fixtures/bootstrap-workspace", import.meta.url),
);
const CLI = fileURLToPath(new URL("../dist/cli.js", import.meta.url));
const PUBLIC_PACKAGE = new URL("../dist/index.js", import.meta.url).href;
const imageDigest =
  "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

function filesystemIdentity(path: string) {
  const details = statSync(path, { bigint: true });
  return {
    device: details.dev.toString(),
    inode: details.ino.toString(),
    birthtimeNanoseconds: details.birthtimeNs.toString(),
  };
}

function homebrewPrerequisitesAvailable(architecture: "arm64" | "x64"): boolean {
  const prefix = architecture === "arm64" ? "/opt/homebrew" : "/usr/local";
  return [
    "bin/brew",
    "opt/node@24/bin/node",
    "opt/python@3.13/libexec/bin/python3",
    "bin/uv",
  ].every((path) => existsSync(join(prefix, path)));
}

const unavailableDarwinArchitecture = (["arm64", "x64"] as const).find(
  (architecture) => !homebrewPrerequisitesAvailable(architecture),
);

function input(
  root: string,
  inputs = ["package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock"],
) {
  const declaration = sdlc.validateDeclaration({
    schema: "tc.sdlc/v1",
    project: "bootstrap-real-consumer",
    toolchains: sdlc.CANONICAL_SDLC_TOOLCHAINS,
    fitness: sdlc.CANONICAL_SDLC_FITNESS,
    projects: [{ name: "consumer", root: "." }],
    targets: {
      check: {
        command: "node --version",
        mode: "evaluate",
        trustBoundary: "portable",
        inputs,
      },
    },
  });
  const catalogue = sdlc.generateReleaseCatalogue({
    releaseVersion: "3.0.0",
    workflowCommit: "1234567890abcdef1234567890abcdef12345678",
    imageDigest,
  });
  return {
    root,
    declaration,
    catalogue,
    lock: sdlc.resolveLock(declaration, catalogue),
  };
}

function bootstrapReferenceStem(project: string, root: string): string {
  return sdlc.digest({ consumer: project, consumerRoot: realpathSync(root) })
    .slice("sha256:".length);
}

async function waitForPath(path: string, child: ReturnType<typeof spawn>): Promise<void> {
  const deadline = Date.now() + 60_000;
  while (!existsSync(path) && child.exitCode === null && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 2));
  }
  expect(existsSync(path)).toBe(true);
}

async function waitForPort(port: number, child: ReturnType<typeof spawn>): Promise<void> {
  const deadline = Date.now() + 60_000;
  while (child.exitCode === null && Date.now() < deadline) {
    const available = await new Promise<boolean>((resolve) => {
      const socket = createConnection({ host: "127.0.0.1", port });
      socket.once("connect", () => {
        socket.destroy();
        resolve(true);
      });
      socket.once("error", () => resolve(false));
    });
    if (available) return;
    await new Promise((resolve) => setTimeout(resolve, 2));
  }
  throw new Error(`deterministic bootstrap kernel boundary port ${port} was not observed`);
}

async function waitForRecoveryMarker(
  locksRoot: string,
  pid: number,
  child: ReturnType<typeof spawn>,
): Promise<string> {
  const deadline = Date.now() + 60_000;
  while (child.exitCode === null && Date.now() < deadline) {
    for (const name of readdirSync(locksRoot)) {
      if (!name.endsWith(".recovery")) continue;
      const path = join(locksRoot, name);
      try {
        if (JSON.parse(readFileSync(path, "utf8")).pid === pid) return path;
      } catch {
        // The owner is atomically publishing or removing the marker.
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 2));
  }
  throw new Error(`recovery marker for process ${pid} was not observed`);
}

async function waitForPendingReference(
  stateRoot: string,
  pid: number,
  child: ReturnType<typeof spawn>,
): Promise<string> {
  const pendingRoot = join(stateRoot, "references", "pending");
  const deadline = Date.now() + 60_000;
  while (child.exitCode === null && Date.now() < deadline) {
    for (const name of readdirSync(pendingRoot)) {
      const path = join(pendingRoot, name);
      try {
        if (JSON.parse(readFileSync(path, "utf8")).pid === pid) return path;
      } catch {
        // The pending reference is being atomically published or removed.
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 2));
  }
  throw new Error(`pending reference for process ${pid} was not observed`);
}

function childOutcome(child: ReturnType<typeof spawn>) {
  return new Promise<Readonly<{ status: number | null; stdout: string; stderr: string }>>(
    (resolve) => {
      let stdout = "";
      let stderr = "";
      child.stdout?.setEncoding("utf8");
      child.stderr?.setEncoding("utf8");
      child.stdout?.on("data", (value) => { stdout += value; });
      child.stderr?.on("data", (value) => { stderr += value; });
      child.once("exit", (status) => resolve({ status, stdout, stderr }));
    },
  );
}

function referenceFixture(prefix: string, stateParent = tmpdir()) {
  const root = mkdtempSync(join(tmpdir(), `${prefix}-consumer-`));
  const stateRoot = mkdtempSync(join(stateParent, `${prefix}-state-`));
  const evidence = mkdtempSync(join(tmpdir(), `${prefix}-evidence-`));
  writeFileSync(join(root, "input.txt"), "input\n");
  const catalogue = input(root, ["input.txt"]).catalogue;
  const project = prefix;
  const declarationFor = (generation: string) =>
    sdlc.validateDeclaration({
      schema: "tc.sdlc/v1",
      project,
      toolchains: sdlc.CANONICAL_SDLC_TOOLCHAINS,
      fitness: sdlc.CANONICAL_SDLC_FITNESS,
      projects: [{ name: "consumer", root: "." }],
      targets: {
        check: {
          command: `node -e 'process.stdout.write("${generation}")'`,
          mode: "evaluate",
          trustBoundary: "portable",
          inputs: ["input.txt"],
        },
      },
    });
  const optionsFor = (generation: string, receipt = `${generation}.json`) => {
    const declaration = declarationFor(generation);
    return {
      root,
      declaration,
      catalogue,
      lock: sdlc.resolveLock(declaration, catalogue),
      stateRoot,
      receiptPath: join(evidence, receipt),
      host: { platform: "darwin" as const, architecture: process.arch, offline: false },
    };
  };
  const stem = bootstrapReferenceStem(project, root);
  const runner = join(evidence, "bootstrap-child.mjs");
  writeFileSync(
    runner,
    `import {readFileSync} from "node:fs"; import * as sdlc from ${JSON.stringify(PUBLIC_PACKAGE)}; const receipt=await sdlc.bootstrap(JSON.parse(readFileSync(process.argv[2], "utf8"))); process.stdout.write(JSON.stringify(receipt));\n`,
  );
  const maintenanceRunner = join(evidence, "maintenance-child.mjs");
  writeFileSync(
    maintenanceRunner,
    `import {readFileSync,writeFileSync} from "node:fs"; import * as sdlc from ${JSON.stringify(PUBLIC_PACKAGE)}; writeFileSync(process.argv[3], "started"); const receipt=await sdlc.maintain(JSON.parse(readFileSync(process.argv[2], "utf8"))); process.stdout.write(JSON.stringify(receipt));\n`,
  );
  const spawnBootstrap = (
    generation: string,
    stateRootOverride = stateRoot,
    receipt = `${generation}.json`,
  ) => {
    const optionsPath = join(evidence, `${generation}-${receipt}-options.json`);
    writeFileSync(optionsPath, JSON.stringify({
      ...optionsFor(generation, receipt),
      stateRoot: stateRootOverride,
    }));
    const child = spawn(process.execPath, [runner, optionsPath], {
      stdio: ["ignore", "pipe", "pipe"],
    });
    return { child, outcome: childOutcome(child) };
  };
  const spawnMaintenance = (name: string) => {
    const optionsPath = join(evidence, `${name}-maintenance-options.json`);
    const startedPath = join(evidence, `${name}-maintenance-started`);
    writeFileSync(optionsPath, JSON.stringify({
      stateRoot,
      temporaryRoot: mkdtempSync(join(tmpdir(), `${prefix}-maintenance-temp-`)),
      receiptPath: join(evidence, `${name}-maintenance.json`),
      mode: "apply",
    }));
    const child = spawn(process.execPath, [maintenanceRunner, optionsPath, startedPath], {
      stdio: ["ignore", "pipe", "pipe"],
    });
    return { child, outcome: childOutcome(child), startedPath };
  };
  return {
    root,
    stateRoot,
    evidence,
    project,
    optionsFor,
    spawnBootstrap,
    spawnMaintenance,
    referencePath: join(stateRoot, "references", `${stem}.json`),
    lockPath: join(stateRoot, "references", "locks", `${stem}.lock`),
  };
}

describe("reviewed macOS bootstrap host and dependency boundary", () => {
  test("public CLI rebuilds a poisoned generation at the same state key before succeeding", async () => {
    expect(process.platform).toBe("darwin");
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-generation-rebuild-consumer-"));
    const stateRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-generation-rebuild-state-"));
    const evidence = mkdtempSync(join(tmpdir(), "tc-sdlc-generation-rebuild-evidence-"));
    const ready = join(evidence, "check-ready");
    const release = join(evidence, "check-release");
    const downstreamSentinel = join(evidence, "downstream-ran");
    for (const name of ["package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock"]) {
      writeFileSync(join(root, name), readFileSync(join(consumer, name)));
    }
    writeFileSync(join(root, "input.txt"), "input\n");
    writeFileSync(
      join(root, "check.mjs"),
      `import { existsSync, writeFileSync } from "node:fs";\n` +
        `const ready = process.argv[2];\n` +
        `const release = process.argv[3];\n` +
        `if (!existsSync(ready)) {\n` +
        `  writeFileSync(ready, "ready\\n");\n` +
        `  if (Object.hasOwn(process.env, "TC_SDLC_BOOTSTRAP_STATE_ROOT")) process.exit(78);\n` +
        `  while (!existsSync(release)) await new Promise((resolve) => setTimeout(resolve, 5));\n` +
        `}\n`,
    );
    writeFileSync(
      join(root, "downstream.mjs"),
      `import { writeFileSync } from "node:fs";\n` +
        `writeFileSync(process.argv[2], "downstream ran\\n");\n`,
    );
    execFileSync("git", ["init", "-q"], { cwd: root });
    execFileSync("git", ["config", "user.name", "Fixture"], { cwd: root });
    execFileSync("git", ["config", "user.email", "fixture@example.invalid"], { cwd: root });
    execFileSync("git", ["add", "."], { cwd: root });
    execFileSync("git", ["commit", "-qm", "consumer fixture"], { cwd: root });

    const catalogue = input(root, ["input.txt"]).catalogue;
    const declaration = sdlc.validateDeclaration({
      schema: "tc.sdlc/v1",
      project: "bootstrap-state-generation-rebuild",
      toolchains: sdlc.CANONICAL_SDLC_TOOLCHAINS,
      fitness: sdlc.CANONICAL_SDLC_FITNESS,
      projects: [{ name: "consumer", root: "." }],
      targets: {
        prepare: {
          command: "node --version",
          mode: "prepare",
          trustBoundary: "portable",
          inputs: ["input.txt"],
        },
        check: {
          command: `node check.mjs ${JSON.stringify(ready)} ${JSON.stringify(release)}`,
          mode: "evaluate",
          trustBoundary: "portable",
          inputs: ["input.txt", "check.mjs"],
        },
        downstream: {
          command: `node downstream.mjs ${JSON.stringify(downstreamSentinel)}`,
          mode: "evaluate",
          trustBoundary: "portable",
          dependsOn: ["check"],
          inputs: ["input.txt", "downstream.mjs"],
        },
      },
    });
    const lock = sdlc.resolveLock(declaration, catalogue);
    const declarationPath = join(evidence, "declaration.json");
    const cataloguePath = join(evidence, "catalogue.json");
    const lockPath = join(evidence, "lock.json");
    writeFileSync(declarationPath, sdlc.canonicalJson(declaration));
    writeFileSync(cataloguePath, sdlc.canonicalJson(catalogue));
    writeFileSync(lockPath, sdlc.canonicalJson(lock));
    const publicArgsFor = (consumerRoot = root) => [
      "--declaration", declarationPath,
      "--catalogue", cataloguePath,
      "--lock", lockPath,
      "--root", consumerRoot,
      "--state-root", stateRoot,
    ];
    const invoke = (
      command: string,
      args: readonly string[],
      consumerRoot = root,
    ) => spawnSync(
      process.execPath,
      [CLI, command, ...publicArgsFor(consumerRoot), ...args],
      { encoding: "utf8" },
    );
    const bootstrap = (name: string) => {
      const receiptPath = join(evidence, `${name}-bootstrap.json`);
      const result = invoke("bootstrap", ["--receipt", receiptPath]);
      expect(result.status, result.stderr).toBe(0);
      return { receiptPath, receipt: JSON.parse(readFileSync(receiptPath, "utf8")) };
    };
    const prepare = (name: string, bootstrapReceipt: string) => {
      const receiptPath = join(evidence, `${name}-prepare.json`);
      const result = invoke("prepare", [
        "--bootstrap-receipt", bootstrapReceipt,
        "--receipt", receiptPath,
      ]);
      expect(result.status, result.stderr).toBe(0);
      return receiptPath;
    };
    const check = (
      name: string,
      bootstrapReceipt: string,
      preparationReceipt: string,
    ) => {
      const receiptPath = join(evidence, `${name}-evaluation.json`);
      const result = invoke("check", [
        "--bootstrap-receipt", bootstrapReceipt,
        "--receipt", receiptPath,
        "--changed", "input.txt",
        "--environment", "native-darwin",
        "--producer", "f6-generation-rebuild-test",
        "--preparation-receipt", preparationReceipt,
      ]);
      return { result, receiptPath };
    };

    const initial = bootstrap("initial");
    expect(initial.receipt.status).toBe("succeeded");
    const secondRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-generation-rebuild-second-consumer-"));
    cpSync(root, secondRoot, { recursive: true });
    const secondBootstrapPath = join(evidence, "second-consumer-bootstrap.json");
    const secondBootstrapResult = invoke(
      "bootstrap",
      ["--receipt", secondBootstrapPath],
      secondRoot,
    );
    expect(secondBootstrapResult.status, secondBootstrapResult.stderr).toBe(0);
    const secondBootstrap = JSON.parse(readFileSync(secondBootstrapPath, "utf8"));
    expect(secondBootstrap).toMatchObject({
      status: "succeeded",
      reused: true,
      stateKey: initial.receipt.stateKey,
    });
    const secondReferencePath = join(
      stateRoot,
      "references",
      `${bootstrapReferenceStem(declaration.project, secondRoot)}.json`,
    );
    const secondReferenceBeforeRebuild = JSON.parse(readFileSync(secondReferencePath, "utf8"));
    expect(secondReferenceBeforeRebuild.currentStateKey).toBe(initial.receipt.stateKey);
    const poisonedPath = join(stateRoot, initial.receipt.stateKey);
    const poisonedIdentity = filesystemIdentity(poisonedPath);
    expect(secondReferenceBeforeRebuild.currentStateIdentity).toMatchObject({
      device: poisonedIdentity.device,
      inode: poisonedIdentity.inode,
    });
    const undeclaredMember = join(poisonedPath, "foreign-cache.json");
    writeFileSync(undeclaredMember, "not declared by bootstrap state\n");
    const rejectedPreparationPath = join(evidence, "undeclared-state-prepare.json");
    const rejectedPreparation = invoke("prepare", [
      "--bootstrap-receipt", initial.receiptPath,
      "--receipt", rejectedPreparationPath,
    ]);
    expect(rejectedPreparation.status).not.toBe(0);
    expect(existsSync(rejectedPreparationPath)).toBe(false);
    rmSync(undeclaredMember);

    const uvDependency = initial.receipt.dependencies.find(
      (dependency: Record<string, string>) => dependency.manager === "uv",
    );
    expect(uvDependency).toBeDefined();
    const firstPythonSource = (directory: string): string | undefined => {
      for (const entry of readdirSync(directory, { withFileTypes: true }).sort(
        (left, right) => left.name.localeCompare(right.name),
      )) {
        if (entry.isSymbolicLink()) continue;
        const path = join(directory, entry.name);
        if (entry.isDirectory()) {
          const nested = firstPythonSource(path);
          if (nested !== undefined) return nested;
        } else if (entry.isFile() && entry.name.endsWith(".py")) {
          return path;
        }
      }
      return undefined;
    };
    const mutatedStateFile = firstPythonSource(join(poisonedPath, uvDependency!.environment));
    expect(mutatedStateFile).toBeDefined();
    const initialPreparation = prepare("initial", initial.receiptPath);
    const poisonedEvaluationPath = join(evidence, "poisoned-evaluation.json");
    const poisonedChild = spawn(process.execPath, [
      CLI,
      "check",
      ...publicArgsFor(),
      "--bootstrap-receipt", initial.receiptPath,
      "--receipt", poisonedEvaluationPath,
      "--changed", "input.txt",
      "--environment", "native-darwin",
      "--producer", "f6-generation-rebuild-test",
      "--preparation-receipt", initialPreparation,
    ], { stdio: ["ignore", "pipe", "pipe"] });
    const poisonedOutcome = childOutcome(poisonedChild);
    await waitForPath(ready, poisonedChild);
    writeFileSync(mutatedStateFile!, Buffer.concat([
      readFileSync(mutatedStateFile!),
      Buffer.from("\n# external integrity sabotage\n"),
    ]));
    writeFileSync(release, "continue\n");
    const poisonedResult = await poisonedOutcome;
    const poisoned = { result: poisonedResult, receiptPath: poisonedEvaluationPath };
    expect(poisoned.result.status).not.toBe(0);
    const poisonedEvaluation = JSON.parse(readFileSync(poisoned.receiptPath, "utf8"));
    expect(poisonedEvaluation).toMatchObject({ status: "failed" });
    expect(poisonedEvaluation.scheduler).toMatchObject({
      status: "failed",
      reason: "bootstrap_state_changed",
      scratchCleanup: "removed",
    });
    expect(poisonedEvaluation.scheduler.tasks.some(
      (task: Record<string, unknown>) => task.reason === "bootstrap_state_changed",
    )).toBe(true);
    expect(existsSync(downstreamSentinel)).toBe(true);
    expect(poisonedEvaluation.scheduler.tasks.flatMap(
      (task: { events: readonly Record<string, unknown>[] }) => task.events,
    ).filter((event: Record<string, unknown>) => event.type === "terminal").every(
      (event: Record<string, unknown>) => event.status !== "succeeded",
    )).toBe(true);

    const rebuilt = bootstrap("rebuilt");
    expect(rebuilt.receipt).toMatchObject({
      status: "succeeded",
      reused: false,
      stateKey: initial.receipt.stateKey,
    });
    const rebuiltIdentity = filesystemIdentity(poisonedPath);
    expect(rebuiltIdentity.device).toBe(poisonedIdentity.device);
    expect(rebuiltIdentity.inode).not.toBe(poisonedIdentity.inode);
    expect(readdirSync(join(stateRoot, "invalidated")).length).toBeGreaterThan(0);
    const rebuiltPreparation = prepare("rebuilt", rebuilt.receiptPath);
    const recovered = check("recovered", rebuilt.receiptPath, rebuiltPreparation);
    expect(recovered.result.status, recovered.result.stderr).toBe(0);
    expect(JSON.parse(readFileSync(recovered.receiptPath, "utf8"))).toMatchObject({
      status: "succeeded",
      scheduler: { status: "succeeded", scratchCleanup: "removed" },
    });
    expect(existsSync(downstreamSentinel)).toBe(true);

    const stateParent = dirname(poisonedPath);
    const quarantineName = readdirSync(stateParent).find((name) =>
      name.startsWith(".tc-sdlc-quarantine-"),
    );
    expect(quarantineName).toBeDefined();
    const quarantineRoot = join(stateParent, quarantineName!);
    const quarantinePayload = join(quarantineRoot, "candidate");
    expect(existsSync(quarantinePayload)).toBe(true);
    const quarantineMarker = JSON.parse(
      readFileSync(join(quarantineRoot, ".tc-sdlc-quarantine.json"), "utf8"),
    );
    expect(quarantineMarker.payloadIdentity).toMatchObject({
      device: poisonedIdentity.device,
      inode: poisonedIdentity.inode,
    });
    const invalidationStem = `${sdlc.digest(initial.receipt.stateKey).slice("sha256:".length)}.`;
    const tombstoneName = readdirSync(join(stateRoot, "invalidated")).find((name) =>
      name.startsWith(invalidationStem),
    );
    expect(tombstoneName).toBeDefined();
    const tombstonePath = join(stateRoot, "invalidated", tombstoneName!);
    expect(JSON.parse(readFileSync(tombstonePath, "utf8"))).toMatchObject({
      stateKey: initial.receipt.stateKey,
    });
    const quarantineRelativePath = posix.relative(stateRoot, quarantineRoot);
    const rebuiltIdentityBeforeMaintenance = filesystemIdentity(poisonedPath);
    const maintenanceTemporaryRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-generation-rebuild-maintenance-"));
    const beforeCutoff = await sdlc.maintain({
      stateRoot,
      temporaryRoot: maintenanceTemporaryRoot,
      receiptPath: join(evidence, "maintenance-before-quarantine-cutoff.json"),
      mode: "apply",
    });
    expect(beforeCutoff.status).toBe("succeeded");
    expect(beforeCutoff.retained).toContainEqual({
      path: quarantineRelativePath,
      reason: "retention_window",
    });
    expect(existsSync(quarantinePayload)).toBe(true);
    expect(existsSync(tombstonePath)).toBe(true);
    expect(filesystemIdentity(poisonedPath)).toEqual(rebuiltIdentityBeforeMaintenance);
    expect(JSON.parse(readFileSync(secondReferencePath, "utf8")).currentStateIdentity).toMatchObject({
      device: poisonedIdentity.device,
      inode: poisonedIdentity.inode,
    });

    const expired = new Date(Date.now() - 49 * 60 * 60 * 1_000);
    utimesSync(quarantineRoot, expired, expired);
    const atCutoff = await sdlc.maintain({
      stateRoot,
      temporaryRoot: maintenanceTemporaryRoot,
      receiptPath: join(evidence, "maintenance-after-quarantine-cutoff.json"),
      mode: "apply",
    });
    expect(atCutoff.status).toBe("succeeded");
    expect(atCutoff.removedCount).toBeGreaterThan(0);
    expect(existsSync(quarantineRoot)).toBe(false);
    expect(existsSync(tombstonePath)).toBe(false);
    expect(existsSync(poisonedPath)).toBe(true);
    expect(filesystemIdentity(poisonedPath)).toEqual(rebuiltIdentityBeforeMaintenance);
    const firstReferenceAfterMaintenance = JSON.parse(readFileSync(
      join(
        stateRoot,
        "references",
        `${bootstrapReferenceStem(declaration.project, root)}.json`,
      ),
      "utf8",
    ));
    expect(firstReferenceAfterMaintenance.currentStateIdentity).toMatchObject({
      device: rebuiltIdentityBeforeMaintenance.device,
      inode: rebuiltIdentityBeforeMaintenance.inode,
    });

    const secondRecoveryPath = join(evidence, "second-consumer-recovered-bootstrap.json");
    const secondRecovery = invoke(
      "bootstrap",
      ["--receipt", secondRecoveryPath],
      secondRoot,
    );
    expect(secondRecovery.status, secondRecovery.stderr).toBe(0);
    expect(JSON.parse(readFileSync(secondRecoveryPath, "utf8"))).toMatchObject({
      status: "succeeded",
      reused: true,
      stateKey: initial.receipt.stateKey,
    });
    expect(JSON.parse(readFileSync(secondReferencePath, "utf8")).currentStateIdentity).toMatchObject({
      device: rebuiltIdentityBeforeMaintenance.device,
      inode: rebuiltIdentityBeforeMaintenance.inode,
    });
  }, 180_000);

  test("a killed cold bootstrap releases the kernel boundary and the next bootstrap recovers", async () => {
    expect(process.platform).toBe("darwin");
    const fixture = referenceFixture("bootstrap-state-killed-owner");
    writeFileSync(
      join(fixture.stateRoot, ".tc-sdlc-owner.json"),
      sdlc.canonicalJson({
        schema: "tc.sdlc/state-owner/v1",
        owner: "@three-cubes/tc-sdlc",
      }),
    );
    const options = fixture.optionsFor("crash-recovery", "after-crash.json");
    const dependencyDigest = sdlc.digest([]);
    const stateKey = posix.join(
      "releases",
      sdlc.digest(options.lock).slice("sha256:".length),
      dependencyDigest.slice("sha256:".length),
      `darwin-${process.arch}`,
    );
    const port = bootstrapKernelBoundaryPort(
      fixture.stateRoot,
      "bootstrap-state-materialization",
      { stateKey },
    );
    const crashed = fixture.spawnBootstrap("crash-recovery");
    await waitForPort(port, crashed.child);
    expect(crashed.child.kill("SIGKILL")).toBe(true);
    const outcome = await crashed.outcome;
    expect(outcome.status).toBeNull();

    const recovered = await sdlc.bootstrap(fixture.optionsFor("crash-recovery", "recovered.json"));
    expect(recovered.status, JSON.stringify(recovered)).toBe("succeeded");
    expect(recovered.stateKey).toBe(stateKey);
    expect(existsSync(join(fixture.stateRoot, stateKey, "state.json"))).toBe(true);
  }, 180_000);

  test("fails closed when an unrelated process occupies the public state boundary port", async () => {
    expect(process.platform).toBe("darwin");
    const fixture = referenceFixture("bootstrap-state-port-collision");
    const options = fixture.optionsFor("collision", "collision.json");
    const stateKey = posix.join(
      "releases",
      sdlc.digest(options.lock).slice("sha256:".length),
      sdlc.digest([]).slice("sha256:".length),
      `darwin-${process.arch}`,
    );
    const port = bootstrapKernelBoundaryPort(
      fixture.stateRoot,
      "bootstrap-state-materialization",
      { stateKey },
    );
    const listener = createServer();
    await new Promise<void>((resolve, reject) => {
      listener.once("error", reject);
      listener.listen({ host: "127.0.0.1", port, exclusive: true }, () => resolve());
    });
    try {
      const receipt = await sdlc.bootstrap(options);
      expect(receipt).toMatchObject({
        status: "failed",
        reason: "state_materialization_busy",
        diagnostics: [{ code: "BOOTSTRAP_STATE_MATERIALIZATION_BUSY" }],
      });
      expect(existsSync(join(fixture.stateRoot, stateKey))).toBe(false);
    } finally {
      await new Promise<void>((resolve, reject) => {
        listener.close((error) => error === undefined ? resolve() : reject(error));
      });
    }
  }, 30_000);

  test("serialises separate cold bootstraps for the same state key", async () => {
    expect(process.platform).toBe("darwin");
    const fixture = referenceFixture("bootstrap-state-materialisation-race");
    const first = fixture.spawnBootstrap("same", fixture.stateRoot, "same-first.json");
    const second = fixture.spawnBootstrap("same", fixture.stateRoot, "same-second.json");
    const [firstResult, secondResult] = await Promise.all([first.outcome, second.outcome]);
    expect(firstResult.status, firstResult.stderr).toBe(0);
    expect(secondResult.status, secondResult.stderr).toBe(0);
    const receipts = [JSON.parse(firstResult.stdout), JSON.parse(secondResult.stdout)];
    expect(
      receipts.every((receipt) => receipt.status === "succeeded"),
      JSON.stringify({ receipts, stderr: [firstResult.stderr, secondResult.stderr] }),
    ).toBe(true);
    expect(new Set(receipts.map((receipt) => receipt.stateKey)).size).toBe(1);
    expect(receipts.map((receipt) => receipt.reused).sort()).toEqual([false, true]);
    const statePath = join(fixture.stateRoot, receipts[0].stateKey, "state.json");
    expect(existsSync(statePath)).toBe(true);
    expect(JSON.parse(readFileSync(statePath, "utf8")).schema)
      .toBe("tc.sdlc/bootstrap-state/v6");
  }, 180_000);

  test("serialises concurrent commits for one consumer without losing either successful state", async () => {
    expect(process.platform).toBe("darwin");
    const fixture = referenceFixture("bootstrap-reference-commit");
    const initial = await sdlc.bootstrap(fixture.optionsFor("A"));
    expect(initial.status).toBe("succeeded");
    const transitionB = fixture.spawnBootstrap("B");
    await waitForPath(fixture.lockPath, transitionB.child);
    expect(transitionB.child.kill("SIGSTOP")).toBe(true);

    const transitionC = fixture.spawnBootstrap("C");
    const cFinishedBeforeRelease = await Promise.race([
      transitionC.outcome.then(() => true),
      new Promise<false>((resolve) => setTimeout(() => resolve(false), 500)),
    ]);
    expect(cFinishedBeforeRelease).toBe(false);
    expect(transitionB.child.kill("SIGCONT")).toBe(true);
    const [resultB, resultC] = await Promise.all([
      transitionB.outcome,
      transitionC.outcome,
    ]);
    expect(resultB.status, resultB.stderr).toBe(0);
    expect(resultC.status, resultC.stderr).toBe(0);
    const receiptB = JSON.parse(resultB.stdout);
    const receiptC = JSON.parse(resultC.stdout);
    expect(receiptB).toMatchObject({ status: "succeeded" });
    expect(receiptC).toMatchObject({ status: "succeeded" });
    const reference = JSON.parse(readFileSync(fixture.referencePath, "utf8"));
    expect(new Set([reference.currentStateKey, reference.predecessorStateKey])).toEqual(
      new Set([receiptB.stateKey, receiptC.stateKey]),
    );
  }, 180_000);

  test("serialises two stale-lock recoverers with a crash-released OS boundary", async () => {
    expect(process.platform).toBe("darwin");
    const fixture = referenceFixture("bootstrap-reference-recovery-race");
    expect(await sdlc.bootstrap(fixture.optionsFor("A"))).toMatchObject({ status: "succeeded" });
    const staleOwner = fixture.spawnBootstrap("B");
    await waitForPath(fixture.lockPath, staleOwner.child);
    expect(staleOwner.child.kill("SIGKILL")).toBe(true);
    await staleOwner.outcome;

    const first = fixture.spawnBootstrap("C");
    const recoveryMarker = await waitForRecoveryMarker(
      dirname(fixture.lockPath),
      first.child.pid!,
      first.child,
    );
    expect(first.child.kill("SIGSTOP")).toBe(true);
    expect(existsSync(recoveryMarker)).toBe(true);
    const second = fixture.spawnBootstrap("D");
    await waitForPendingReference(fixture.stateRoot, second.child.pid!, second.child);
    expect(second.child.exitCode).toBeNull();
    expect(existsSync(recoveryMarker)).toBe(true);
    expect(first.child.kill("SIGCONT")).toBe(true);
    const [firstResult, secondResult] = await Promise.all([first.outcome, second.outcome]);
    expect(firstResult.status, firstResult.stderr).toBe(0);
    expect(secondResult.status, secondResult.stderr).toBe(0);
    const firstReceipt = JSON.parse(firstResult.stdout);
    const secondReceipt = JSON.parse(secondResult.stdout);
    expect(firstReceipt).toMatchObject({ status: "succeeded" });
    expect(secondReceipt).toMatchObject({ status: "succeeded" });
    const reference = JSON.parse(readFileSync(fixture.referencePath, "utf8"));
    expect(new Set([reference.currentStateKey, reference.predecessorStateKey])).toEqual(
      new Set([firstReceipt.stateKey, secondReceipt.stateKey]),
    );
  }, 60_000);

  test("serialises stale-lock recovery against maintenance cleanup", async () => {
    expect(process.platform).toBe("darwin");
    const fixture = referenceFixture("bootstrap-reference-maintenance-race");
    expect(await sdlc.bootstrap(fixture.optionsFor("A"))).toMatchObject({ status: "succeeded" });
    const staleOwner = fixture.spawnBootstrap("B");
    await waitForPath(fixture.lockPath, staleOwner.child);
    expect(staleOwner.child.kill("SIGKILL")).toBe(true);
    await staleOwner.outcome;
    const locksRoot = dirname(fixture.lockPath);
    const staleMarker = join(
      locksRoot,
      readdirSync(locksRoot).find((name) => name.endsWith(".marker"))!,
    );
    const old = new Date(Date.now() - 49 * 60 * 60 * 1_000);
    utimesSync(fixture.lockPath, old, old);
    utimesSync(staleMarker, old, old);

    const recovery = fixture.spawnBootstrap("C");
    const recoveryMarker = await waitForRecoveryMarker(
      locksRoot,
      recovery.child.pid!,
      recovery.child,
    );
    expect(recovery.child.kill("SIGSTOP")).toBe(true);
    expect(existsSync(recoveryMarker)).toBe(true);
    const maintenance = fixture.spawnMaintenance("contended");
    await waitForPath(maintenance.startedPath, maintenance.child);
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(maintenance.child.exitCode).toBeNull();
    expect(existsSync(recoveryMarker)).toBe(true);
    expect(recovery.child.kill("SIGCONT")).toBe(true);
    const [recoveryResult, maintenanceResult] = await Promise.all([
      recovery.outcome,
      maintenance.outcome,
    ]);
    expect(recoveryResult.status, recoveryResult.stderr).toBe(0);
    expect(JSON.parse(recoveryResult.stdout)).toMatchObject({ status: "succeeded" });
    expect(maintenanceResult.status, maintenanceResult.stderr).toBe(0);
    expect(JSON.parse(maintenanceResult.stdout)).toMatchObject({ status: "succeeded" });
    const reference = JSON.parse(readFileSync(fixture.referencePath, "utf8"));
    expect(existsSync(join(fixture.stateRoot, reference.currentStateKey, "state.json"))).toBe(true);
  }, 60_000);

  test("serialises stale recovery through lexical aliases of one state root", async () => {
    expect(process.platform).toBe("darwin");
    const fixture = referenceFixture("bootstrap-reference-alias-race", "/private/tmp");
    const aliasStateRoot = fixture.stateRoot.replace(/^\/private/, "");
    expect(aliasStateRoot).not.toBe(fixture.stateRoot);
    expect(realpathSync(aliasStateRoot)).toBe(realpathSync(fixture.stateRoot));
    expect(await sdlc.bootstrap(fixture.optionsFor("A"))).toMatchObject({ status: "succeeded" });
    const staleOwner = fixture.spawnBootstrap("B");
    await waitForPath(fixture.lockPath, staleOwner.child);
    expect(staleOwner.child.kill("SIGKILL")).toBe(true);
    await staleOwner.outcome;

    const first = fixture.spawnBootstrap("C");
    const recoveryMarker = await waitForRecoveryMarker(
      dirname(fixture.lockPath),
      first.child.pid!,
      first.child,
    );
    expect(first.child.kill("SIGSTOP")).toBe(true);
    let resumed = false;
    const second = fixture.spawnBootstrap("D", aliasStateRoot);
    try {
      await waitForPendingReference(fixture.stateRoot, second.child.pid!, second.child);
      const escapedCanonicalBoundary = await Promise.race([
        waitForRecoveryMarker(dirname(fixture.lockPath), second.child.pid!, second.child)
          .then(() => true),
        second.outcome.then(() => true),
        new Promise<false>((resolve) => setTimeout(() => resolve(false), 500)),
      ]);
      expect(escapedCanonicalBoundary).toBe(false);
      expect(first.child.exitCode).toBeNull();
      expect(existsSync(recoveryMarker)).toBe(true);
    } finally {
      if (first.child.exitCode === null) first.child.kill("SIGCONT");
      resumed = true;
    }
    expect(resumed).toBe(true);
    const [firstResult, secondResult] = await Promise.all([first.outcome, second.outcome]);
    expect(firstResult.status, firstResult.stderr).toBe(0);
    expect(secondResult.status, secondResult.stderr).toBe(0);
    expect(JSON.parse(firstResult.stdout)).toMatchObject({ status: "succeeded" });
    expect(JSON.parse(secondResult.stdout)).toMatchObject({ status: "succeeded" });
  }, 60_000);

  test("destroys accepted recovery clients so a completed bootstrap child exits", async () => {
    expect(process.platform).toBe("darwin");
    const fixture = referenceFixture("bootstrap-reference-accepted-client", "/private/tmp");
    expect(await sdlc.bootstrap(fixture.optionsFor("A"))).toMatchObject({ status: "succeeded" });
    const staleOwner = fixture.spawnBootstrap("B");
    await waitForPath(fixture.lockPath, staleOwner.child);
    expect(staleOwner.child.kill("SIGKILL")).toBe(true);
    await staleOwner.outcome;
    const locksRoot = dirname(fixture.lockPath);
    const liveMarkerPath = join(
      locksRoot,
      readdirSync(locksRoot).find((name) => name.endsWith(".marker"))!,
    );
    const liveMarker = JSON.parse(readFileSync(fixture.lockPath, "utf8"));
    const started = execFileSync(
      "/bin/ps",
      ["-p", `${process.pid}`, "-o", "lstart="],
      { encoding: "utf8", env: { LC_ALL: "C", PATH: "/usr/bin:/bin" } },
    ).trim();
    liveMarker.pid = process.pid;
    liveMarker.processStartIdentity = `darwin:${Math.floor(Date.parse(started) / 1_000)}`;
    writeFileSync(fixture.lockPath, sdlc.canonicalJson(liveMarker));

    const transition = fixture.spawnBootstrap("C");
    const markerPath = await waitForRecoveryMarker(
      locksRoot,
      transition.child.pid!,
      transition.child,
    );
    const port = JSON.parse(readFileSync(markerPath, "utf8")).port as number;
    const client = createConnection({ host: "127.0.0.1", port });
    const peerClosed = new Promise<true>((resolve) => client.once("close", () => resolve(true)));
    await new Promise<void>((resolve, reject) => {
      client.once("connect", resolve);
      client.once("error", reject);
    });
    try {
      const rejected = await Promise.race([
        peerClosed,
        new Promise<false>((resolve) => setTimeout(() => resolve(false), 15_000)),
      ]);
      expect(rejected).toBe(true);
      expect(transition.child.exitCode).toBeNull();
      unlinkSync(fixture.lockPath);
      unlinkSync(liveMarkerPath);
      const result = await Promise.race([
        transition.outcome,
        new Promise<false>((resolve) => setTimeout(() => resolve(false), 15_000)),
      ]);
      expect(result).not.toBe(false);
      if (result !== false) {
        expect(result.status, result.stderr).toBe(0);
        expect(JSON.parse(result.stdout)).toMatchObject({ status: "succeeded" });
      }
    } finally {
      client.destroy();
      if (existsSync(fixture.lockPath)) unlinkSync(fixture.lockPath);
      if (existsSync(liveMarkerPath)) unlinkSync(liveMarkerPath);
      if (transition.child.exitCode === null) transition.child.kill("SIGKILL");
    }
  }, 60_000);

  test("recovers an exact commit lock whose owner was killed", async () => {
    expect(process.platform).toBe("darwin");
    const fixture = referenceFixture("bootstrap-reference-killed-owner");
    expect(await sdlc.bootstrap(fixture.optionsFor("A"))).toMatchObject({ status: "succeeded" });
    const { child, outcome } = fixture.spawnBootstrap("B");
    await waitForPath(fixture.lockPath, child);
    expect(child.kill("SIGKILL")).toBe(true);
    await outcome;

    const recoveredC = fixture.spawnBootstrap("C");
    const recoveredD = fixture.spawnBootstrap("D");
    const [outcomeC, outcomeD] = await Promise.all([
      recoveredC.outcome,
      recoveredD.outcome,
    ]);
    expect(outcomeC.status, outcomeC.stderr).toBe(0);
    expect(outcomeD.status, outcomeD.stderr).toBe(0);
    const receiptC = JSON.parse(outcomeC.stdout);
    const receiptD = JSON.parse(outcomeD.stdout);
    expect(receiptC).toMatchObject({ status: "succeeded" });
    expect(receiptD).toMatchObject({ status: "succeeded" });
    expect(existsSync(fixture.lockPath)).toBe(false);
    const reference = JSON.parse(readFileSync(fixture.referencePath, "utf8"));
    expect(new Set([reference.currentStateKey, reference.predecessorStateKey])).toEqual(
      new Set([receiptC.stateKey, receiptD.stateKey]),
    );

    const interrupted = fixture.spawnBootstrap("E");
    await waitForPath(fixture.lockPath, interrupted.child);
    expect(interrupted.child.kill("SIGKILL")).toBe(true);
    await interrupted.outcome;
    const locksRoot = dirname(fixture.lockPath);
    const markerPath = join(
      locksRoot,
      readdirSync(locksRoot).find((name) => name.endsWith(".marker"))!,
    );
    const old = new Date(Date.now() - 49 * 60 * 60 * 1_000);
    utimesSync(fixture.lockPath, old, old);
    utimesSync(markerPath, old, old);
    const maintained = await sdlc.maintain({
      stateRoot: fixture.stateRoot,
      temporaryRoot: mkdtempSync(join(tmpdir(), "tc-sdlc-reference-lock-maintenance-")),
      receiptPath: join(fixture.evidence, "maintenance.json"),
      mode: "apply",
    });
    expect(maintained).toMatchObject({
      status: "succeeded",
      referenceMetadataRemovedCount: 1,
    });
    expect(existsSync(fixture.lockPath)).toBe(false);
    expect(existsSync(markerPath)).toBe(false);

    const beforeLinkCrash = fixture.spawnBootstrap("F");
    await waitForPath(fixture.lockPath, beforeLinkCrash.child);
    expect(beforeLinkCrash.child.kill("SIGKILL")).toBe(true);
    await beforeLinkCrash.outcome;
    rmSync(fixture.lockPath);
    const orphanMarker = join(
      locksRoot,
      readdirSync(locksRoot).find((name) => name.endsWith(".marker"))!,
    );
    utimesSync(orphanMarker, old, old);
    const orphanCleanup = await sdlc.maintain({
      stateRoot: fixture.stateRoot,
      temporaryRoot: mkdtempSync(join(tmpdir(), "tc-sdlc-reference-marker-maintenance-")),
      receiptPath: join(fixture.evidence, "orphan-maintenance.json"),
      mode: "apply",
    });
    expect(orphanCleanup).toMatchObject({
      status: "succeeded",
      referenceMetadataRemovedCount: 1,
    });
    expect(existsSync(orphanMarker)).toBe(false);
  }, 60_000);

  test("does not steal a live commit lock and returns actionable bounded evidence", async () => {
    expect(process.platform).toBe("darwin");
    const fixture = referenceFixture("bootstrap-reference-live-owner");
    expect(await sdlc.bootstrap(fixture.optionsFor("A"))).toMatchObject({ status: "succeeded" });
    const { child, outcome } = fixture.spawnBootstrap("B");
    await waitForPath(fixture.lockPath, child);
    expect(child.kill("SIGSTOP")).toBe(true);
    const identity = filesystemIdentity(fixture.lockPath);
    try {
      const contended = await sdlc.bootstrap(fixture.optionsFor("C"));
      expect(contended).toMatchObject({
        status: "failed",
        reason: "reference_commit_busy",
        diagnostics: [{ code: "BOOTSTRAP_REFERENCE_COMMIT_BUSY" }],
      });
      expect(filesystemIdentity(fixture.lockPath)).toEqual(identity);
    } finally {
      child.kill("SIGCONT");
    }
    const completed = await outcome;
    expect(completed.status, completed.stderr).toBe(0);
    expect(JSON.parse(completed.stdout)).toMatchObject({ status: "succeeded" });
  }, 60_000);

  test("fails safely when an unrelated listener occupies the deterministic recovery port", async () => {
    expect(process.platform).toBe("darwin");
    const fixture = referenceFixture("bootstrap-reference-port-collision");
    const initial = await sdlc.bootstrap(fixture.optionsFor("A"));
    expect(initial).toMatchObject({ status: "succeeded" });
    const port = bootstrapKernelBoundaryPort(
      fixture.stateRoot,
      "bootstrap-reference-recovery",
      {
        consumer: fixture.project,
        consumerRoot: realpathSync(fixture.root),
      },
    );
    const listener = createServer();
    await new Promise<void>((resolve, reject) => {
      listener.once("error", reject);
      listener.listen({ host: "127.0.0.1", port, exclusive: true }, () => resolve());
    });
    try {
      const collision = await sdlc.bootstrap(fixture.optionsFor("B"));
      expect(collision).toMatchObject({
        status: "failed",
        reason: "reference_commit_busy",
        diagnostics: [{ code: "BOOTSTRAP_REFERENCE_COMMIT_BUSY" }],
      });
      const reference = JSON.parse(readFileSync(fixture.referencePath, "utf8"));
      expect(reference.currentStateKey).toBe(initial.stateKey);
    } finally {
      await new Promise<void>((resolve, reject) => {
        listener.close((error) => error === undefined ? resolve() : reject(error));
      });
    }
  }, 60_000);

  test("fails closed on symlinked or replaced commit lock markers", async () => {
    expect(process.platform).toBe("darwin");
    const fixture = referenceFixture("bootstrap-reference-hostile-lock");
    const initial = await sdlc.bootstrap(fixture.optionsFor("A"));
    expect(initial).toMatchObject({ status: "succeeded" });
    mkdirSync(dirname(fixture.lockPath), { recursive: true });
    const foreign = join(fixture.evidence, "foreign-lock");
    writeFileSync(foreign, "foreign-lock-bytes");

    const acquired = fixture.spawnBootstrap("B");
    await waitForPath(fixture.lockPath, acquired.child);
    expect(acquired.child.kill("SIGSTOP")).toBe(true);
    const displaced = join(fixture.evidence, "displaced-owned-lock");
    renameSync(fixture.lockPath, displaced);
    writeFileSync(fixture.lockPath, "replacement-lock-bytes");
    expect(acquired.child.kill("SIGCONT")).toBe(true);
    const replacedWhileHeld = await acquired.outcome;
    expect(replacedWhileHeld.status, replacedWhileHeld.stderr).toBe(0);
    expect(JSON.parse(replacedWhileHeld.stdout)).toMatchObject({
      status: "failed",
      reason: "reference_commit_invalid",
      diagnostics: [{ code: "BOOTSTRAP_REFERENCE_COMMIT_INVALID" }],
    });
    expect(readFileSync(fixture.lockPath, "utf8")).toBe("replacement-lock-bytes");
    rmSync(fixture.lockPath);
    rmSync(displaced);
    for (const name of readdirSync(dirname(fixture.lockPath))) {
      if (name.endsWith(".marker")) rmSync(join(dirname(fixture.lockPath), name));
    }

    symlinkSync(foreign, fixture.lockPath);

    const symlinked = await sdlc.bootstrap(fixture.optionsFor("C"));
    expect(symlinked).toMatchObject({
      status: "failed",
      reason: "reference_commit_invalid",
      diagnostics: [{ code: "BOOTSTRAP_REFERENCE_COMMIT_INVALID" }],
    });
    expect(readFileSync(foreign, "utf8")).toBe("foreign-lock-bytes");
    rmSync(fixture.lockPath);
    writeFileSync(fixture.lockPath, "replacement-lock-bytes");

    const replaced = await sdlc.bootstrap(fixture.optionsFor("D"));
    expect(replaced).toMatchObject({
      status: "failed",
      reason: "reference_commit_invalid",
      diagnostics: [{ code: "BOOTSTRAP_REFERENCE_COMMIT_INVALID" }],
    });
    expect(readFileSync(fixture.lockPath, "utf8")).toBe("replacement-lock-bytes");
    const reference = JSON.parse(readFileSync(fixture.referencePath, "utf8"));
    expect(reference.currentStateKey).toBe(initial.stateKey);
  }, 60_000);

  test("never leaves a reference to state quarantined by concurrent maintenance", async () => {
    expect(process.platform).toBe("darwin");
    const raceRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-bootstrap-race-consumer-"));
    const sentinelRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-bootstrap-race-sentinel-"));
    const stateRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-bootstrap-race-state-"));
    const evidence = mkdtempSync(join(tmpdir(), "tc-sdlc-bootstrap-race-evidence-"));
    const temporaryRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-bootstrap-race-temp-"));
    for (const root of [raceRoot, sentinelRoot]) writeFileSync(join(root, "input.txt"), "input\n");
    const values = input(raceRoot, ["input.txt"]);
    const declarationFor = (command: string) =>
      sdlc.validateDeclaration({
        ...values.declaration,
        targets: { check: { ...values.declaration.targets.check, command } },
      });
    const raceDeclaration = declarationFor("node -e 'process.stdout.write(\"race\")'");
    const sentinelDeclaration = declarationFor("node -e 'process.stdout.write(\"sentinel\")'");
    const bootstrapFor = (
      root: string,
      declaration: ReturnType<typeof sdlc.validateDeclaration>,
      receiptPath: string,
    ) => ({
      root,
      declaration,
      catalogue: values.catalogue,
      lock: sdlc.resolveLock(declaration, values.catalogue),
      stateRoot,
      receiptPath,
      host: { platform: "darwin" as const, architecture: process.arch, offline: false },
    });
    const raceOptions = bootstrapFor(
      raceRoot,
      raceDeclaration,
      join(evidence, "initial-race.json"),
    );
    const sentinelOptions = bootstrapFor(
      sentinelRoot,
      sentinelDeclaration,
      join(evidence, "initial-sentinel.json"),
    );
    const initialRace = await sdlc.bootstrap(raceOptions);
    const initialSentinel = await sdlc.bootstrap(sentinelOptions);
    expect(initialRace.status).toBe("succeeded");
    expect(initialSentinel.status).toBe("succeeded");
    expect(initialRace.stateKey).not.toBe(initialSentinel.stateKey);

    const referencePath = join(
      stateRoot,
      "references",
      `${sdlc.digest({ consumer: raceDeclaration.project, consumerRoot: realpathSync(raceRoot) }).slice("sha256:".length)}.json`,
    );
    const waitFor = (child: ReturnType<typeof spawn>) =>
      new Promise<Readonly<{ status: number | null; stderr: string }>>((resolve) => {
        let stderr = "";
        child.stderr?.setEncoding("utf8");
        child.stderr?.on("data", (value) => { stderr += value; });
        child.once("exit", (status) => resolve({ status, stderr }));
      });
    const references = join(stateRoot, "references");
    const sentinelIdentity = filesystemIdentity(join(stateRoot, initialSentinel.stateKey));
    for (let index = 0; index < 5_000; index += 1) {
      const value = {
        schema: "tc.sdlc/bootstrap-reference/v2",
        owner: "@three-cubes/tc-sdlc",
        phase: "committed",
        transaction: "00000000-0000-4000-8000-000000000001",
        committedAtMs: 1,
        consumer: `lock-holder-${index}`,
        consumerRoot: `/private/tmp/tc-sdlc-lock-holder-${index}`,
        currentStateKey: initialSentinel.stateKey,
        currentStateIdentity: sentinelIdentity,
      };
      const name = `${sdlc.digest({ consumer: value.consumer, consumerRoot: value.consumerRoot }).slice("sha256:".length)}.json`;
      writeFileSync(join(references, name), sdlc.canonicalJson(value));
    }
    rmSync(referencePath, { force: true });
    const statePath = join(stateRoot, initialRace.stateKey);
    const old = new Date(Date.now() - 49 * 60 * 60 * 1_000);
    utimesSync(statePath, old, old);

    const blockedBootstrapReceipt = join(evidence, "race-bootstrap-blocked.json");
    const maintenanceReceipt = join(evidence, "race-maintenance.json");
    const maintenanceChild = spawn(
      process.execPath,
      [
        CLI,
        "maintain",
        "--state-root", stateRoot,
        "--temporary-root", temporaryRoot,
        "--receipt", maintenanceReceipt,
        "--mode", "apply",
      ],
      { stdio: ["ignore", "ignore", "pipe"] },
    );
    const maintenanceExitPromise = waitFor(maintenanceChild);
    const stateParent = dirname(statePath);
    let quarantinePath: string | undefined;
    const deadline = Date.now() + 30_000;
    while (quarantinePath === undefined && Date.now() < deadline) {
      quarantinePath = readdirSync(stateParent)
        .find((name) => name.startsWith(".tc-sdlc-quarantine-"));
      await new Promise((resolve) => setTimeout(resolve, 1));
    }
    expect(quarantinePath).toBeDefined();
    expect(maintenanceChild.kill("SIGSTOP")).toBe(true);
    const quarantinePathname = join(stateParent, quarantinePath!);
    expect(existsSync(quarantinePathname)).toBe(true);
    const quarantineIdentity = filesystemIdentity(quarantinePathname);

    const blockedBootstrap = await sdlc.bootstrap({
      ...raceOptions,
      receiptPath: blockedBootstrapReceipt,
    });
    expect(blockedBootstrap).toMatchObject({
      status: "failed",
      reason: "state_materialization_busy",
      diagnostics: [{ code: "BOOTSTRAP_STATE_MATERIALIZATION_BUSY" }],
    });
    expect(existsSync(statePath)).toBe(false);
    expect(filesystemIdentity(quarantinePathname)).toEqual(quarantineIdentity);

    expect(maintenanceChild.kill("SIGCONT")).toBe(true);
    const maintenanceExit = await maintenanceExitPromise;
    expect(maintenanceExit.stderr).toBe("");
    expect(maintenanceExit.status).toBe(0);
    expect(JSON.parse(readFileSync(maintenanceReceipt, "utf8"))).toMatchObject({
      schema: "tc.sdlc/maintenance-receipt/v1",
      status: "succeeded",
    });
    expect(existsSync(quarantinePathname)).toBe(false);
    const retriedReceipt = join(evidence, "race-bootstrap-retried.json");
    const retried = await sdlc.bootstrap({ ...raceOptions, receiptPath: retriedReceipt });
    expect(retried).toMatchObject({ status: "succeeded", stateKey: initialRace.stateKey });
    const reference = JSON.parse(readFileSync(referencePath, "utf8"));
    expect(existsSync(join(stateRoot, reference.currentStateKey, "state.json"))).toBe(true);
    expect(reference.currentStateIdentity).toEqual(
      filesystemIdentity(join(stateRoot, reference.currentStateKey)),
    );
  }, 180_000);

  test("retains state after bootstrap is killed with an identity-bound pending transaction", async () => {
    expect(process.platform).toBe("darwin");
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-pending-crash-consumer-"));
    for (const name of ["package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock"]) {
      writeFileSync(join(root, name), readFileSync(join(consumer, name)));
    }
    const stateRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-pending-crash-state-"));
    const evidence = mkdtempSync(join(tmpdir(), "tc-sdlc-pending-crash-evidence-"));
    const temporaryRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-pending-crash-temp-"));
    const options = {
      ...input(root),
      stateRoot,
      receiptPath: join(evidence, "initial.json"),
      host: { platform: "darwin" as const, architecture: process.arch, offline: false },
    };
    const initial = await sdlc.bootstrap(options);
    expect(initial.status).toBe("succeeded");
    const referencePath = join(
      stateRoot,
      "references",
      `${sdlc.digest({ consumer: options.declaration.project, consumerRoot: realpathSync(root) }).slice("sha256:".length)}.json`,
    );
    rmSync(referencePath);
    const recoveryPort = bootstrapKernelBoundaryPort(
      stateRoot,
      "bootstrap-reference-recovery",
      {
        consumer: options.declaration.project,
        consumerRoot: realpathSync(root),
      },
    );
    const recoveryBlocker = createServer();
    await new Promise<void>((resolve, reject) => {
      recoveryBlocker.once("error", reject);
      recoveryBlocker.listen(
        { host: "127.0.0.1", port: recoveryPort, exclusive: true },
        () => resolve(),
      );
    });
    const runner = join(evidence, "pending-child.mjs");
    const optionsPath = join(evidence, "pending-options.json");
    writeFileSync(
      runner,
      `import {readFileSync} from "node:fs"; import * as sdlc from ${JSON.stringify(PUBLIC_PACKAGE)}; await sdlc.bootstrap(JSON.parse(readFileSync(process.argv[2], "utf8")));\n`,
    );
    writeFileSync(
      optionsPath,
      JSON.stringify({
        ...options,
        receiptPath: join(evidence, "killed.json"),
        host: { ...options.host, offline: true },
      }),
    );
    const child = spawn(process.execPath, [runner, optionsPath], { stdio: "ignore" });
    const pendingRoot = join(stateRoot, "references", "pending");
    let pendingName: string | undefined;
    const deadline = Date.now() + 30_000;
    while (pendingName === undefined && child.exitCode === null && Date.now() < deadline) {
      pendingName = readdirSync(pendingRoot).find((name) => name.endsWith(".json"));
      if (pendingName === undefined) await new Promise((resolve) => setTimeout(resolve, 1));
    }
    expect(pendingName).toBeDefined();
    expect(child.kill("SIGKILL")).toBe(true);
    await new Promise<void>((resolve) => child.once("exit", () => resolve()));
    await new Promise<void>((resolve, reject) => {
      recoveryBlocker.close((error) => error === undefined ? resolve() : reject(error));
    });
    expect(existsSync(referencePath)).toBe(false);
    const pendingPath = join(pendingRoot, pendingName!);
    expect(JSON.parse(readFileSync(pendingPath, "utf8"))).toMatchObject({
      schema: "tc.sdlc/bootstrap-reference-pending/v1",
      phase: "pending",
      stateKey: initial.stateKey,
      stateIdentity: filesystemIdentity(join(stateRoot, initial.stateKey)),
    });

    const old = new Date(Date.now() - 49 * 60 * 60 * 1_000);
    utimesSync(join(stateRoot, initial.stateKey), old, old);
    const retained = await sdlc.maintain({
      stateRoot,
      temporaryRoot,
      receiptPath: join(evidence, "retained.json"),
      mode: "apply",
    });
    expect(retained.retained).toContainEqual({ path: initial.stateKey, reason: "referenced" });
    expect(existsSync(join(stateRoot, initial.stateKey, "state.json"))).toBe(true);

    utimesSync(pendingPath, old, old);
    const healed = await sdlc.maintain({
      stateRoot,
      temporaryRoot,
      receiptPath: join(evidence, "healed.json"),
      mode: "apply",
    });
    expect(healed.referenceMetadataRemovedCount).toBe(1);
    expect(healed.retained).toContainEqual({ path: initial.stateKey, reason: "referenced" });
    expect(existsSync(pendingPath)).toBe(false);
    const restarted = await sdlc.bootstrap({
      ...options,
      receiptPath: join(evidence, "restarted.json"),
      host: { ...options.host, offline: true },
    });
    expect(restarted).toMatchObject({ status: "succeeded", reused: true });
    expect(JSON.parse(readFileSync(referencePath, "utf8"))).toMatchObject({
      schema: "tc.sdlc/bootstrap-reference/v2",
      phase: "committed",
      currentStateKey: initial.stateKey,
    });
  }, 180_000);

  test("producer advances A to B to C and maintenance expires only unreferenced A", async () => {
    expect(process.platform).toBe("darwin");
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-reference-journey-"));
    writeFileSync(join(root, "input.txt"), "input\n");
    const stateRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-reference-state-"));
    const evidence = mkdtempSync(join(tmpdir(), "tc-sdlc-reference-evidence-"));
    const states: string[] = [];
    for (const generation of ["A", "B", "C"]) {
      const values = input(root, ["input.txt"]);
      const declaration = sdlc.validateDeclaration({
        ...values.declaration,
        targets: {
          check: {
            ...values.declaration.targets.check,
            command: `node -e 'process.stdout.write(\"${generation}\")'`,
          },
        },
      });
      const receipt = await sdlc.bootstrap({
        root,
        declaration,
        catalogue: values.catalogue,
        lock: sdlc.resolveLock(declaration, values.catalogue),
        stateRoot,
        receiptPath: join(evidence, `${generation}.json`),
        host: { platform: "darwin", architecture: process.arch, offline: false },
      });
      expect(receipt).toMatchObject({ status: "succeeded" });
      states.push(receipt.stateKey);
    }
    expect(new Set(states).size).toBe(3);
    const referenceFiles = readdirSync(join(stateRoot, "references"))
      .filter((name) => name.endsWith(".json"));
    expect(referenceFiles).toHaveLength(1);
    expect(readdirSync(join(stateRoot, "references", "pending"))).toEqual([]);
    const finalReference = JSON.parse(
      readFileSync(join(stateRoot, "references", referenceFiles[0]!), "utf8"),
    );
    expect(finalReference).toMatchObject({
      currentStateKey: states[2],
      predecessorStateKey: states[1],
    });
    expect(finalReference.currentStateIdentity).toEqual(
      filesystemIdentity(join(stateRoot, states[2]!)),
    );
    expect(finalReference.predecessorStateIdentity).toEqual(
      filesystemIdentity(join(stateRoot, states[1]!)),
    );
    const old = new Date(Date.now() - 49 * 60 * 60 * 1_000);
    for (const state of states) utimesSync(join(stateRoot, state), old, old);
    const maintained = await sdlc.maintain({
      stateRoot,
      temporaryRoot: mkdtempSync(join(tmpdir(), "tc-sdlc-reference-temp-")),
      receiptPath: join(evidence, "maintain.json"),
      mode: "apply",
    });
    expect(maintained.candidates).toContainEqual(
      expect.objectContaining({ kind: "bootstrap-state", path: states[0] }),
    );
    expect(maintained.retained).toEqual(expect.arrayContaining([
      { path: states[1], reason: "referenced" },
      { path: states[2], reason: "referenced" },
    ]));
    expect(existsSync(join(stateRoot, states[0]!))).toBe(false);
    expect(existsSync(join(stateRoot, states[1]!))).toBe(true);
    expect(existsSync(join(stateRoot, states[2]!))).toBe(true);
  }, 180_000);

  test("does not trust an arbitrary PATH and emits one executable Linux remediation command", async () => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-untrusted-path-"));
    for (const name of ["package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock"]) {
      writeFileSync(join(root, name), readFileSync(join(consumer, name)));
    }
    const stateRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-untrusted-state-"));
    const options = input(root);
    const receipt = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: join(dirname(root), "untrusted-path-receipt.json"),
      host: {
        platform: "linux",
        architecture: "arm64",
        path: "/an/arbitrary/path/must/not/be-used",
        offline: false,
      } as never,
    });

    expect(receipt).toMatchObject({
      status: "failed",
      reason: "host_prerequisite_missing",
      diagnosticsCount: 1,
      diagnosticsTruncated: false,
    });
    expect(receipt.diagnostics).toHaveLength(1);
    expect(receipt.diagnostics[0]?.action).toBe(
      `docker pull ghcr.io/three-cubes/tc-sdlc@${imageDigest}`,
    );
    expect(execFileSync("docker", ["--version"], { encoding: "utf8" })).toContain("Docker version");
  });

  test.skipIf(unavailableDarwinArchitecture === undefined)("emits one syntactically executable macOS prerequisite remediation command", async () => {
    expect(process.platform).toBe("darwin");
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-mac-remediation-"));
    for (const name of ["package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock"]) {
      writeFileSync(join(root, name), readFileSync(join(consumer, name)));
    }
    const values = input(root);
    expect(() => sdlc.validateDeclaration({
      ...values.declaration,
      toolchains: { ...values.declaration.toolchains, node: "25" },
    })).toThrow(/must be equal to constant/);
    const receipt = await sdlc.bootstrap({
      ...values,
      stateRoot: mkdtempSync(join(tmpdir(), "tc-sdlc-mac-remediation-state-")),
      receiptPath: join(dirname(root), "mac-remediation.json"),
      host: { platform: "darwin", architecture: unavailableDarwinArchitecture!, offline: false },
    });

    expect(receipt).toMatchObject({
      status: "failed",
      reason: "host_prerequisite_missing",
      diagnosticsCount: 1,
    });
    const action = receipt.diagnostics[0]?.action;
    expect(action).toContain("brew install node@24 python@3.13 uv");
    expect(action).not.toContain("corepack install --global");
    expect(spawnSync("/bin/bash", ["-n", "-c", action!]).status).toBe(0);
  });

  test("materialises exact pnpm inside owned state without ambient Corepack", async () => {
    expect(process.platform).toBe("darwin");
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-python-only-consumer-"));
    for (const name of ["pyproject.toml", "uv.lock"]) {
      writeFileSync(join(root, name), readFileSync(join(consumer, name)));
    }
    const stateRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-python-only-state-"));
    const evidence = mkdtempSync(join(tmpdir(), "tc-sdlc-python-only-evidence-"));
    const ambientCorepack = join(evidence, "ambient-corepack-is-a-file");
    const ambientHome = join(evidence, "ambient-home-is-a-file");
    writeFileSync(ambientCorepack, "ambient corepack must remain untouched\n");
    writeFileSync(ambientHome, "ambient home must remain untouched\n");
    const values = input(root, ["pyproject.toml", "uv.lock"]);
    const options = {
      ...values,
      stateRoot,
      receiptPath: join(evidence, "online.json"),
      host: { platform: "darwin" as const, architecture: process.arch, offline: false },
    };
    const previous = {
      HOME: process.env.HOME,
      COREPACK_HOME: process.env.COREPACK_HOME,
      COREPACK_ENABLE_NETWORK: process.env.COREPACK_ENABLE_NETWORK,
    };
    process.env.HOME = ambientHome;
    process.env.COREPACK_HOME = ambientCorepack;
    process.env.COREPACK_ENABLE_NETWORK = "0";
    try {
      const online = await sdlc.bootstrap(options);
      expect(online).toMatchObject({ status: "succeeded", reused: false });
      expect(online.dependencies.map((dependency) => dependency.manager)).toEqual(["uv"]);
      const pnpmEvidence = online.adapters.find((adapter) => adapter.name === "pnpm")!;
      expect(pnpmEvidence).toMatchObject({
        version: "11.22.0",
        provider: "catalogue-distribution",
      });
      const state = JSON.parse(
        readFileSync(join(stateRoot, online.stateKey, "state.json"), "utf8"),
      );
      const pnpmState = state.adapters.find(
        (adapter: { name: string }) => adapter.name === "pnpm",
      );
      expect(pnpmState.executable.startsWith(`${join(stateRoot, online.stateKey)}/`)).toBe(true);
      const launcher = join(stateRoot, pnpmEvidence.launcher);
      expect(execFileSync(launcher, ["--version"], {
        encoding: "utf8",
        env: {
          HOME: ambientHome,
          COREPACK_HOME: ambientCorepack,
          COREPACK_ENABLE_NETWORK: "0",
          PATH: "/usr/bin:/bin",
        },
      }).trim()).toBe("11.22.0");

      const warm = await sdlc.bootstrap({
        ...options,
        receiptPath: join(evidence, "offline.json"),
        host: { ...options.host, offline: true },
      });
      expect(warm).toMatchObject({ status: "succeeded", reused: true });
      expect(readFileSync(ambientCorepack, "utf8")).toBe(
        "ambient corepack must remain untouched\n",
      );
      expect(readFileSync(ambientHome, "utf8")).toBe(
        "ambient home must remain untouched\n",
      );

      const distributionRoot = dirname(dirname(pnpmState.executable));
      const distributionBytes = join(distributionRoot, "dist", "pnpm.mjs");
      writeFileSync(distributionBytes, "\n// corrupted\n", { flag: "a" });
      const corrupt = await sdlc.bootstrap({
        ...options,
        receiptPath: join(evidence, "corrupt.json"),
        host: { ...options.host, offline: true },
      });
      expect(corrupt).toMatchObject({ status: "failed", reason: "state_corrupt" });

      const cold = await sdlc.bootstrap({
        ...options,
        stateRoot: mkdtempSync(join(tmpdir(), "tc-sdlc-python-only-cold-state-")),
        receiptPath: join(evidence, "cold.json"),
        host: { ...options.host, offline: true },
      });
      expect(cold).toMatchObject({ status: "failed", reason: "offline_cold" });
      expect(cold.diagnostics[0]?.action).toContain("retry without offline mode");
      expect(cold.diagnostics[0]?.action).not.toContain("corepack install --global");
    } finally {
      for (const [name, value] of Object.entries(previous)) {
        if (value === undefined) delete process.env[name];
        else process.env[name] = value;
      }
    }
  }, 180_000);

  test("uses real platform prerequisites and materialises both dependency locks outside the checkout", async () => {
    expect(process.platform).toBe("darwin");
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-real-consumer-"));
    for (const name of ["package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock"]) {
      writeFileSync(join(root, name), readFileSync(join(consumer, name)));
    }
    const stateRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-real-state-"));
    const options = input(root);
    const receiptPath = join(dirname(stateRoot), "real-bootstrap-receipt.json");
    const receipt = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath,
      host: {
        platform: "darwin",
        architecture: process.arch,
        offline: false,
      },
    });

    expect(receipt).toMatchObject({
      status: "succeeded",
      reason: null,
      platform: "darwin",
      architecture: process.arch,
      diagnostics: [],
    });
    expect(receipt.adapters.map((adapter) => [adapter.name, adapter.provider])).toEqual([
      ["node", "homebrew"],
      ["pnpm", "catalogue-distribution"],
      ["python", "homebrew"],
      ["uv", "catalogue-distribution"],
    ]);
    expect(receipt.dependencies.map((dependency) => dependency.manager)).toEqual([
      "pnpm",
      "uv",
    ]);
    expect(receipt.dependencies.every((dependency) => dependency.lockDigest.startsWith("sha256:"))).toBe(true);
    expect(receipt.dependencies.every((dependency) => dependency.manifestDigest.startsWith("sha256:"))).toBe(true);
    expect(existsSync(join(root, "node_modules"))).toBe(false);
    expect(existsSync(join(root, ".venv"))).toBe(false);
    expect(existsSync(join(stateRoot, receipt.stateKey, "dependencies", "node", "node_modules", "yaml"))).toBe(true);
    const python = join(stateRoot, receipt.stateKey, "dependencies", "python", "bin", "python");
    const pythonEnvironment = { ...process.env, PYTHONDONTWRITEBYTECODE: "1" };
    expect(execFileSync(python, ["-c", "import attrs; print(attrs.__version__)"], {
      encoding: "utf8",
      env: pythonEnvironment,
    }).trim()).toBe("26.1.0");
    const pnpmLauncher = join(
      stateRoot,
      receipt.adapters.find((adapter) => adapter.name === "pnpm")!.launcher,
    );
    const emptyHome = join(dirname(stateRoot), "empty-home-is-a-file");
    writeFileSync(emptyHome, "unchanged");
    expect(execFileSync(pnpmLauncher, ["--version"], {
      encoding: "utf8",
      env: { HOME: emptyHome, PATH: "/usr/bin:/bin", COREPACK_ENABLE_NETWORK: "0" },
    }).trim()).toBe("11.22.0");
    expect(readFileSync(receiptPath, "utf8")).toBe(sdlc.serialiseBootstrapReceipt(receipt));
    const referenceFiles = readdirSync(join(stateRoot, "references"))
      .filter((name) => name.endsWith(".json"));
    expect(referenceFiles).toHaveLength(1);
    expect(readdirSync(join(stateRoot, "references", "pending"))).toEqual([]);
    expect(
      JSON.parse(readFileSync(join(stateRoot, "references", referenceFiles[0]!), "utf8")),
    ).toMatchObject({
      schema: "tc.sdlc/bootstrap-reference/v2",
      owner: "@three-cubes/tc-sdlc",
      phase: "committed",
      transaction: expect.stringMatching(/^[0-9a-f-]{36}$/),
      consumerRoot: realpathSync(root),
      currentStateKey: receipt.stateKey,
    });

    const relocatedRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-relocated-consumer-"));
    for (const name of ["package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock"]) {
      writeFileSync(join(relocatedRoot, name), readFileSync(join(consumer, name)));
    }
    const relocatedOptions = input(relocatedRoot);
    const relocated = await sdlc.bootstrap({
      ...relocatedOptions,
      stateRoot,
      receiptPath: `${receiptPath}.relocated`,
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(relocated).toMatchObject({ status: "succeeded", reused: true });
    expect(relocated.dependencies).toEqual(receipt.dependencies);
    expect(
      readdirSync(join(stateRoot, "references")).filter((name) => name.endsWith(".json")),
    ).toHaveLength(2);

    const warm = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: `${receiptPath}.offline`,
      host: {
        platform: "darwin",
        architecture: process.arch,
        offline: true,
      },
    });
    expect(warm).toMatchObject({ status: "succeeded", reused: true });
    const maintenanceTemporaryRoot = join(dirname(stateRoot), "tc-sdlc-pnpm-maintenance");
    mkdirSync(maintenanceTemporaryRoot);
    const maintained = await sdlc.maintain({
      stateRoot,
      temporaryRoot: maintenanceTemporaryRoot,
      receiptPath: `${receiptPath}.maintenance`,
      mode: "apply",
      pnpmExecutable: pnpmLauncher,
    });
    expect(maintained).toMatchObject({
      status: "succeeded",
      tools: { pnpm: { status: "pruned", reclaimedBytes: expect.any(Number) } },
    });
    const uvDependency = receipt.dependencies.find((dependency) => dependency.manager === "uv")!;
    expect(uvDependency.installedDigest).toMatch(/^sha256:[0-9a-f]{64}$/);
    const attrsDirectory = execFileSync(
      python,
      ["-c", "import attrs; print(attrs.__path__[0])"],
      { encoding: "utf8", env: pythonEnvironment },
    ).trim();
    const movedAttrsDirectory = `${attrsDirectory}.renamed`;
    renameSync(attrsDirectory, movedAttrsDirectory);
    expect(() => execFileSync(python, ["-c", "import attrs"], {
      stdio: "pipe",
      env: pythonEnvironment,
    })).toThrow();
    const renamedPythonTree = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: `${receiptPath}.renamed-python-tree`,
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(renamedPythonTree).toMatchObject({ status: "failed", reason: "state_corrupt" });
    renameSync(movedAttrsDirectory, attrsDirectory);
    const attrModule = execFileSync(
      python,
      ["-c", "import attr._make; print(attr._make.__file__)"],
      { encoding: "utf8", env: pythonEnvironment },
    ).trim();
    const attrModuleBytes = readFileSync(attrModule);
    rmSync(attrModule);
    rmSync(join(dirname(attrModule), "__pycache__"), { recursive: true, force: true });
    expect(() => execFileSync(python, ["-c", "import attr._make"], {
      stdio: "pipe",
      env: pythonEnvironment,
    })).toThrow();
    const deletedPythonFile = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: `${receiptPath}.deleted-python-file`,
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(deletedPythonFile).toMatchObject({ status: "failed", reason: "state_corrupt" });
    writeFileSync(attrModule, attrModuleBytes);
    const restoredPythonTree = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: `${receiptPath}.restored-python-tree`,
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(restoredPythonTree).toMatchObject({ status: "succeeded", reused: true });

    const declarationPath = join(root, "sdlc.json");
    const cataloguePath = join(root, "catalogue.json");
    const lockPath = join(root, "tc-sdlc.lock");
    writeFileSync(declarationPath, sdlc.canonicalJson(options.declaration));
    writeFileSync(cataloguePath, sdlc.canonicalJson(options.catalogue));
    sdlc.writeLock(lockPath, options.lock);
    const ambientCorepack = join(homedir(), ".cache", "node", "corepack");
    const sandboxedWarm = spawnSync(
      "/usr/bin/sandbox-exec",
      [
        "-p",
        `(version 1)(allow default)(deny file-read* file-write* (subpath ${JSON.stringify(ambientCorepack)}))`,
        process.execPath,
        CLI,
        "bootstrap",
        "--declaration", declarationPath,
        "--catalogue", cataloguePath,
        "--lock", lockPath,
        "--root", root,
        "--state-root", stateRoot,
        "--receipt", `${receiptPath}.sandboxed`,
        "--offline", "true",
      ],
      {
        encoding: "utf8",
        env: {
          ...process.env,
          HOME: emptyHome,
          PATH: "/untrusted",
          XDG_CACHE_HOME: join(homedir(), ".cache"),
          COREPACK_HOME: ambientCorepack,
        },
      },
    );
    expect(sandboxedWarm.status, sandboxedWarm.stderr).toBe(0);
    expect(JSON.parse(sandboxedWarm.stdout)).toMatchObject({ status: "ok", reused: true });

    const originalManifest = readFileSync(join(root, "package.json"), "utf8");
    const changedManifest = JSON.parse(originalManifest);
    changedManifest.description = "identity-affecting manifest change";
    writeFileSync(join(root, "package.json"), `${JSON.stringify(changedManifest, null, 2)}\n`);
    const changed = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: `${receiptPath}.changed`,
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(changed).toMatchObject({ status: "failed", reason: "offline_cold", reused: false });
    expect(changed.stateKey).not.toBe(receipt.stateKey);
    writeFileSync(join(root, "package.json"), originalManifest);

    const launcher = join(stateRoot, warm.adapters[0]!.launcher);
    writeFileSync(launcher, "corrupt");
    const corrupt = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: `${receiptPath}.corrupt`,
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(corrupt).toMatchObject({ status: "failed", reason: "state_corrupt" });
    expect(readFileSync(launcher, "utf8")).toBe("corrupt");
  }, 30_000);

  test("materialises and identity-binds the complete pnpm workspace graph", async () => {
    expect(process.platform).toBe("darwin");
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-workspace-consumer-"));
    cpSync(workspaceConsumer, root, { recursive: true });
    const undeclaredCache = join(root, "packages", "b", ".cache", "untracked");
    mkdirSync(dirname(undeclaredCache), { recursive: true });
    writeFileSync(undeclaredCache, "must not enter managed state");
    const stateRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-workspace-state-"));
    const options = input(root, [
      "package.json",
      "pnpm-lock.yaml",
      "pnpm-workspace.yaml",
      "packages/**/*.json",
    ]);
    const receipt = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: join(dirname(stateRoot), "workspace-receipt.json"),
      host: { platform: "darwin", architecture: process.arch, offline: false },
    });

    expect(receipt).toMatchObject({ status: "succeeded", dependencies: [{ manager: "pnpm" }] });
    expect(receipt.dependencies[0]?.inputs.map((input) => input.path)).toEqual([
      "package.json",
      "packages/a/index.js",
      "packages/a/package.json",
      "packages/b/index.js",
      "packages/b/package.json",
      "patches/is-number@7.0.0.patch",
      "pnpm-lock.yaml",
      "pnpm-workspace.yaml",
    ]);
    const environment = join(stateRoot, receipt.stateKey, receipt.dependencies[0]!.environment);
    expect(existsSync(join(environment, "packages", "b", ".cache"))).toBe(false);
    expect(existsSync(join(environment, "packages", "a", "node_modules", "yaml"))).toBe(true);
    expect(existsSync(join(environment, "packages", "a", "node_modules", "workspace-b"))).toBe(true);
    const nodeLauncher = join(
      stateRoot,
      receipt.adapters.find((adapter) => adapter.name === "node")!.launcher,
    );
    expect(execFileSync(nodeLauncher, [
      "-e",
      `if (!require(${JSON.stringify(join(environment, "node_modules", "is-number"))}).tcSdlcPatched) process.exit(1)`,
    ], { encoding: "utf8" })).toBe("");
    for (const source of [
      join(root, "packages", "b"),
      join(environment, "node_modules", "workspace-a"),
    ]) {
      expect(execFileSync(nodeLauncher, [
        "-e",
        `if (require(${JSON.stringify(source)}) !== "workspace-source-contract") process.exit(1)`,
      ], { encoding: "utf8" })).toBe("");
    }

    const workspaceSource = join(root, "packages", "b", "index.js");
    const originalWorkspaceSource = readFileSync(workspaceSource, "utf8");
    writeFileSync(workspaceSource, `${originalWorkspaceSource}\nmodule.exports = "changed";\n`);
    const staleSource = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: join(dirname(stateRoot), "workspace-stale-source.json"),
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(staleSource).toMatchObject({ status: "failed", reason: "offline_cold" });
    expect(staleSource.stateKey).not.toBe(receipt.stateKey);
    writeFileSync(workspaceSource, originalWorkspaceSource);
    const restoredSource = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: join(dirname(stateRoot), "workspace-restored-source.json"),
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(restoredSource).toMatchObject({ status: "succeeded", reused: true });

    const memberManifest = join(root, "packages", "b", "package.json");
    const changed = JSON.parse(readFileSync(memberManifest, "utf8"));
    changed.description = "workspace identity sabotage";
    writeFileSync(memberManifest, `${JSON.stringify(changed, null, 2)}\n`);
    const stale = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: join(dirname(stateRoot), "workspace-stale.json"),
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(stale).toMatchObject({ status: "failed", reason: "offline_cold" });
    expect(stale.stateKey).not.toBe(receipt.stateKey);
    delete changed.description;
    writeFileSync(memberManifest, `${JSON.stringify(changed, null, 2)}\n`);

    const patch = join(root, "patches", "is-number@7.0.0.patch");
    const originalPatch = readFileSync(patch, "utf8");
    writeFileSync(patch, `${originalPatch}\n`);
    const stalePatch = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: join(dirname(stateRoot), "workspace-stale-patch.json"),
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(stalePatch).toMatchObject({ status: "failed", reason: "offline_cold" });
    expect(stalePatch.stateKey).not.toBe(receipt.stateKey);
    writeFileSync(patch, originalPatch);

    expect(receipt.dependencies[0]?.installedDigest).toMatch(/^sha256:[0-9a-f]{64}$/);
    const installedManifest = join(environment, "packages", "a", "node_modules", "yaml", "package.json");
    const originalInstalledManifest = readFileSync(installedManifest, "utf8");
    writeFileSync(installedManifest, `${originalInstalledManifest}\n`);
    const tamperedInstalledTree = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: join(dirname(stateRoot), "workspace-tampered-installed-tree.json"),
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(tamperedInstalledTree).toMatchObject({ status: "failed", reason: "state_corrupt" });
    writeFileSync(installedManifest, originalInstalledManifest);

    const installedExecutable = join(
      environment,
      "packages",
      "a",
      "node_modules",
      ".bin",
      "yaml",
    );
    const executableMode = statSync(installedExecutable).mode & 0o777;
    chmodSync(installedExecutable, 0o644);
    const nonExecutableInstalledTree = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: join(dirname(stateRoot), "workspace-non-executable-installed-tree.json"),
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(nonExecutableInstalledTree).toMatchObject({ status: "failed", reason: "state_corrupt" });
    chmodSync(installedExecutable, executableMode);

    rmSync(join(environment, "node_modules"), { recursive: true });
    const missingInstalledTree = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: join(dirname(stateRoot), "workspace-missing-installed-tree.json"),
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(missingInstalledTree).toMatchObject({ status: "failed", reason: "state_corrupt" });
  }, 30_000);

  test("rejects foreign, symlinked, in-checkout and stale state before host use", async () => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-state-sabotage-"));
    for (const name of ["package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock"]) {
      writeFileSync(join(root, name), readFileSync(join(consumer, name)));
    }
    const options = input(root);
    const host = { platform: "linux", architecture: "x64", offline: false } as const;
    const foreignRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-foreign-state-"));
    writeFileSync(join(foreignRoot, "foreign"), "preserve");
    const foreign = await sdlc.bootstrap({
      ...options,
      stateRoot: foreignRoot,
      receiptPath: join(dirname(root), "foreign-receipt.json"),
      host,
    });
    expect(foreign).toMatchObject({ status: "failed", reason: "foreign_state" });
    expect(readFileSync(join(foreignRoot, "foreign"), "utf8")).toBe("preserve");

    const target = mkdtempSync(join(tmpdir(), "tc-sdlc-state-target-"));
    const link = `${target}-link`;
    symlinkSync(target, link);
    const symlinked = await sdlc.bootstrap({
      ...options,
      stateRoot: link,
      receiptPath: join(dirname(root), "symlink-receipt.json"),
      host,
    });
    expect(symlinked).toMatchObject({ status: "failed", reason: "state_root_invalid" });

    const inside = join(root, ".state");
    const inCheckout = await sdlc.bootstrap({
      ...options,
      stateRoot: inside,
      receiptPath: join(dirname(root), "inside-receipt.json"),
      host,
    });
    expect(inCheckout).toMatchObject({ status: "failed", reason: "state_root_invalid" });
    expect(existsSync(inside)).toBe(false);

    const stale = structuredClone(options.lock) as Record<string, unknown>;
    stale.release = "9.9.9";
    const staleReceipt = await sdlc.bootstrap({
      ...options,
      lock: stale as never,
      stateRoot: mkdtempSync(join(tmpdir(), "tc-sdlc-stale-state-")),
      receiptPath: join(dirname(root), "stale-receipt.json"),
      host,
    });
    expect(staleReceipt).toMatchObject({ status: "failed", reason: "stale_lock" });
  });

  test("built CLI ignores PATH and HOME while using reviewed macOS prerequisites", () => {
    expect(process.platform).toBe("darwin");
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-bootstrap-cli-"));
    for (const name of ["package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock"]) {
      writeFileSync(join(root, name), readFileSync(join(consumer, name)));
    }
    const options = input(root);
    const stateRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-cli-state-"));
    const evidenceRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-cli-evidence-"));
    const declarationPath = join(root, "sdlc.json");
    const cataloguePath = join(root, "catalogue.json");
    const lockPath = join(root, "tc-sdlc.lock");
    const receiptPath = join(evidenceRoot, "bootstrap.json");
    writeFileSync(declarationPath, sdlc.canonicalJson(options.declaration));
    writeFileSync(cataloguePath, sdlc.canonicalJson(options.catalogue));
    sdlc.writeLock(lockPath, options.lock);
    const homeTrap = join(evidenceRoot, "home-is-a-file");
    writeFileSync(homeTrap, "unchanged");

    const result = spawnSync(
      process.execPath,
      [
        CLI,
        "bootstrap",
        "--declaration", declarationPath,
        "--catalogue", cataloguePath,
        "--lock", lockPath,
        "--root", root,
        "--state-root", stateRoot,
        "--receipt", receiptPath,
      ],
      { encoding: "utf8", env: { ...process.env, HOME: homeTrap, PATH: "/untrusted" } },
    );
    expect(result.status, result.stderr).toBe(0);
    expect(JSON.parse(result.stdout)).toMatchObject({
      schema: "tc.sdlc/command-result/v1",
      command: "bootstrap",
      status: "ok",
      release: "3.0.0",
    });
    expect(readFileSync(homeTrap, "utf8")).toBe("unchanged");
  }, 30_000);
});
