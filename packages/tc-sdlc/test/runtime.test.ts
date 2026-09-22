import * as sdlc from "../dist/index.js";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, test } from "vitest";

const release = {
  version: "2.2.0",
  package: {
    name: "@three-cubes/tc-sdlc",
    version: "2.2.0",
  },
  workflowCommit: "1234567890abcdef1234567890abcdef12345678",
  imageDigest:
    "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  declarationSchema: "tc.sdlc/v1",
  lockSchema: "tc.sdlc/lock/v1",
  fitness: {
    package: "three-cubes-fitness",
    version: "0.17.1",
  },
  toolchains: {
    node: "24",
    packageManager: "pnpm@11.22.0",
    python: "3.13",
    uv: "0.12.5",
  },
  bootstrap: sdlc.CANONICAL_SDLC_BOOTSTRAP,
} as const;

const declarationFitness = {
  package: "three-cubes-fitness",
  config: "pyproject.toml",
  profiles: { full: "full" },
} as const;

function graphFor(targets: Readonly<Record<string, Record<string, unknown>>>) {
  const declaration = {
    schema: "tc.sdlc/v1",
    project: "runtime-fixture",
    toolchains: release.toolchains,
    fitness: declarationFitness,
    projects: [{ name: "fixture", root: "." }],
    targets,
  } as const;
  const catalogue = sdlc.createReleaseCatalogue(release);
  const lock = sdlc.resolveLock(declaration as never, catalogue);
  const inputs = Object.fromEntries(
    Object.keys(targets).map((target) => [`fixture:${target}`, []]),
  );
  const boundLock = (sdlc as Record<string, any>).bindGraphLock(
    declaration,
    lock,
    catalogue,
    inputs,
  );
  return (sdlc as Record<string, any>).buildGraph(declaration, boundLock);
}

function runtimeTarget(
  command: string,
  fields: Readonly<Record<string, unknown>> = {},
) {
  return {
    command,
    mode: "evaluate",
    trustBoundary: "portable",
    resources: { cpu: 1, memoryMiB: 64, ports: [], exclusive: [] },
    budget: { phaseMs: 5_000, noProgressMs: 2_000, heartbeatMs: 100 },
    ...fields,
  };
}

function testExecutionContext() {
  return {
    binding: {
      schema: "tc.sdlc/execution-context/v1",
      release: "2.2.0",
      platform: process.platform === "linux" ? "linux" : "darwin",
      architecture: process.arch,
      lockDigest: `sha256:${"a".repeat(64)}`,
      stateKey: "releases/2.2.0/test/darwin-arm64",
      stateGenerationIdentity: `sha256:${"e".repeat(64)}`,
      bootstrapReceiptDigest: `sha256:${"b".repeat(64)}`,
      stateDigest: `sha256:${"c".repeat(64)}`,
      dependencyDigest: `sha256:${"d".repeat(64)}`,
      fitness: { package: "three-cubes-fitness", version: "0.17.1" },
      adapters: [],
    },
    stateRoot: "/tmp/test-state",
    stateDirectory: "/tmp/test-state/releases/2.2.0/test/darwin-arm64",
    environment: { PATH: process.env.PATH ?? "" },
    lease: { assertCurrent: () => undefined, release: () => undefined },
    assertIdentity: () => undefined,
    verifyIntegrity: () => undefined,
  };
}

function runGraphWithContext(
  graph: unknown,
  selection: readonly string[],
  options: Record<string, any>,
) {
  return (sdlc as Record<string, any>).runGraph(graph, selection, {
    ...options,
    executionContext: options.executionContext ?? testExecutionContext(),
  });
}

