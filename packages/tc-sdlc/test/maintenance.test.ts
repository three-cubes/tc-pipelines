import * as sdlc from "../dist/index.js";
import { execFileSync, spawnSync } from "node:child_process";
import {
  chmodSync,
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  realpathSync,
  rmSync,
  symlinkSync,
  utimesSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, test } from "vitest";

const CLI = fileURLToPath(new URL("../dist/cli.js", import.meta.url));
const UV = ["/opt/homebrew/bin/uv", "/usr/local/bin/uv", "/usr/bin/uv"]
  .filter(existsSync)
  .map((path) => realpathSync(path))
  .find((path) => lstatSync(path).isFile());
const roots: string[] = [];

function temporary(prefix: string): string {
  const root = mkdtempSync(join(tmpdir(), prefix));
  roots.push(root);
  return root;
}

function ownedState(root: string): void {
  mkdirSync(root, { recursive: true, mode: 0o700 });
  writeFileSync(
    join(root, ".tc-sdlc-owner.json"),
    sdlc.canonicalJson({
      schema: "tc.sdlc/state-owner/v1",
      owner: "@three-cubes/tc-sdlc",
    }),
    { mode: 0o600 },
  );
}

function managedTemporary(
  parent: string,
  name: string,
  options: Readonly<{ pid: number; old: boolean; git?: "clean" | "dirty" }>,
): string {
  const directory = join(parent, name);
  mkdirSync(directory, { mode: 0o700 });
  writeFileSync(
    join(directory, ".tc-sdlc-temporary.json"),
    sdlc.canonicalJson({
      schema: "tc.sdlc/temporary-owner/v1",
      owner: "@three-cubes/tc-sdlc",
      kind: "evaluation-workspace",
      pid: options.pid,
    }),
    { mode: 0o600 },
  );
  if (options.git !== undefined) {
    execFileSync("git", ["init", "--quiet"], { cwd: directory });
    writeFileSync(join(directory, "tracked.txt"), "tracked\n");
    execFileSync("git", ["add", "tracked.txt"], { cwd: directory });
    execFileSync(
      "git",
      [
        "-c",
        "user.name=Lifecycle Test",
        "-c",
        "user.email=lifecycle@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "fixture",
      ],
      { cwd: directory },
    );
    if (options.git === "dirty") writeFileSync(join(directory, "tracked.txt"), "dirty\n");
  }
  if (options.old) {
    const old = new Date(Date.now() - 49 * 60 * 60 * 1_000);
    for (const path of [join(directory, ".tc-sdlc-temporary.json"), directory]) {
      utimesSync(path, old, old);
    }
  }
  return directory;
}

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

