import * as sdlc from "../dist/index.js";
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
  utimesSync,
  writeFileSync,
} from "node:fs";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
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

describe("reviewed macOS bootstrap host and dependency boundary", () => {
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

    const runner = join(evidence, "bootstrap-child.mjs");
    writeFileSync(
      runner,
      `import {readFileSync} from "node:fs"; import * as sdlc from ${JSON.stringify(PUBLIC_PACKAGE)}; const options=JSON.parse(readFileSync(process.argv[2], "utf8")); const receipt=await sdlc.bootstrap(options); process.stdout.write(JSON.stringify({status:receipt.status,stateKey:receipt.stateKey}));\n`,
    );
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
        schema: "tc.sdlc/bootstrap-reference/v1",
        owner: "@three-cubes/tc-sdlc",
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

    const bootstrapReceipt = join(evidence, "race-bootstrap.json");
    const optionsPath = join(evidence, "race-options.json");
    writeFileSync(
      optionsPath,
      JSON.stringify({ ...raceOptions, receiptPath: bootstrapReceipt }),
    );
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
    expect(existsSync(join(stateParent, quarantinePath!))).toBe(true);

    const bootstrapChild = spawn(process.execPath, [runner, optionsPath], {
      stdio: ["ignore", "ignore", "pipe"],
    });
    const bootstrapExit = await waitFor(bootstrapChild);
    expect(bootstrapExit.stderr).toBe("");
    expect(bootstrapExit.status).toBe(0);
    expect(JSON.parse(readFileSync(bootstrapReceipt, "utf8"))).toMatchObject({
      schema: "tc.sdlc/bootstrap-receipt/v1",
      status: "succeeded",
      stateKey: initialRace.stateKey,
    });
    expect(maintenanceChild.kill("SIGCONT")).toBe(true);
    const maintenanceExit = await maintenanceExitPromise;
    expect(maintenanceExit.stderr).toBe("");
    expect(maintenanceExit.status).toBe(0);
    expect(JSON.parse(readFileSync(maintenanceReceipt, "utf8"))).toMatchObject({
      schema: "tc.sdlc/maintenance-receipt/v1",
      status: "succeeded",
    });
    const reference = JSON.parse(readFileSync(referencePath, "utf8"));
    expect(existsSync(join(stateRoot, reference.currentStateKey, "state.json"))).toBe(true);
    expect(reference.currentStateIdentity).toEqual(
      filesystemIdentity(join(stateRoot, reference.currentStateKey)),
    );
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
    const referenceFiles = readdirSync(join(stateRoot, "references"));
    expect(referenceFiles).toHaveLength(1);
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
    expect(execFileSync(python, ["-c", "import attrs; print(attrs.__version__)"], { encoding: "utf8" }).trim()).toBe("26.1.0");
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
    const referenceFiles = readdirSync(join(stateRoot, "references"));
    expect(referenceFiles).toHaveLength(1);
    expect(
      JSON.parse(readFileSync(join(stateRoot, "references", referenceFiles[0]!), "utf8")),
    ).toMatchObject({
      schema: "tc.sdlc/bootstrap-reference/v1",
      owner: "@three-cubes/tc-sdlc",
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
    expect(readdirSync(join(stateRoot, "references"))).toHaveLength(2);

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
      { encoding: "utf8" },
    ).trim();
    const movedAttrsDirectory = `${attrsDirectory}.renamed`;
    renameSync(attrsDirectory, movedAttrsDirectory);
    expect(() => execFileSync(python, ["-c", "import attrs"], { stdio: "pipe" })).toThrow();
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
      { encoding: "utf8" },
    ).trim();
    const attrModuleBytes = readFileSync(attrModule);
    rmSync(attrModule);
    rmSync(join(dirname(attrModule), "__pycache__"), { recursive: true, force: true });
    expect(() => execFileSync(python, ["-c", "import attr._make"], { stdio: "pipe" })).toThrow();
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