describe("tc-sdlc runtime", () => {
  test("retains a terminal receipt and removes run scratch after a scheduling exception", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-schedule-failure-"));
    const graph = graphFor({ check: runtimeTarget("node -e 'process.exit(0)'") });
    const receiptPath = join(directory, "run.json");
    const before = new Set(readdirSync(tmpdir()).filter((name) => name.startsWith("tc-sdlc-run-")));

    const receipt = await runGraphWithContext(
      graph,
      [graph.tasks[0].identity],
      {
        cwd: directory,
        receiptPath,
        capacity: { cpu: 0, memoryMiB: 256 },
      },
    );

    expect(receipt).toMatchObject({
      status: "failed",
      reason: "host capacity must be positive",
      scratchCleanup: "removed",
      tasks: [{ status: "skipped", reason: "run_aborted:host capacity must be positive" }],
    });
    expect(readFileSync(receiptPath, "utf8")).toBe(sdlc.canonicalJson(receipt));
    expect(readdirSync(tmpdir()).filter((name) =>
      name.startsWith("tc-sdlc-run-") && !before.has(name),
    )).toEqual([]);
  });

  test("runs every task with an isolated writable home, temp and cache", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-isolation-"));
    writeFileSync(
      join(directory, "environment.mjs"),
      'console.log(JSON.stringify({home: process.env.HOME, temp: process.env.TMPDIR, cache: process.env.XDG_CACHE_HOME, noBytecode: process.env.PYTHONDONTWRITEBYTECODE}));\n',
    );
    const graph = graphFor({ check: runtimeTarget("node environment.mjs") });
    const receipt = await runGraphWithContext(
      graph,
      [graph.tasks[0].identity],
      {
        cwd: directory,
        receiptPath: join(directory, "receipt.json"),
        capacity: { cpu: 1, memoryMiB: 256 },
        executionContext: testExecutionContext(),
      },
    );
    const observed = JSON.parse(receipt.tasks[0].stdout.trim()) as Record<string, string>;

    expect(receipt.status).toBe("succeeded");
    expect(observed.home).toMatch(/\/tc-sdlc-run-[^/]+\/[^/]+\/home$/);
    expect(observed.temp).toMatch(/\/tc-sdlc-run-[^/]+\/[^/]+\/tmp$/);
    expect(observed.cache).toMatch(/\/tc-sdlc-run-[^/]+\/[^/]+\/cache\/xdg$/);
    expect(observed.noBytecode).toBe("1");
    expect(new Set([observed.home, observed.temp, observed.cache]).size).toBe(3);
  });

  test("rejects caller overrides of the bootstrap-owned executable environment", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-hostile-env-"));
    writeFileSync(join(directory, "check.mjs"), 'console.log("executed");\n');
    const graph = graphFor({ check: runtimeTarget("node check.mjs") });

    const receipt = await runGraphWithContext(
      graph,
      [graph.tasks[0].identity],
      {
        cwd: directory,
        receiptPath: join(directory, "receipt.json"),
        capacity: { cpu: 1, memoryMiB: 256 },
        executionContext: testExecutionContext(),
        environment: {
          PATH: join(directory, "hostile-bin"),
          VIRTUAL_ENV: join(directory, "ambient-python"),
        },
      },
    );

    expect(receipt.status).toBe("failed");
    expect(receipt.tasks[0].reason).toBe("task_environment_invalid");
    expect(receipt.tasks[0].stdout).not.toContain("executed");
  });

  test("resolves workspace packages from the prepared checkout and external packages from managed state", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-workspace-resolution-"));
    const stateEnvironment = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-workspace-state-"));
    const nodeModules = join(stateEnvironment, "node_modules");
    mkdirSync(join(directory, "packages", "workspace-b"), { recursive: true });
    mkdirSync(join(stateEnvironment, "packages", "workspace-b"), { recursive: true });
    mkdirSync(join(nodeModules, "external-package"), { recursive: true });
    for (const root of [join(directory, "packages", "workspace-b"), join(stateEnvironment, "packages", "workspace-b")]) {
      writeFileSync(join(root, "package.json"), JSON.stringify({ name: "workspace-b", type: "commonjs", exports: "./index.js" }));
    }
    writeFileSync(join(directory, "packages", "workspace-b", "index.js"), 'module.exports = "prepared";\n');
    writeFileSync(join(stateEnvironment, "packages", "workspace-b", "index.js"), 'module.exports = "stale";\n');
    symlinkSync("../packages/workspace-b", join(nodeModules, "workspace-b"), "dir");
    writeFileSync(join(nodeModules, "external-package", "package.json"), JSON.stringify({ name: "external-package", type: "commonjs", exports: "./index.js" }));
    writeFileSync(join(nodeModules, "external-package", "index.js"), 'module.exports = "managed";\n');
    writeFileSync(
      join(directory, "esm.mjs"),
      'import workspace from "workspace-b"; import external from "external-package"; console.log(`${workspace}:${external}`);\n',
    );
    writeFileSync(
      join(directory, "commonjs.cjs"),
      'console.log(`${require("workspace-b")}:${require("external-package")}`);\n',
    );
    const graph = graphFor({
      commonjs: runtimeTarget("node commonjs.cjs"),
      esm: runtimeTarget("node esm.mjs"),
    });
    const context = testExecutionContext();
    const receipt = await runGraphWithContext(graph, graph.tasks.map((task) => task.identity), {
      cwd: directory,
      receiptPath: join(directory, "receipt.json"),
      capacity: { cpu: 1, memoryMiB: 256 },
      executionContext: {
        ...context,
        environment: {
          ...context.environment,
          TC_SDLC_NODE_LAUNCHER: process.execPath,
          TC_SDLC_NODE_MODULES: nodeModules,
        },
      },
    });

    expect(receipt.status).toBe("succeeded");
    expect(receipt.tasks.map((task) => task.stdout.trim())).toEqual([
      "prepared:managed",
      "prepared:managed",
    ]);
  });

  test("redacts retained task evidence and binds source and retained digests", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-evidence-redaction-"));
    const token = "consumer-secret-7f3a";
    const raw = `token=${token}\n`;
    const retained = "token=[REDACTED]\n";
    writeFileSync(
      join(directory, "ledger.mjs"),
      'import { writeFileSync } from "node:fs"; writeFileSync(`${process.env.TC_SDLC_TASK_EVIDENCE_DIR}/ledger.txt`, `token=${process.env.TEST_API_TOKEN}\\n`);\n',
    );
    const graph = graphFor({
      check: runtimeTarget("node ledger.mjs", {
        evidence: [{ path: "ledger.txt", mediaType: "text/plain" }],
      }),
    });
    const receipt = await runGraphWithContext(
      graph,
      [graph.tasks[0].identity],
      {
        cwd: directory,
        receiptPath: join(directory, "receipt.json"),
        capacity: { cpu: 1, memoryMiB: 256 },
        executionContext: testExecutionContext(),
        environment: { TEST_API_TOKEN: token },
      },
    );
    const evidence = receipt.tasks[0].evidence[0];

    expect(receipt.status).toBe("succeeded");
    expect(receipt.tasks[0].evidence).toHaveLength(1);
    expect(evidence.content).toBe(retained);
    expect(evidence.content).not.toContain(token);
    expect(evidence.sourceDigest).toBe(`sha256:${createHash("sha256").update(raw).digest("hex")}`);
    expect(evidence.contentDigest).toBe(`sha256:${createHash("sha256").update(retained).digest("hex")}`);
    expect(readFileSync(join(directory, "receipt.json"), "utf8")).not.toContain(token);
  });

  test("redacts JSON-escaped secret values from retained evidence", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-json-redaction-"));
    const token = 'line-one"\\line-two\nline-three';
    writeFileSync(
      join(directory, "evidence.mjs"),
      'import { writeFileSync } from "node:fs"; writeFileSync(`${process.env.TC_SDLC_TASK_EVIDENCE_DIR}/result.json`, `${JSON.stringify({ token: process.env.TEST_API_TOKEN })}\\n`);\n',
    );
    const graph = graphFor({
      check: runtimeTarget("node evidence.mjs", {
        evidence: [{ path: "result.json", mediaType: "application/json" }],
      }),
    });
    const receipt = await runGraphWithContext(graph, [graph.tasks[0].identity], {
      cwd: directory,
      receiptPath: join(directory, "receipt.json"),
      capacity: { cpu: 1, memoryMiB: 256 },
      environment: { TEST_API_TOKEN: token },
    });

    expect(receipt.status).toBe("succeeded");
    expect(JSON.parse(receipt.tasks[0].evidence[0].content)).toEqual({ token: "[REDACTED]" });
    expect(readFileSync(join(directory, "receipt.json"), "utf8")).not.toContain(JSON.stringify(token).slice(1, -1));
  });

  test("rejects binary, symlinked and oversized declared task evidence without retaining bytes", async () => {
    for (const mode of ["binary", "symlink", "oversized"]) {
      const directory = mkdtempSync(join(tmpdir(), `tc-sdlc-runtime-evidence-${mode}-`));
      writeFileSync(
        join(directory, "evidence.mjs"),
        `import { writeFileSync, symlinkSync } from "node:fs";\nimport { join } from "node:path";\nconst root = process.env.TC_SDLC_TASK_EVIDENCE_DIR;\nconst evidence = join(root, "ledger.txt");\nconst mode = process.argv[2];\nif (mode === "binary") writeFileSync(evidence, Buffer.from([0xff, 0x00, 0x80]));\nelse if (mode === "symlink") { writeFileSync(join(root, "target.txt"), "must not be retained\\n"); symlinkSync("target.txt", evidence); }\nelse writeFileSync(evidence, "x".repeat(2 * 1024 * 1024 + 1));\n`,
      );
      const graph = graphFor({
        check: runtimeTarget(`node evidence.mjs ${mode}`, {
          evidence: [{ path: "ledger.txt", mediaType: "text/plain" }],
        }),
      });
      const receipt = await runGraphWithContext(
        graph,
        [graph.tasks[0].identity],
        {
          cwd: directory,
          receiptPath: join(directory, "receipt.json"),
          capacity: { cpu: 1, memoryMiB: 256 },
        },
      );

      expect(receipt.status, mode).toBe("failed");
      expect(receipt.tasks[0].reason, mode).toBe("task_evidence_invalid");
      expect(receipt.tasks[0].evidence, mode).toEqual([]);
      expect(readFileSync(join(directory, "receipt.json"), "utf8"), mode).not.toContain("must not be retained");
    }
  });

  test("retains valid partial evidence without replacing a task failure reason", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-evidence-partial-"));
    writeFileSync(
      join(directory, "partial.mjs"),
      'import { writeFileSync } from "node:fs"; writeFileSync(`${process.env.TC_SDLC_TASK_EVIDENCE_DIR}/partial.txt`, "partial result\\n"); process.exit(9);\n',
    );
    const graph = graphFor({
      check: runtimeTarget("node partial.mjs", {
        evidence: [
          { path: "partial.txt", mediaType: "text/plain" },
          { path: "missing.json", mediaType: "application/json" },
        ],
      }),
    });
    const receipt = await runGraphWithContext(
      graph,
      [graph.tasks[0].identity],
      {
        cwd: directory,
        receiptPath: join(directory, "receipt.json"),
        capacity: { cpu: 1, memoryMiB: 256 },
      },
    );

    expect(receipt.status).toBe("failed");
    expect(receipt.tasks[0].reason).toBe("process_exit_nonzero");
    expect(receipt.tasks[0].evidence).toMatchObject([
      { path: "partial.txt", content: "partial result\n" },
    ]);
    expect(receipt.tasks[0].missingEvidence).toEqual(["missing.json"]);
  });

  test("fails a successful task whose declared evidence is missing", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-evidence-missing-"));
    const graph = graphFor({
      check: runtimeTarget("node -e 'process.exit(0)'", {
        evidence: [{ path: "required.json", mediaType: "application/json" }],
      }),
    });
    const receipt = await runGraphWithContext(
      graph,
      [graph.tasks[0].identity],
      {
        cwd: directory,
        receiptPath: join(directory, "receipt.json"),
        capacity: { cpu: 1, memoryMiB: 256 },
      },
    );

    expect(receipt.status).toBe("failed");
    expect(receipt.tasks[0].reason).toBe("task_evidence_invalid");
    expect(receipt.tasks[0].missingEvidence).toEqual(["required.json"]);
  });

  test("binds declared task resources and budgets into graph identity", () => {
    const first = graphFor({
      check: {
        command: "node --version",
        mode: "evaluate",
        trustBoundary: "portable",
        resources: {
          cpu: 2,
          memoryMiB: 384,
          ports: [4173],
          exclusive: ["docker"],
        },
        budget: {
          phaseMs: 20_000,
          noProgressMs: 5_000,
          heartbeatMs: 1_000,
        },
      },
    });
    const second = graphFor({
      check: {
        command: "node --version",
        mode: "evaluate",
        trustBoundary: "portable",
        resources: {
          cpu: 1,
          memoryMiB: 384,
          ports: [4173],
          exclusive: ["docker"],
        },
        budget: {
          phaseMs: 20_000,
          noProgressMs: 5_000,
          heartbeatMs: 1_000,
        },
      },
    });

    expect(first.tasks[0]).toMatchObject({
      resources: {
        cpu: 2,
        memoryMiB: 384,
        ports: [4173],
        exclusive: ["docker"],
      },
      budget: {
        phaseMs: 20_000,
        noProgressMs: 5_000,
        heartbeatMs: 1_000,
      },
    });
    expect(first.tasks[0].identity).not.toBe(second.tasks[0].identity);
  });

  test("rejects incoherent task-owned budget intervals before execution", () => {
    expect(() =>
      graphFor({
        check: runtimeTarget("node --version", {
          budget: { phaseMs: 100, noProgressMs: 101, heartbeatMs: 10 },
        }),
      }),
    ).toThrowError(expect.objectContaining({ code: "GRAPH_BUDGET_INVALID" }));
  });

  test("runs dependencies in order and durably records lifecycle evidence", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-"));
    writeFileSync(
      join(directory, "prepare.mjs"),
      'import { writeFileSync } from "node:fs"; writeFileSync("prepared", "yes"); console.log("prepared");\n',
    );
    writeFileSync(
      join(directory, "check.mjs"),
      'import { existsSync } from "node:fs"; if (!existsSync("prepared")) process.exit(9); console.log("checked");\n',
    );
    const graph = graphFor({
      prepare: runtimeTarget("node prepare.mjs"),
      check: runtimeTarget("node check.mjs", { dependsOn: ["prepare"] }),
    });
    const receiptPath = join(directory, "run-receipt.json");
    const observed: Record<string, unknown>[] = [];

    const receipt = await runGraphWithContext(
      graph,
      graph.tasks.map((task: { identity: string }) => task.identity),
      {
        cwd: directory,
        receiptPath,
        capacity: { cpu: 2, memoryMiB: 256 },
        onEvent: (event: Record<string, unknown>) => observed.push(event),
      },
    );

    expect(receipt.status).toBe("succeeded");
    expect(receipt.tasks.map((task: Record<string, unknown>) => [task.key, task.status])).toEqual([
      ["fixture:check", "succeeded"],
      ["fixture:prepare", "succeeded"],
    ]);
    expect(
      observed
        .filter((event) => event.type !== "heartbeat" && event.type !== "terminal")
        .map((event) => [event.taskKey, event.type]),
    ).toEqual([
      ["fixture:prepare", "start"],
      ["fixture:prepare", "output"],
      ["fixture:check", "start"],
      ["fixture:check", "output"],
    ]);
    expect(observed.filter((event) => event.type === "terminal")).toEqual(
      receipt.tasks.flatMap((task: Record<string, any>) =>
        task.events.filter((event: Record<string, unknown>) => event.type === "terminal"),
      ),
    );
    expect(readFileSync(receiptPath, "utf8")).toBe(
      (sdlc as Record<string, any>).serialiseRunReceipt(receipt),
    );
  });

  test("runs every prerequisite returned by affected selection before its consumer", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-"));
    writeFileSync(
      join(directory, "prepare.mjs"),
      'import { writeFileSync } from "node:fs"; writeFileSync("prepared", "yes");\n',
    );
    writeFileSync(
      join(directory, "check.mjs"),
      'import { existsSync } from "node:fs"; if (!existsSync("prepared")) process.exit(9); console.log("checked");\n',
    );
    const graph = graphFor({
      prepare: runtimeTarget("node prepare.mjs", {
        inputs: ["prepare.trigger"],
      }),
      check: runtimeTarget("node check.mjs", {
        dependsOn: ["prepare"],
        inputs: ["check.trigger"],
      }),
    });
    const selection = (sdlc as Record<string, any>).selectAffected(graph, [
      "check.trigger",
    ]);

    const receipt = await runGraphWithContext(
      graph,
      selection,
      {
        cwd: directory,
        receiptPath: join(directory, "run-receipt.json"),
        capacity: { cpu: 2, memoryMiB: 256 },
      },
    );

    expect(
      graph.tasks
        .filter((task: { identity: string }) => selection.includes(task.identity))
        .map((task: { key: string }) => task.key),
    ).toEqual(["fixture:check", "fixture:prepare"]);
    expect(receipt.status).toBe("succeeded");
    expect(receipt.tasks.map((task: Record<string, unknown>) => task.status)).toEqual([
      "succeeded",
      "succeeded",
    ]);
  });

  test("rejects a caller selection that omits a required dependency", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-"));
    const receiptPath = join(directory, "run-receipt.json");
    const graph = graphFor({
      prepare: runtimeTarget(
        'node -e \'require("node:fs").writeFileSync("prepare-started", "yes")\'',
      ),
      check: runtimeTarget(
        'node -e \'require("node:fs").writeFileSync("check-started", "yes")\'',
        { dependsOn: ["prepare"] },
      ),
    });
    const check = graph.tasks.find(
      (task: { key: string }) => task.key === "fixture:check",
    );

    await expect(
      runGraphWithContext(graph, [check.identity], {
        cwd: directory,
        receiptPath,
        capacity: { cpu: 1, memoryMiB: 256 },
      }),
    ).rejects.toMatchObject({ code: "RUN_SELECTION_INVALID" });
    expect(existsSync(receiptPath)).toBe(false);
    expect(existsSync(join(directory, "prepare-started"))).toBe(false);
    expect(existsSync(join(directory, "check-started"))).toBe(false);
  });

  test("runs independent ready tasks concurrently within injected capacity", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-"));
    const rendezvous = (self: string, peer: string) => `
import { existsSync, writeFileSync } from "node:fs";
import { setTimeout as delay } from "node:timers/promises";
writeFileSync("${self}.ready", "ready");
const deadline = Date.now() + 1500;
while (!existsSync("${peer}.ready") && Date.now() < deadline) await delay(10);
if (!existsSync("${peer}.ready")) process.exit(7);
console.log("${self}-met-${peer}");
`;
    writeFileSync(join(directory, "left.mjs"), rendezvous("left", "right"));
    writeFileSync(join(directory, "right.mjs"), rendezvous("right", "left"));
    const graph = graphFor({
      left: runtimeTarget("node left.mjs"),
      right: runtimeTarget("node right.mjs"),
    });

    const receipt = await runGraphWithContext(
      graph,
      graph.tasks.map((task: { identity: string }) => task.identity),
      {
        cwd: directory,
        receiptPath: join(directory, "run-receipt.json"),
        capacity: { cpu: 2, memoryMiB: 128 },
      },
    );

    expect(receipt.status).toBe("succeeded");
    expect(receipt.tasks.map((task: Record<string, unknown>) => task.status)).toEqual([
      "succeeded",
      "succeeded",
    ]);
  });

  test.each([
    [
      "CPU",
      { cpu: 1, memoryMiB: 32, ports: [], exclusive: [] },
      { cpu: 1, memoryMiB: 256 },
    ],
    [
      "memory",
      { cpu: 1, memoryMiB: 96, ports: [], exclusive: [] },
      { cpu: 2, memoryMiB: 128 },
    ],
    [
      "port",
      { cpu: 1, memoryMiB: 32, ports: [4173], exclusive: [] },
      { cpu: 2, memoryMiB: 256 },
    ],
    [
      "exclusive resource",
      { cpu: 1, memoryMiB: 32, ports: [], exclusive: ["docker"] },
      { cpu: 2, memoryMiB: 256 },
    ],
  ])("does not oversubscribe declared %s capacity", async (_name, resources, capacity) => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-"));
    writeFileSync(
      join(directory, "claim.mjs"),
      `
import { closeSync, openSync, unlinkSync } from "node:fs";
import { setTimeout as delay } from "node:timers/promises";
let descriptor;
try {
  descriptor = openSync("claimed", "wx");
} catch {
  process.exit(8);
}
await delay(150);
closeSync(descriptor);
unlinkSync("claimed");
console.log("released");
`,
    );
    const target = () =>
      runtimeTarget("node claim.mjs", { resources });
    const graph = graphFor({ first: target(), second: target() });

    const receipt = await runGraphWithContext(
      graph,
      graph.tasks.map((task: { identity: string }) => task.identity),
      {
        cwd: directory,
        receiptPath: join(directory, "run-receipt.json"),
        capacity,
      },
    );

    expect(receipt.status).toBe("succeeded");
    expect(receipt.tasks.map((task: Record<string, unknown>) => task.status)).toEqual([
      "succeeded",
      "succeeded",
    ]);
  });

  test("records an unschedulable resource claim without starting the task", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-"));
    const graph = graphFor({
      oversized: runtimeTarget("node -e 'process.exit(91)'", {
        resources: {
          cpu: 3,
          memoryMiB: 513,
          ports: [],
          exclusive: [],
        },
      }),
    });

    const receipt = await runGraphWithContext(
      graph,
      [graph.tasks[0].identity],
      {
        cwd: directory,
        receiptPath: join(directory, "run-receipt.json"),
        capacity: { cpu: 2, memoryMiB: 512 },
      },
    );

    expect(receipt).toMatchObject({
      status: "failed",
      tasks: [
        {
          key: "fixture:oversized",
          status: "failed",
          exitCode: null,
          reason: "resource_capacity_exceeded",
          events: [
            {
              type: "terminal",
              status: "failed",
              reason: "resource_capacity_exceeded",
            },
          ],
        },
      ],
    });
  });

  test("blocks dependants after failure while independent work completes", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-"));
    const graph = graphFor({
      fail: runtimeTarget("node -e 'process.exit(3)'"),
      blocked: runtimeTarget(
        "node -e 'require(\"node:fs\").writeFileSync(\"forbidden\", \"ran\")'",
        { dependsOn: ["fail"] },
      ),
      independent: runtimeTarget("node -e 'console.log(\"independent\")'"),
    });
    const observed: Record<string, unknown>[] = [];

    const receipt = await runGraphWithContext(
      graph,
      graph.tasks.map((task: { identity: string }) => task.identity),
      {
        cwd: directory,
        receiptPath: join(directory, "run-receipt.json"),
        capacity: { cpu: 2, memoryMiB: 256 },
        onEvent: (event: Record<string, unknown>) => observed.push(event),
      },
    );

    expect(receipt.status).toBe("failed");
    expect(
      receipt.tasks.map((task: Record<string, unknown>) => [
        task.key,
        task.status,
        task.reason,
      ]),
    ).toEqual([
      ["fixture:blocked", "skipped", "dependency_failed:fixture:fail"],
      ["fixture:fail", "failed", "process_exit_nonzero"],
      ["fixture:independent", "succeeded", null],
    ]);
    expect(existsSync(join(directory, "forbidden"))).toBe(false);
    expect(observed).toContainEqual(
      expect.objectContaining({
        taskKey: "fixture:blocked",
        type: "terminal",
        status: "skipped",
      }),
    );
  });

  test.each([
    ["duplicate", (identity: string) => [identity, identity]],
    [
      "unknown",
      () => [
        "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
      ],
    ],
  ])("rejects a %s selection before execution", async (_name, select) => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-"));
    const graph = graphFor({ check: runtimeTarget("node -e 'process.exit(91)'") });
    const receiptPath = join(directory, "run-receipt.json");

    await expect(
      runGraphWithContext(
        graph,
        select(graph.tasks[0].identity),
        {
          cwd: directory,
          receiptPath,
          capacity: { cpu: 1, memoryMiB: 256 },
        },
      ),
    ).rejects.toMatchObject({ code: "RUN_SELECTION_INVALID" });
    expect(existsSync(receiptPath)).toBe(false);
  });

  test("emits heartbeat events between progress output and terminal state", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-"));
    writeFileSync(
      join(directory, "heartbeat.mjs"),
      `
import { setTimeout as delay } from "node:timers/promises";
console.log("first");
await delay(220);
console.log("second");
`,
    );
    const graph = graphFor({
      heartbeat: runtimeTarget("node heartbeat.mjs", {
        budget: { phaseMs: 2_000, noProgressMs: 500, heartbeatMs: 50 },
      }),
    });
    const observed: Record<string, unknown>[] = [];

    const receipt = await runGraphWithContext(
      graph,
      [graph.tasks[0].identity],
      {
        cwd: directory,
        receiptPath: join(directory, "run-receipt.json"),
        capacity: { cpu: 1, memoryMiB: 256 },
        onEvent: (event: Record<string, unknown>) => observed.push(event),
      },
    );

    const types = observed.map((event) => event.type);
    const outputIndexes = types
      .map((type, index) => (type === "output" ? index : -1))
      .filter((index) => index >= 0);
    const heartbeatIndexes = types
      .map((type, index) => (type === "heartbeat" ? index : -1))
      .filter((index) => index >= 0);
    expect(receipt.status).toBe("succeeded");
    expect(types[0]).toBe("start");
    expect(types.at(-1)).toBe("terminal");
    expect(outputIndexes).toHaveLength(2);
    expect(
      heartbeatIndexes.some(
        (index) =>
          index > (outputIndexes[0] as number) &&
          index < (outputIndexes[1] as number),
      ),
    ).toBe(true);
  });

  test("captures diagnostics and kills the process group on no-progress stall", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-"));
    writeFileSync(
      join(directory, "grandchild.mjs"),
      `
import { writeFileSync } from "node:fs";
import { setTimeout as delay } from "node:timers/promises";
await delay(300);
writeFileSync("survivor", "alive");
`,
    );
    writeFileSync(
      join(directory, "staller.mjs"),
      `
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
spawn(process.execPath, ["grandchild.mjs"], { stdio: "ignore" });
await delay(500);
`,
    );
    const graph = graphFor({
      stall: runtimeTarget("node staller.mjs", {
        budget: { phaseMs: 2_000, noProgressMs: 100, heartbeatMs: 30 },
      }),
    });

    const receipt = await runGraphWithContext(
      graph,
      [graph.tasks[0].identity],
      {
        cwd: directory,
        receiptPath: join(directory, "run-receipt.json"),
        capacity: { cpu: 1, memoryMiB: 256 },
        terminationGraceMs: 50,
      },
    );
    await new Promise((resolve) => setTimeout(resolve, 400));

    expect(receipt).toMatchObject({
      status: "stalled",
      tasks: [
        {
          status: "stalled",
          exitCode: null,
          reason: "no_progress",
          diagnostic: {
            running: true,
            cpu: 1,
            memoryMiB: 64,
            ports: [],
            exclusive: [],
            stdoutBytes: 0,
            stderrBytes: 0,
            processes: expect.arrayContaining([
              expect.objectContaining({
                pid: expect.any(Number),
                parentPid: expect.any(Number),
                cpuPercent: expect.any(Number),
                residentMemoryKiB: expect.any(Number),
              }),
            ]),
          },
        },
      ],
    });
    expect(receipt.tasks[0].diagnostic.pid).toBeGreaterThan(0);
    expect(receipt.tasks[0].events.map((event: Record<string, unknown>) => [event.type, event.reason])).toContainEqual([
      "cancellation",
      "no_progress",
    ]);
    expect(existsSync(join(directory, "survivor"))).toBe(false);
  });

  test("records phase-budget expiry as failed rather than stalled", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-"));
    writeFileSync(
      join(directory, "phase.mjs"),
      `
import { setTimeout as delay } from "node:timers/promises";
for (let index = 0; index < 20; index += 1) {
  console.log("progress");
  await delay(30);
}
`,
    );
    const graph = graphFor({
      phase: runtimeTarget("node phase.mjs", {
        budget: { phaseMs: 120, noProgressMs: 100, heartbeatMs: 20 },
      }),
    });

    const receipt = await runGraphWithContext(
      graph,
      [graph.tasks[0].identity],
      {
        cwd: directory,
        receiptPath: join(directory, "run-receipt.json"),
        capacity: { cpu: 1, memoryMiB: 256 },
        terminationGraceMs: 50,
      },
    );

    expect(receipt).toMatchObject({
      status: "failed",
      tasks: [
        {
          status: "failed",
          exitCode: null,
          reason: "phase_budget_exceeded",
        },
      ],
    });
    expect(receipt.tasks[0].diagnostic).toBeUndefined();
    expect(receipt.tasks[0].events).toContainEqual(
      expect.objectContaining({
        type: "cancellation",
        reason: "phase_budget_exceeded",
      }),
    );
  });

  test("records operator cancellation and kills descendant processes", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-"));
    writeFileSync(
      join(directory, "abort-child.mjs"),
      `
import { writeFileSync } from "node:fs";
import { setTimeout as delay } from "node:timers/promises";
await delay(300);
writeFileSync("abort-survivor", "alive");
`,
    );
    writeFileSync(
      join(directory, "abort-parent.mjs"),
      `
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
spawn(process.execPath, ["abort-child.mjs"], { stdio: "ignore" });
console.log("started");
await delay(500);
`,
    );
    const graph = graphFor({
      abort: runtimeTarget("node abort-parent.mjs", {
        budget: { phaseMs: 2_000, noProgressMs: 1_000, heartbeatMs: 30 },
      }),
    });
    const controller = new AbortController();
    setTimeout(() => controller.abort(), 80);

    const receipt = await runGraphWithContext(
      graph,
      [graph.tasks[0].identity],
      {
        cwd: directory,
        receiptPath: join(directory, "run-receipt.json"),
        capacity: { cpu: 1, memoryMiB: 256 },
        terminationGraceMs: 50,
        signal: controller.signal,
      },
    );
    await new Promise((resolve) => setTimeout(resolve, 400));

    expect(receipt).toMatchObject({
      status: "cancelled",
      tasks: [
        {
          status: "cancelled",
          exitCode: null,
          reason: "operator_abort",
        },
      ],
    });
    expect(receipt.tasks[0].events).toContainEqual(
      expect.objectContaining({
        type: "cancellation",
        reason: "operator_abort",
      }),
    );
    expect(existsSync(join(directory, "abort-survivor"))).toBe(false);
  });

  test("cancels queued tasks without starting them after an operator abort", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-"));
    writeFileSync(
      join(directory, "running.mjs"),
      `
import { setTimeout as delay } from "node:timers/promises";
console.log("running");
await delay(500);
`,
    );
    writeFileSync(
      join(directory, "queued.mjs"),
      'import { writeFileSync } from "node:fs"; writeFileSync("queued-started", "yes");\n',
    );
    const graph = graphFor({
      active: runtimeTarget("node running.mjs"),
      queued: runtimeTarget("node queued.mjs"),
    });
    const observed: Record<string, unknown>[] = [];
    const controller = new AbortController();
    setTimeout(() => controller.abort(), 80);

    const receipt = await runGraphWithContext(
      graph,
      graph.tasks.map((task: { identity: string }) => task.identity),
      {
        cwd: directory,
        receiptPath: join(directory, "run-receipt.json"),
        capacity: { cpu: 1, memoryMiB: 256 },
        terminationGraceMs: 50,
        signal: controller.signal,
        onEvent: (event: Record<string, unknown>) => observed.push(event),
      },
    );

    expect(receipt.status).toBe("cancelled");
    expect(
      receipt.tasks.map((task: Record<string, unknown>) => [
        task.key,
        task.status,
        task.reason,
      ]),
    ).toEqual([
      ["fixture:active", "cancelled", "operator_abort"],
      ["fixture:queued", "cancelled", "operator_abort"],
    ]);
    expect(
      observed.some(
        (event) =>
          event.taskKey === "fixture:queued" && event.type === "start",
      ),
    ).toBe(false);
    expect(existsSync(join(directory, "queued-started"))).toBe(false);
  });

  test("bounds retained output and redacts secrets from events and durable evidence", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-"));
    const secret = "tc-super-secret-value";
    writeFileSync(
      join(directory, "output.mjs"),
      `
console.log("stdout:${secret}:" + "x".repeat(300));
console.error("stderr:${secret}:" + "y".repeat(300));
`,
    );
    const graph = graphFor({ output: runtimeTarget("node output.mjs") });
    const receiptPath = join(directory, "run-receipt.json");
    const observed: Record<string, unknown>[] = [];

    const receipt = await runGraphWithContext(
      graph,
      [graph.tasks[0].identity],
      {
        cwd: directory,
        receiptPath,
        capacity: { cpu: 1, memoryMiB: 256 },
        maxOutputBytes: 80,
        redactions: [secret],
        onEvent: (event: Record<string, unknown>) => observed.push(event),
      },
    );

    const evidence = readFileSync(receiptPath, "utf8");
    expect(receipt.status).toBe("succeeded");
    expect(receipt.tasks[0].outputTruncated).toBe(true);
    expect(Buffer.byteLength(receipt.tasks[0].stdout)).toBeLessThanOrEqual(80);
    expect(Buffer.byteLength(receipt.tasks[0].stderr)).toBeLessThanOrEqual(80);
    expect(evidence).not.toContain(secret);
    expect(JSON.stringify(observed)).not.toContain(secret);
    expect(evidence).toContain("[REDACTED]");
  });

  test("preserves task identities and outcomes across scheduler concurrency levels", async () => {
    const firstDirectory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-"));
    const secondDirectory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-"));
    const script = `
import { setTimeout as delay } from "node:timers/promises";
await delay(Number(process.argv[2]));
console.log(process.argv[3]);
`;
    for (const directory of [firstDirectory, secondDirectory]) {
      writeFileSync(join(directory, "timed.mjs"), script);
    }
    const graph = graphFor({
      left: runtimeTarget("node timed.mjs 150 left", {
        budget: { phaseMs: 2_000, noProgressMs: 1_000, heartbeatMs: 500 },
      }),
      right: runtimeTarget("node timed.mjs 20 right", {
        budget: { phaseMs: 2_000, noProgressMs: 1_000, heartbeatMs: 500 },
      }),
    });
    const selection = graph.tasks.map((task: { identity: string }) => task.identity);

    const serial = await runGraphWithContext(graph, selection, {
      cwd: firstDirectory,
      receiptPath: join(firstDirectory, "run-receipt.json"),
      capacity: { cpu: 1, memoryMiB: 256 },
    });
    const concurrent = await runGraphWithContext(
      graph,
      selection,
      {
        cwd: secondDirectory,
        receiptPath: join(secondDirectory, "run-receipt.json"),
        capacity: { cpu: 2, memoryMiB: 256 },
      },
    );

    const stableTaskEvidence = (receipt: Record<string, any>) => receipt.tasks
      .map((task: Record<string, any>) => ({
        key: task.key,
        identity: task.identity,
        status: task.status,
        exitCode: task.exitCode,
        executionContextDigest: task.executionContextDigest,
        resources: task.resources,
      }))
      .sort((left: Record<string, any>, right: Record<string, any>) => left.key.localeCompare(right.key));
    expect(concurrent.bootstrapContext).toEqual(serial.bootstrapContext);
    expect(stableTaskEvidence(concurrent)).toEqual(stableTaskEvidence(serial));
  });

  test("performs one full bootstrap integrity check per graph run, not per task", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-integrity-count-"));
    let fullChecks = 0;
    const executionContext = {
      ...testExecutionContext(),
      verifyIntegrity: () => { fullChecks += 1; },
    };
    const graph = graphFor({
      first: runtimeTarget("node -e 'process.exit(0)'"),
      second: runtimeTarget("node -e 'process.exit(0)'"),
      third: runtimeTarget("node -e 'process.exit(0)'"),
    });
    const receipt = await runGraphWithContext(
      graph,
      graph.tasks.map((task: { identity: string }) => task.identity),
      {
        cwd: directory,
        receiptPath: join(directory, "run-receipt.json"),
        capacity: { cpu: 2, memoryMiB: 768 },
        executionContext,
      },
    );

    expect(receipt.status).toBe("succeeded");
    expect(fullChecks).toBe(1);
  });

  test("rejects concurrent task evidence when one task mutates the leased state", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-state-integrity-"));
    const statePath = join(directory, "state.json");
    writeFileSync(statePath, "original state\n");
    const expected = readFileSync(statePath, "utf8");
    const attacker = join(directory, "mutate.mjs");
    const observer = join(directory, "observe.mjs");
    writeFileSync(
      attacker,
      `import { writeFileSync } from "node:fs";\nimport { setTimeout as delay } from "node:timers/promises";\nawait delay(50); writeFileSync(${JSON.stringify(statePath)}, "mutated state\\n"); console.log("mutation attempted");\n`,
    );
    writeFileSync(
      observer,
      'import { setTimeout as delay } from "node:timers/promises"; await delay(250); console.log("observer completed");\n',
    );
    const graph = graphFor({
      mutate: runtimeTarget("node mutate.mjs"),
      observe: runtimeTarget("node observe.mjs"),
    });
    const executionContext = {
      ...testExecutionContext(),
      assertIdentity: () => undefined,
      verifyIntegrity: () => {
        if (readFileSync(statePath, "utf8") !== expected) {
          throw new Error("bootstrap state content changed");
        }
      },
    };
    const receiptPath = join(directory, "run-receipt.json");
    const observedEvents: Array<Record<string, unknown>> = [];
    const receipt = await runGraphWithContext(
      graph,
      graph.tasks.map((task: { identity: string }) => task.identity),
      {
        cwd: directory,
        receiptPath,
        capacity: { cpu: 2, memoryMiB: 256 },
        executionContext,
        onEvent: (event: Record<string, unknown>) => observedEvents.push(event),
      },
    );

    expect(receipt.status).toBe("failed");
    expect(receipt.reason).toBe("bootstrap_state_changed");
    expect(receipt.tasks.map((task: Record<string, unknown>) => task.status)).toEqual([
      "failed",
      "failed",
    ]);
    expect(receipt.tasks.map((task: Record<string, unknown>) => task.reason)).toEqual([
      "bootstrap_state_changed",
      "bootstrap_state_changed",
    ]);
    expect(readFileSync(receiptPath, "utf8")).toContain("bootstrap_state_changed");
    expect(observedEvents.filter((event) => event.type === "terminal")).toEqual(
      receipt.tasks.flatMap((task: Record<string, any>) =>
        task.events.filter((event: Record<string, unknown>) => event.type === "terminal"),
      ),
    );
  });

  test("fails closed when durable receipt replacement cannot complete", async () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-"));
    const graph = graphFor({ check: runtimeTarget("node -e 'process.exit(0)'") });

    await expect(
      runGraphWithContext(
        graph,
        [graph.tasks[0].identity],
        {
          cwd: directory,
          receiptPath: directory,
          capacity: { cpu: 1, memoryMiB: 256 },
        },
      ),
    ).rejects.toBeInstanceOf(Error);
    expect(existsSync(`${directory}.tmp-${process.pid}`)).toBe(false);
  });

  test("rejects unserialisable receipt evidence without creating a file", () => {
    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-runtime-"));
    const path = join(directory, "invalid.json");
    const invalid: Record<string, unknown> = {};
    invalid.self = invalid;

    expect(() =>
      (sdlc as Record<string, any>).writeRunReceipt(path, invalid),
    ).toThrow();
    expect(existsSync(path)).toBe(false);
    expect(existsSync(`${path}.tmp-${process.pid}`)).toBe(false);
  });

  test.each([
    [
      "cgroup v2 quotas",
      {
        logicalCpu: 8,
        totalMemoryBytes: 8 * 1024 * 1024 * 1024,
        cgroupV2CpuMax: "150000 100000",
        cgroupV2MemoryMax: "536870912",
      },
      { cpu: 1.5, memoryMiB: 512 },
    ],
    [
      "cgroup v1 quotas",
      {
        logicalCpu: 8,
        totalMemoryBytes: 8 * 1024 * 1024 * 1024,
        cgroupV1CpuQuotaMicros: 200000,
        cgroupV1CpuPeriodMicros: 100000,
        cgroupV1MemoryLimitBytes: 1073741824,
      },
      { cpu: 2, memoryMiB: 1024 },
    ],
    [
      "unlimited fallback",
      {
        logicalCpu: 8,
        totalMemoryBytes: 4 * 1024 * 1024 * 1024,
        cgroupV2CpuMax: "max 100000",
        cgroupV2MemoryMax: "max",
      },
      { cpu: 8, memoryMiB: 4096 },
    ],
  ])("resolves %s host capacity", (_name, input, expected) => {
    expect((sdlc as Record<string, any>).resolveHostCapacity(input)).toEqual(
      expected,
    );
  });
});