describe("tc-sdlc managed lifecycle", () => {
  test("dry-run reports only aged owned temporary state and never mutates", async () => {
    const parent = temporary("tc-sdlc-maintenance-temp-");
    const stateRoot = temporary("tc-sdlc-maintenance-state-");
    const evidence = temporary("tc-sdlc-maintenance-evidence-");
    ownedState(stateRoot);
    const expired = managedTemporary(parent, "tc-sdlc-evaluation-expired", {
      pid: 2_147_483_647,
      old: true,
      git: "clean",
    });
    const recent = managedTemporary(parent, "tc-sdlc-evaluation-recent", {
      pid: 2_147_483_647,
      old: false,
      git: "clean",
    });
    const foreign = join(parent, "tc-sdlc-evaluation-foreign");
    mkdirSync(foreign);
    writeFileSync(join(foreign, "keep"), "foreign\n");
    const wrongKind = managedTemporary(parent, "tc-sdlc-evaluation-wrong-kind", {
      pid: 2_147_483_647,
      old: true,
    });
    writeFileSync(
      join(wrongKind, ".tc-sdlc-temporary.json"),
      sdlc.canonicalJson({
        schema: "tc.sdlc/temporary-owner/v1",
        owner: "@three-cubes/tc-sdlc",
        kind: "user-data",
        pid: 2_147_483_647,
      }),
    );

    const receipt = await (sdlc as Record<string, any>).maintain({
      stateRoot,
      temporaryRoot: parent,
      receiptPath: join(evidence, "dry-run.json"),
      mode: "dry-run",
    });

    expect(receipt).toMatchObject({
      schema: "tc.sdlc/maintenance-receipt/v1",
      status: "succeeded",
      mode: "dry-run",
      retentionHours: 48,
      candidateCount: 1,
      removedCount: 0,
      reclaimedBytes: 0,
      candidates: [{ kind: "temporary", path: "tc-sdlc-evaluation-expired" }],
    });
    expect(existsSync(expired)).toBe(true);
    expect(existsSync(recent)).toBe(true);
    expect(readFileSync(join(foreign, "keep"), "utf8")).toBe("foreign\n");
    expect(existsSync(wrongKind)).toBe(true);
    expect(readFileSync(join(evidence, "dry-run.json"), "utf8")).toBe(
      sdlc.serialiseMaintenanceReceipt(receipt),
    );

    const bounded = await sdlc.maintain({
      stateRoot,
      temporaryRoot: parent,
      receiptPath: join(evidence, "bounded.json"),
      mode: "dry-run",
      maxEntries: 1,
    });
    expect(bounded).toMatchObject({ entriesTruncated: true });
    expect(bounded.candidates.length + bounded.retained.length).toBe(1);
  });

  test("apply removes expired clean state but retains active, dirty, recent, foreign and linked paths", async () => {
    const parent = temporary("tc-sdlc-maintenance-apply-");
    const stateRoot = temporary("tc-sdlc-maintenance-state-");
    const evidence = temporary("tc-sdlc-maintenance-evidence-");
    ownedState(stateRoot);
    const expired = managedTemporary(parent, "tc-sdlc-evaluation-expired", {
      pid: 2_147_483_647,
      old: true,
      git: "clean",
    });
    const active = managedTemporary(parent, "tc-sdlc-evaluation-active", {
      pid: process.pid,
      old: true,
      git: "clean",
    });
    const dirty = managedTemporary(parent, "tc-sdlc-evaluation-dirty", {
      pid: 2_147_483_647,
      old: true,
      git: "dirty",
    });
    const recent = managedTemporary(parent, "tc-sdlc-evaluation-recent", {
      pid: 2_147_483_647,
      old: false,
      git: "clean",
    });
    const foreign = join(parent, "tc-sdlc-evaluation-foreign");
    mkdirSync(foreign);
    const outside = temporary("tc-sdlc-maintenance-outside-");
    const linked = join(parent, "tc-sdlc-evaluation-linked");
    symlinkSync(outside, linked);

    const receipt = await (sdlc as Record<string, any>).maintain({
      stateRoot,
      temporaryRoot: parent,
      receiptPath: join(evidence, "apply.json"),
      mode: "apply",
    });

    expect(receipt).toMatchObject({
      status: "succeeded",
      candidateCount: 1,
      removedCount: 1,
      retained: expect.arrayContaining([
        { path: "tc-sdlc-evaluation-active", reason: "active" },
        { path: "tc-sdlc-evaluation-dirty", reason: "dirty_worktree" },
        { path: "tc-sdlc-evaluation-recent", reason: "retention_window" },
      ]),
    });
    expect(existsSync(expired)).toBe(false);
    for (const path of [active, dirty, recent, foreign, linked, outside]) {
      expect(lstatSync(path)).toBeDefined();
    }
  });

  test("bounds parallel cleanup of independent owned roots and removes read-only fixture files", async () => {
    const parent = temporary("tc-sdlc-maintenance-parallel-");
    const stateRoot = temporary("tc-sdlc-maintenance-state-");
    const evidence = temporary("tc-sdlc-maintenance-evidence-");
    ownedState(stateRoot);
    const paths = Array.from({ length: 6 }, (_, index) =>
      managedTemporary(parent, `tc-sdlc-evaluation-parallel-${index}`, {
        pid: 2_147_483_647,
        old: true,
      }),
    );
    for (const path of paths) {
      mkdirSync(join(path, "nested"));
      const file = join(path, "nested", "read-only.txt");
      writeFileSync(file, "fixture\n");
      chmodSync(file, 0o444);
      const old = new Date(Date.now() - 49 * 60 * 60 * 1_000);
      utimesSync(path, old, old);
    }

    const receipt = await sdlc.maintain({
      stateRoot,
      temporaryRoot: parent,
      receiptPath: join(evidence, "parallel.json"),
      mode: "apply",
      cleanupWorkers: 2,
    });

    expect(receipt).toMatchObject({
      status: "succeeded",
      cleanupWorkers: 2,
      candidateCount: 6,
      removedCount: 6,
    });
    expect(paths.some(existsSync)).toBe(false);
  });

  test("rejects foreign state and unowned BuildKit identities without deleting bytes", async () => {
    const parent = temporary("tc-sdlc-maintenance-reject-");
    const foreignState = temporary("tc-sdlc-maintenance-foreign-state-");
    const evidence = temporary("tc-sdlc-maintenance-evidence-");
    writeFileSync(join(foreignState, "keep"), "user-data\n");

    const foreign = await (sdlc as Record<string, any>).maintain({
      stateRoot: foreignState,
      temporaryRoot: parent,
      receiptPath: join(evidence, "foreign.json"),
      mode: "apply",
    });
    expect(foreign).toMatchObject({ status: "failed", reason: "foreign_state" });
    expect(readFileSync(join(foreignState, "keep"), "utf8")).toBe("user-data\n");

    const ownedTarget = temporary("tc-sdlc-maintenance-owned-target-");
    ownedState(ownedTarget);
    writeFileSync(join(ownedTarget, "keep"), "owned-target\n");
    const linkedState = join(parent, "linked-state");
    symlinkSync(ownedTarget, linkedState);
    const linked = await sdlc.maintain({
      stateRoot: linkedState,
      temporaryRoot: parent,
      receiptPath: join(evidence, "linked-state.json"),
      mode: "apply",
    });
    expect(linked).toMatchObject({ status: "failed", reason: "foreign_state" });
    expect(readFileSync(join(ownedTarget, "keep"), "utf8")).toBe("owned-target\n");

    const stateRoot = temporary("tc-sdlc-maintenance-state-");
    ownedState(stateRoot);
    const docker = await (sdlc as Record<string, any>).maintain({
      stateRoot,
      temporaryRoot: parent,
      receiptPath: join(evidence, "docker.json"),
      mode: "dry-run",
      dockerBuilder: "default",
    });
    expect(docker).toMatchObject({ status: "failed", reason: "docker_builder_unowned" });

    const retained = managedTemporary(parent, "tc-sdlc-evaluation-worker-limit", {
      pid: 2_147_483_647,
      old: true,
    });
    const excessiveWorkers = await sdlc.maintain({
      stateRoot,
      temporaryRoot: parent,
      receiptPath: join(evidence, "workers.json"),
      mode: "apply",
      cleanupWorkers: 17,
    });
    expect(excessiveWorkers).toMatchObject({ status: "failed", reason: "invalid_options" });
    expect(existsSync(retained)).toBe(true);
  });

  test.runIf(UV !== undefined)(
    "uses uv's public prune boundary only inside owned non-linked cache state",
    async () => {
      const parent = temporary("tc-sdlc-maintenance-uv-");
      const evidence = temporary("tc-sdlc-maintenance-evidence-");
      const stateRoot = temporary("tc-sdlc-maintenance-state-");
      ownedState(stateRoot);

      const dry = await sdlc.maintain({
        stateRoot,
        temporaryRoot: parent,
        receiptPath: join(evidence, "uv-dry.json"),
        mode: "dry-run",
        uvExecutable: UV!,
      });
      expect(dry).toMatchObject({
        status: "succeeded",
        platform: process.platform,
        tools: { uv: { status: "planned" } },
      });
      expect(existsSync(join(stateRoot, "cache"))).toBe(false);

      const applied = await sdlc.maintain({
        stateRoot,
        temporaryRoot: parent,
        receiptPath: join(evidence, "uv-apply.json"),
        mode: "apply",
        uvExecutable: UV!,
      });
      expect(applied).toMatchObject({
        status: "succeeded",
        tools: { uv: { status: "pruned" } },
      });

      const linkedState = temporary("tc-sdlc-maintenance-state-");
      ownedState(linkedState);
      const outside = temporary("tc-sdlc-maintenance-user-cache-");
      writeFileSync(join(outside, "keep"), "user-cache\n");
      mkdirSync(join(linkedState, "cache"));
      symlinkSync(outside, join(linkedState, "cache", "uv"));
      const rejected = await sdlc.maintain({
        stateRoot: linkedState,
        temporaryRoot: parent,
        receiptPath: join(evidence, "uv-linked.json"),
        mode: "apply",
        uvExecutable: UV!,
      });
      expect(rejected).toMatchObject({ status: "failed", reason: "uv_cache_unowned" });
      expect(readFileSync(join(outside, "keep"), "utf8")).toBe("user-cache\n");
    },
  );

  test("removes receipt-bound evaluation workspaces when task execution fails", async () => {
    const temporaryRoot = temporary("tc-sdlc-maintenance-task-root-");
    const root = join(temporaryRoot, "source");
    const evidence = join(temporaryRoot, "evidence");
    mkdirSync(root);
    mkdirSync(evidence);
    writeFileSync(join(root, "input.txt"), "input\n");
    execFileSync("git", ["init", "--quiet"], { cwd: root });
    execFileSync("git", ["add", "."], { cwd: root });
    execFileSync(
      "git",
      [
        "-c",
        "user.name=Lifecycle Test",
        "-c",
        "user.email=lifecycle@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "fixture",
      ],
      { cwd: root },
    );
    const declaration = sdlc.validateDeclaration({
      schema: "tc.sdlc/v1",
      project: "lifecycle-fixture",
      toolchains: sdlc.CANONICAL_SDLC_TOOLCHAINS,
      fitness: sdlc.CANONICAL_SDLC_FITNESS,
      projects: [{ name: "fixture", root: "." }],
      targets: {
        check: {
          command: `${process.execPath} -e 'process.exit(2)'`,
          mode: "evaluate",
          trustBoundary: "portable",
          resources: { cpu: 1, memoryMiB: 32, ports: [], exclusive: [] },
          budget: { phaseMs: 5_000, noProgressMs: 2_000, heartbeatMs: 100 },
          inputs: ["input.txt"],
          outputs: [],
        },
      },
    });
    const catalogue = sdlc.generateReleaseCatalogue({
      releaseVersion: "3.0.0",
      workflowCommit: "1234567890abcdef1234567890abcdef12345678",
      imageDigest:
        "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    });
    const previous = process.env.TMPDIR;
    process.env.TMPDIR = temporaryRoot;
    try {
      const result = await sdlc.checkAll({
        root,
        declaration,
        catalogue,
        lock: sdlc.resolveLock(declaration, catalogue),
        receiptPath: join(evidence, "evaluation.json"),
        environmentClass: `native-${process.platform}`,
        producer: "lifecycle-test",
        runOptions: { capacity: { cpu: 1, memoryMiB: 64 } },
      });
      expect(result.status).toBe("failed");
      expect(
        readdirSync(temporaryRoot).filter((name) => name.startsWith("tc-sdlc-evaluation-")),
      ).toEqual([]);
    } finally {
      if (previous === undefined) delete process.env.TMPDIR;
      else process.env.TMPDIR = previous;
    }
  });

  test("exposes dry-run and apply through the built CLI with a canonical receipt", () => {
    const parent = temporary("tc-sdlc-maintenance-cli-");
    const stateRoot = temporary("tc-sdlc-maintenance-state-");
    const evidence = temporary("tc-sdlc-maintenance-evidence-");
    ownedState(stateRoot);
    managedTemporary(parent, "tc-sdlc-evaluation-expired", {
      pid: 2_147_483_647,
      old: true,
      git: "clean",
    });
    const receiptPath = join(evidence, "receipt.json");

    const result = spawnSync(
      process.execPath,
      [
        CLI,
        "maintain",
        "--state-root", stateRoot,
        "--temporary-root", parent,
        "--receipt", receiptPath,
        "--mode", "apply",
      ],
      { encoding: "utf8" },
    );

    expect(result.status, result.stderr).toBe(0);
    expect(result.stderr).toBe("");
    expect(JSON.parse(result.stdout)).toMatchObject({
      schema: "tc.sdlc/command-result/v1",
      command: "maintain",
      status: "ok",
      receiptSchema: "tc.sdlc/maintenance-receipt/v1",
      removedCount: 1,
      cleanupWorkers: 4,
      cleanupFailures: 0,
    });
    const receipt = JSON.parse(readFileSync(receiptPath, "utf8"));
    expect(readFileSync(receiptPath, "utf8")).toBe(sdlc.canonicalJson(receipt));
  });
});
