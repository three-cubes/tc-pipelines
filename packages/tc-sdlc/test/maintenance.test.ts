import * as sdlc from "../dist/index.js";
import { execFileSync, spawn, spawnSync } from "node:child_process";
import {
  chmodSync,
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  realpathSync,
  renameSync,
  rmSync,
  symlinkSync,
  utimesSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
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

function taskRunOptions(capacity = { cpu: 1, memoryMiB: 64 }) {
  return {
    capacity,
    executionContext: {
      binding: {
        schema: "tc.sdlc/execution-context/v1",
        release: "3.0.0",
        platform: process.platform === "linux" ? "linux" : "darwin",
        architecture: process.arch,
        lockDigest: `sha256:${"a".repeat(64)}`,
        stateKey: "releases/test/maintenance",
        stateGenerationIdentity: `sha256:${"e".repeat(64)}`,
        bootstrapReceiptDigest: `sha256:${"b".repeat(64)}`,
        stateDigest: `sha256:${"c".repeat(64)}`,
        dependencyDigest: `sha256:${"d".repeat(64)}`,
        fitness: { package: "three-cubes-fitness", version: "0.17.0" },
        adapters: [],
      },
      stateRoot: tmpdir(),
      stateDirectory: tmpdir(),
      environment: { PATH: process.env.PATH ?? "" },
      lease: { assertCurrent: () => undefined, release: () => undefined },
      assertIdentity: () => undefined,
      verifyIntegrity: () => undefined,
    },
  };
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

function bootstrapState(root: string, stateKey: string, old = true): string {
  const directory = join(root, stateKey);
  mkdirSync(directory, { recursive: true });
  writeFileSync(
    join(directory, "state.json"),
    sdlc.canonicalJson({
      schema: "tc.sdlc/bootstrap-state/v6",
      release: "3.0.0",
      lockDigest: "sha256:" + "a".repeat(64),
      dependencyDigest: "sha256:" + "b".repeat(64),
      platform: "darwin",
      architecture: "arm64",
      adapters: [],
      dependencies: [],
    }),
  );
  if (old) {
    const expired = new Date(Date.now() - 49 * 60 * 60 * 1_000);
    utimesSync(directory, expired, expired);
  }
  return directory;
}

function filesystemIdentity(path: string) {
  const details = lstatSync(path, { bigint: true });
  return {
    device: details.dev.toString(),
    inode: details.ino.toString(),
    birthtimeNanoseconds: details.birthtimeNs.toString(),
  };
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
      peakCleanupWorkers: 2,
      candidateCount: 6,
      removedCount: 6,
    });
    expect(paths.some(existsSync)).toBe(false);
  });

  test("recovers an owner-bound quarantine left by a killed maintain process", async () => {
    const parent = temporary("tc-sdlc-maintenance-killed-");
    const stateRoot = temporary("tc-sdlc-maintenance-state-");
    const evidence = temporary("tc-sdlc-maintenance-evidence-");
    ownedState(stateRoot);
    const candidate = managedTemporary(parent, "tc-sdlc-evaluation-killed", {
      pid: 2_147_483_647,
      old: true,
    });
    for (let index = 0; index < 20_000; index += 1) {
      writeFileSync(join(candidate, `entry-${index}.txt`), "owned\n");
    }
    const old = new Date(Date.now() - 49 * 60 * 60 * 1_000);
    utimesSync(candidate, old, old);

    const child = spawn(
      process.execPath,
      [
        CLI,
        "maintain",
        "--state-root", stateRoot,
        "--temporary-root", parent,
        "--receipt", join(evidence, "killed.json"),
        "--mode", "apply",
      ],
      { stdio: "ignore" },
    );
    let quarantine: string | undefined;
    const deadline = Date.now() + 10_000;
    while (Date.now() < deadline) {
      quarantine = readdirSync(parent)
        .find((name) => name.startsWith(".tc-sdlc-quarantine-"));
      if (
        quarantine !== undefined &&
        existsSync(join(parent, quarantine, "candidate"))
      ) break;
      await new Promise((resolve) => setTimeout(resolve, 1));
    }
    expect(quarantine).toBeDefined();
    child.kill("SIGKILL");
    await new Promise<void>((resolve) => child.once("exit", () => resolve()));
    const quarantinePath = join(parent, quarantine!);
    expect(existsSync(join(quarantinePath, "candidate"))).toBe(true);
    utimesSync(quarantinePath, old, old);

    const displaced = join(parent, "displaced-quarantine");
    const racing = sdlc.maintain({
      stateRoot,
      temporaryRoot: parent,
      receiptPath: join(evidence, "replacement-race.json"),
      mode: "apply",
    });
    try {
      renameSync(quarantinePath, displaced);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
    mkdirSync(join(quarantinePath, "deleting"), { recursive: true });
    writeFileSync(
      join(quarantinePath, "deleting", "foreign.txt"),
      "foreign replacement bytes\n",
    );
    await racing;
    expect(
      readFileSync(join(quarantinePath, "deleting", "foreign.txt"), "utf8"),
    ).toBe("foreign replacement bytes\n");
    rmSync(quarantinePath, { recursive: true, force: true });
    let recoveryPath = quarantinePath;
    if (existsSync(displaced)) {
      renameSync(displaced, quarantinePath);
    } else {
      const recoveredName = readdirSync(parent).find((name) =>
        name.startsWith(".tc-sdlc-quarantine-"),
      );
      expect(recoveredName).toBeDefined();
      recoveryPath = join(parent, recoveredName!);
      quarantine = recoveredName;
    }
    utimesSync(recoveryPath, old, old);

    const receipt = await sdlc.maintain({
      stateRoot,
      temporaryRoot: parent,
      receiptPath: join(evidence, "recovered.json"),
      mode: "apply",
    });

    expect(receipt.candidates).toContainEqual(
      expect.objectContaining({ kind: "quarantine", path: quarantine }),
    );
    expect(receipt.removedCount).toBe(1);
    expect(receipt.peakCleanupWorkers).toBe(1);
    expect(existsSync(recoveryPath)).toBe(false);

    const foreign = join(parent, ".tc-sdlc-quarantine-foreign");
    mkdirSync(foreign);
    writeFileSync(join(foreign, "preserve.txt"), "foreign bytes\n");
    utimesSync(foreign, old, old);
    const mismatched = join(parent, ".tc-sdlc-quarantine-mismatched");
    mkdirSync(mismatched);
    mkdirSync(join(mismatched, "candidate"));
    writeFileSync(join(mismatched, "candidate", "preserve.txt"), "mismatched bytes\n");
    writeFileSync(
      join(mismatched, ".tc-sdlc-quarantine.json"),
      sdlc.canonicalJson({
        schema: "tc.sdlc/quarantine-owner/v1",
        owner: "@three-cubes/tc-sdlc",
        kind: "temporary",
        originalName: "tc-sdlc-evaluation-missing",
        payloadIdentity: {
          device: "0",
          inode: "0",
          birthtimeNanoseconds: "0",
        },
      }),
    );
    utimesSync(mismatched, old, old);
    const mixed = join(parent, ".tc-sdlc-quarantine-mixed");
    mkdirSync(join(mixed, "candidate"), { recursive: true });
    mkdirSync(join(mixed, "deleting"));
    writeFileSync(join(mixed, "candidate", "owned.txt"), "owned candidate\n");
    writeFileSync(join(mixed, "deleting", "foreign.txt"), "foreign deleting\n");
    const mixedIdentity = lstatSync(join(mixed, "candidate"), { bigint: true });
    writeFileSync(
      join(mixed, ".tc-sdlc-quarantine.json"),
      sdlc.canonicalJson({
        schema: "tc.sdlc/quarantine-owner/v1",
        owner: "@three-cubes/tc-sdlc",
        kind: "temporary",
        originalName: "tc-sdlc-evaluation-mixed",
        payloadIdentity: {
          device: mixedIdentity.dev.toString(),
          inode: mixedIdentity.ino.toString(),
          birthtimeNanoseconds: mixedIdentity.birthtimeNs.toString(),
        },
      }),
    );
    utimesSync(mixed, old, old);
    const guarded = await sdlc.maintain({
      stateRoot,
      temporaryRoot: parent,
      receiptPath: join(evidence, "foreign-quarantine.json"),
      mode: "apply",
    });
    expect(guarded.removedCount).toBe(0);
    expect(readFileSync(join(foreign, "preserve.txt"), "utf8")).toBe("foreign bytes\n");
    expect(readFileSync(join(mismatched, "candidate", "preserve.txt"), "utf8")).toBe(
      "mismatched bytes\n",
    );
    expect(readFileSync(join(mixed, "candidate", "owned.txt"), "utf8")).toBe(
      "owned candidate\n",
    );
    expect(readFileSync(join(mixed, "deleting", "foreign.txt"), "utf8")).toBe(
      "foreign deleting\n",
    );

    const emptyInterrupted = join(parent, ".tc-sdlc-quarantine-empty");
    mkdirSync(emptyInterrupted);
    utimesSync(emptyInterrupted, old, old);
    const emptyRecovery = await sdlc.maintain({
      stateRoot,
      temporaryRoot: parent,
      receiptPath: join(evidence, "empty-quarantine.json"),
      mode: "apply",
    });
    expect(emptyRecovery.retained).toContainEqual({
      path: ".tc-sdlc-quarantine-empty",
      reason: "foreign",
    });
    expect(existsSync(emptyInterrupted)).toBe(true);
  }, 30_000);

  test("recovers an owned quarantine when birthtime evidence changes across a move", async () => {
    const parent = temporary("tc-sdlc-maintenance-move-identity-");
    const stateRoot = temporary("tc-sdlc-maintenance-move-state-");
    const evidence = temporary("tc-sdlc-maintenance-move-evidence-");
    ownedState(stateRoot);
    const root = join(parent, ".tc-sdlc-quarantine-moved");
    const payload = join(root, "candidate");
    mkdirSync(payload, { recursive: true });
    writeFileSync(join(payload, "owned.txt"), "owned bytes\n");
    const movedIdentity = filesystemIdentity(payload);
    writeFileSync(
      join(root, ".tc-sdlc-quarantine.json"),
      sdlc.canonicalJson({
        schema: "tc.sdlc/quarantine-owner/v1",
        owner: "@three-cubes/tc-sdlc",
        kind: "temporary",
        originalName: "tc-sdlc-evaluation-moved",
        payloadIdentity: {
          ...movedIdentity,
          birthtimeNanoseconds: `${BigInt(movedIdentity.birthtimeNanoseconds) + 1n}`,
        },
      }),
    );
    const old = new Date(Date.now() - 49 * 60 * 60 * 1_000);
    utimesSync(root, old, old);

    const receipt = await sdlc.maintain({
      stateRoot,
      temporaryRoot: parent,
      receiptPath: join(evidence, "move-identity.json"),
      mode: "apply",
    });

    expect(receipt).toMatchObject({ status: "succeeded", removedCount: 1 });
    expect(receipt.candidates).toContainEqual(
      expect.objectContaining({ kind: "quarantine", path: ".tc-sdlc-quarantine-moved" }),
    );
    expect(existsSync(root)).toBe(false);
  });

  test("bounds deletion-worker lifecycle and records a terminal cleanup failure", async () => {
    const parent = temporary("tc-sdlc-maintenance-worker-budget-");
    const stateRoot = temporary("tc-sdlc-maintenance-state-");
    const evidence = temporary("tc-sdlc-maintenance-evidence-");
    ownedState(stateRoot);
    const candidate = managedTemporary(parent, "tc-sdlc-evaluation-worker-budget", {
      pid: 2_147_483_647,
      old: true,
    });
    for (let index = 0; index < 2_000; index += 1) {
      writeFileSync(join(candidate, `entry-${index}.txt`), "owned\n");
    }
    const old = new Date(Date.now() - 49 * 60 * 60 * 1_000);
    utimesSync(candidate, old, old);
    const foreign = join(parent, "tc-sdlc-foreign-worker-budget");
    mkdirSync(foreign);
    writeFileSync(join(foreign, "keep.txt"), "foreign bytes\n");

    const receipt = await sdlc.maintain({
      stateRoot,
      temporaryRoot: parent,
      receiptPath: join(evidence, "worker-budget.json"),
      mode: "apply",
      cleanupWorkerMs: 1,
    });

    expect(receipt).toMatchObject({
      status: "failed",
      reason: "temporary_cleanup_failed",
      cleanupWorkerMs: 1,
      peakCleanupWorkers: 1,
      cleanupFailures: 1,
      removedCount: 0,
    });
    expect(readFileSync(join(foreign, "keep.txt"), "utf8")).toBe("foreign bytes\n");
    expect(
      existsSync(candidate) ||
      readdirSync(parent).some((name) => name.startsWith(".tc-sdlc-quarantine-")),
    ).toBe(true);
  });

  test("does not delete a foreign replacement installed after candidate inspection", async () => {
    const parent = temporary("tc-sdlc-maintenance-replacement-");
    const stateRoot = temporary("tc-sdlc-maintenance-state-");
    const evidence = temporary("tc-sdlc-maintenance-evidence-");
    ownedState(stateRoot);
    const candidate = managedTemporary(parent, "tc-sdlc-evaluation-replaced", {
      pid: 2_147_483_647,
      old: true,
    });
    for (let index = 0; index < 100; index += 1) {
      writeFileSync(join(candidate, `owned-${index}.txt`), "owned\n");
    }
    const old = new Date(Date.now() - 49 * 60 * 60 * 1_000);
    utimesSync(candidate, old, old);
    const displaced = join(parent, "displaced-owned-root");

    const running = sdlc.maintain({
      stateRoot,
      temporaryRoot: parent,
      receiptPath: join(evidence, "replacement.json"),
      mode: "apply",
      cleanupWorkers: 1,
    });
    try {
      renameSync(candidate, displaced);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
    mkdirSync(candidate, { recursive: true });
    writeFileSync(join(candidate, "foreign.txt"), "preserve foreign bytes\n");

    const receipt = await running;
    expect(readFileSync(join(candidate, "foreign.txt"), "utf8")).toBe(
      "preserve foreign bytes\n",
    );
    expect(receipt.removedCount).toBeLessThanOrEqual(1);
  });

  test.runIf(process.platform !== "win32" && process.getuid?.() !== 0)(
    "records quarantine-creation failures and retains scratch and bootstrap candidates",
    async () => {
      const parent = temporary("tc-sdlc-maintenance-unwritable-temp-");
      const stateRoot = temporary("tc-sdlc-maintenance-unwritable-state-");
      const evidence = temporary("tc-sdlc-maintenance-unwritable-evidence-");
      ownedState(stateRoot);
      const scratch = managedTemporary(parent, "tc-sdlc-evaluation-unwritable", {
        pid: 2_147_483_647,
        old: true,
      });
      chmodSync(parent, 0o500);
      let scratchReceipt: sdlc.MaintenanceReceipt | undefined;
      try {
        scratchReceipt = await sdlc.maintain({
          stateRoot,
          temporaryRoot: parent,
          receiptPath: join(evidence, "scratch.json"),
          mode: "apply",
        });
      } finally {
        chmodSync(parent, 0o700);
      }
      expect(scratchReceipt).toMatchObject({
        status: "failed",
        reason: "temporary_cleanup_failed",
        candidateCount: 1,
        removedCount: 0,
        cleanupFailures: 1,
        retained: [{ path: "tc-sdlc-evaluation-unwritable", reason: "inspection_failed" }],
      });
      expect(existsSync(scratch)).toBe(true);
      expect(readFileSync(join(evidence, "scratch.json"), "utf8")).toBe(
        sdlc.serialiseMaintenanceReceipt(scratchReceipt!),
      );

      const currentKey = "releases/current/dependencies/darwin-arm64";
      const expiredKey = "releases/expired/dependencies/darwin-arm64";
      const current = bootstrapState(stateRoot, currentKey);
      const expired = bootstrapState(stateRoot, expiredKey);
      mkdirSync(join(stateRoot, "references"));
      writeFileSync(
        join(
          stateRoot,
          "references",
          `${sdlc.digest({ consumer: "fixture", consumerRoot: "/fixture" }).slice("sha256:".length)}.json`,
        ),
        sdlc.canonicalJson({
          schema: "tc.sdlc/bootstrap-reference/v2",
          owner: "@three-cubes/tc-sdlc",
          phase: "committed",
          transaction: "00000000-0000-4000-8000-000000000001",
          committedAtMs: 1,
          consumer: "fixture",
          consumerRoot: "/fixture",
          currentStateKey: currentKey,
          currentStateIdentity: filesystemIdentity(current),
        }),
      );
      const stateParent = join(stateRoot, "releases", "expired", "dependencies");
      chmodSync(stateParent, 0o500);
      let stateReceipt: sdlc.MaintenanceReceipt | undefined;
      try {
        stateReceipt = await sdlc.maintain({
          stateRoot,
          temporaryRoot: temporary("tc-sdlc-maintenance-unwritable-empty-"),
          receiptPath: join(evidence, "bootstrap-state.json"),
          mode: "apply",
        });
      } finally {
        chmodSync(stateParent, 0o700);
      }
      expect(stateReceipt).toMatchObject({
        status: "failed",
        reason: "temporary_cleanup_failed",
        removedCount: 0,
        cleanupFailures: 1,
        retained: expect.arrayContaining([
          { path: expiredKey, reason: "inspection_failed" },
        ]),
      });
      expect(existsSync(expired)).toBe(true);
      expect(readFileSync(join(evidence, "bootstrap-state.json"), "utf8")).toBe(
        sdlc.serialiseMaintenanceReceipt(stateReceipt!),
      );
    },
  );

  test("retains dirty tracked and untracked work in an evaluation workspace", async () => {
    const parent = temporary("tc-sdlc-maintenance-nested-worktree-");
    const stateRoot = temporary("tc-sdlc-maintenance-state-");
    const evidence = temporary("tc-sdlc-maintenance-evidence-");
    ownedState(stateRoot);
    const ownedRoot = managedTemporary(parent, "tc-sdlc-evaluation-dirty-workspace", {
      pid: 2_147_483_647,
      old: false,
    });
    const workspace = join(ownedRoot, "workspace");
    mkdirSync(workspace);
    execFileSync("git", ["init", "--quiet"], { cwd: workspace });
    writeFileSync(join(workspace, "tracked.txt"), "tracked\n");
    execFileSync("git", ["add", "tracked.txt"], { cwd: workspace });
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
      { cwd: workspace },
    );
    writeFileSync(join(workspace, "tracked.txt"), "unsaved tracked bytes\n");
    writeFileSync(join(workspace, "untracked.txt"), "unsaved untracked bytes\n");
    const decoy = temporary("tc-sdlc-maintenance-clean-decoy-");
    execFileSync("git", ["init", "--quiet"], { cwd: decoy });
    writeFileSync(join(decoy, "clean.txt"), "clean\n");
    execFileSync("git", ["add", "clean.txt"], { cwd: decoy });
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
        "clean decoy",
      ],
      { cwd: decoy },
    );
    const old = new Date(Date.now() - 49 * 60 * 60 * 1_000);
    utimesSync(join(ownedRoot, ".tc-sdlc-temporary.json"), old, old);
    utimesSync(ownedRoot, old, old);

    const previousGitDirectory = process.env.GIT_DIR;
    const previousGitWorkTree = process.env.GIT_WORK_TREE;
    process.env.GIT_DIR = join(decoy, ".git");
    process.env.GIT_WORK_TREE = decoy;
    let receipt: sdlc.MaintenanceReceipt;
    try {
      receipt = await sdlc.maintain({
        stateRoot,
        temporaryRoot: parent,
        receiptPath: join(evidence, "nested-worktree.json"),
        mode: "apply",
      });
    } finally {
      if (previousGitDirectory === undefined) delete process.env.GIT_DIR;
      else process.env.GIT_DIR = previousGitDirectory;
      if (previousGitWorkTree === undefined) delete process.env.GIT_WORK_TREE;
      else process.env.GIT_WORK_TREE = previousGitWorkTree;
    }

    expect(receipt.retained).toContainEqual({
      path: "tc-sdlc-evaluation-dirty-workspace",
      reason: "dirty_worktree",
    });
    expect(readFileSync(join(workspace, "tracked.txt"), "utf8")).toBe(
      "unsaved tracked bytes\n",
    );
    expect(readFileSync(join(workspace, "untracked.txt"), "utf8")).toBe(
      "unsaved untracked bytes\n",
    );
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

  test("expires only bootstrap states made unreferenced by producer-owned metadata", async () => {
    const parent = temporary("tc-sdlc-maintenance-state-gc-temp-");
    const stateRoot = temporary("tc-sdlc-maintenance-state-gc-");
    const evidence = temporary("tc-sdlc-maintenance-state-gc-evidence-");
    ownedState(stateRoot);
    const currentKey = "releases/current/dependencies/darwin-arm64";
    const predecessorKey = "releases/predecessor/dependencies/darwin-arm64";
    const expiredKey = "releases/expired/dependencies/darwin-arm64";
    const recentKey = "releases/recent/dependencies/darwin-arm64";
    const current = bootstrapState(stateRoot, currentKey);
    const predecessor = bootstrapState(stateRoot, predecessorKey);
    const expired = bootstrapState(stateRoot, expiredKey);
    const recent = bootstrapState(stateRoot, recentKey, false);
    mkdirSync(join(stateRoot, "references"));
    writeFileSync(
      join(
        stateRoot,
        "references",
        `${sdlc.digest({ consumer: "fixture", consumerRoot: "/fixture" }).slice("sha256:".length)}.json`,
      ),
      sdlc.canonicalJson({
        schema: "tc.sdlc/bootstrap-reference/v2",
        owner: "@three-cubes/tc-sdlc",
        phase: "committed",
        transaction: "00000000-0000-4000-8000-000000000001",
        committedAtMs: 1,
        consumer: "fixture",
        consumerRoot: "/fixture",
        currentStateKey: currentKey,
        currentStateIdentity: filesystemIdentity(current),
        predecessorStateKey: predecessorKey,
        predecessorStateIdentity: filesystemIdentity(predecessor),
      }),
    );

    const receipt = await sdlc.maintain({
      stateRoot,
      temporaryRoot: parent,
      receiptPath: join(evidence, "state-gc.json"),
      mode: "apply",
    });

    expect(receipt.candidates).toContainEqual(
      expect.objectContaining({ kind: "bootstrap-state", path: expiredKey }),
    );
    expect(receipt.retained).toEqual(
      expect.arrayContaining([
        { path: currentKey, reason: "referenced" },
        { path: predecessorKey, reason: "referenced" },
        { path: recentKey, reason: "retention_window" },
      ]),
    );
    expect(existsSync(expired)).toBe(false);
    expect(existsSync(current)).toBe(true);
    expect(existsSync(predecessor)).toBe(true);
    expect(existsSync(recent)).toBe(true);

    rmSync(join(stateRoot, "references"), { recursive: true });
    const unreferencedMetadataAbsent = bootstrapState(
      stateRoot,
      "releases/no-authority/dependencies/darwin-arm64",
    );
    const guarded = await sdlc.maintain({
      stateRoot,
      temporaryRoot: parent,
      receiptPath: join(evidence, "state-gc-no-authority.json"),
      mode: "apply",
    });
    expect(guarded.retained).toContainEqual({
      path: "releases/no-authority/dependencies/darwin-arm64",
      reason: "reference_metadata_absent",
    });
    expect(existsSync(unreferencedMetadataAbsent)).toBe(true);
  });

  test("restores an identity-bound state referenced after quarantine", async () => {
    const parent = temporary("tc-sdlc-maintenance-reference-race-temp-");
    const stateRoot = temporary("tc-sdlc-maintenance-reference-race-state-");
    const evidence = temporary("tc-sdlc-maintenance-reference-race-evidence-");
    ownedState(stateRoot);
    const currentKey = "releases/current/dependencies/darwin-arm64";
    const expiredKey = "releases/expired/dependencies/darwin-arm64";
    const current = bootstrapState(stateRoot, currentKey);
    const expired = bootstrapState(stateRoot, expiredKey);
    const expiredIdentity = filesystemIdentity(expired);
    const references = join(stateRoot, "references");
    mkdirSync(references);
    let greatestName = "";
    for (let index = 0; index < 5_000; index += 1) {
      const consumer = `existing-${index}`;
      const consumerRoot = `/fixture/existing-${index}`;
      const name = `${sdlc.digest({ consumer, consumerRoot }).slice("sha256:".length)}.json`;
      greatestName = name > greatestName ? name : greatestName;
      writeFileSync(
        join(references, name),
        sdlc.canonicalJson({
          schema: "tc.sdlc/bootstrap-reference/v2",
          owner: "@three-cubes/tc-sdlc",
          phase: "committed",
          transaction: "00000000-0000-4000-8000-000000000001",
          committedAtMs: 1,
          consumer,
          consumerRoot,
          currentStateKey: currentKey,
          currentStateIdentity: filesystemIdentity(current),
        }),
      );
    }
    let targetIndex = 0;
    let targetConsumer = "";
    let targetRoot = "";
    let targetName = "";
    while (targetName <= greatestName) {
      targetConsumer = `late-reference-${targetIndex}`;
      targetRoot = `/fixture/late-reference-${targetIndex}`;
      targetName = `${sdlc.digest({ consumer: targetConsumer, consumerRoot: targetRoot }).slice("sha256:".length)}.json`;
      targetIndex += 1;
    }
    const targetPath = join(references, targetName);
    const targetReference = (identity: ReturnType<typeof filesystemIdentity>) =>
      sdlc.canonicalJson({
        schema: "tc.sdlc/bootstrap-reference/v2",
        owner: "@three-cubes/tc-sdlc",
        phase: "committed",
        transaction: "00000000-0000-4000-8000-000000000001",
        committedAtMs: 1,
        consumer: targetConsumer,
        consumerRoot: targetRoot,
        currentStateKey: expiredKey,
        currentStateIdentity: identity,
      });
    writeFileSync(targetPath, targetReference(filesystemIdentity(current)));

    const receiptPath = join(evidence, "reference-race.json");
    const child = spawn(
      process.execPath,
      [
        CLI,
        "maintain",
        "--state-root", stateRoot,
        "--temporary-root", parent,
        "--receipt", receiptPath,
        "--mode", "apply",
      ],
      { stdio: "ignore" },
    );
    const exited = new Promise<number | null>((resolve) => {
      child.once("exit", resolve);
    });
    let resumed = false;
    try {
      const quarantineParent = join(stateRoot, "releases", "expired", "dependencies");
      let quarantine: string | undefined;
      const deadline = Date.now() + 30_000;
      while (quarantine === undefined && Date.now() < deadline) {
        quarantine = readdirSync(quarantineParent)
          .map((name) => join(quarantineParent, name))
          .find((path) =>
            path.includes(".tc-sdlc-quarantine-") &&
            existsSync(join(path, "candidate"))
          );
        await new Promise((resolve) => setTimeout(resolve, 1));
      }
      expect(quarantine).toBeDefined();
      expect(child.kill("SIGSTOP")).toBe(true);
      expect(existsSync(join(quarantine!, "candidate"))).toBe(true);
      writeFileSync(targetPath, targetReference(expiredIdentity));
      expect(child.kill("SIGCONT")).toBe(true);
      resumed = true;
      expect(await exited).toBe(0);
    } finally {
      if (!resumed && child.exitCode === null) {
        child.kill("SIGCONT");
        child.kill("SIGKILL");
      }
    }

    const receipt = JSON.parse(readFileSync(receiptPath, "utf8"));
    expect(receipt).toMatchObject({
      schema: "tc.sdlc/maintenance-receipt/v1",
      status: "succeeded",
      removedCount: 0,
      retained: expect.arrayContaining([
        { path: expiredKey, reason: "referenced" },
      ]),
    });
    expect(existsSync(expired)).toBe(true);
    expect(filesystemIdentity(expired)).toEqual(
      JSON.parse(readFileSync(targetPath, "utf8")).currentStateIdentity,
    );
  }, 60_000);

  test("restores an interrupted bootstrap-state quarantine authorised by a pending transaction", async () => {
    const parent = temporary("tc-sdlc-maintenance-pending-recovery-temp-");
    const stateRoot = temporary("tc-sdlc-maintenance-pending-recovery-state-");
    const evidence = temporary("tc-sdlc-maintenance-pending-recovery-evidence-");
    ownedState(stateRoot);
    const stateKey = "releases/pending/dependencies/darwin-arm64";
    const state = bootstrapState(stateRoot, stateKey);
    const identity = filesystemIdentity(state);
    const quarantine = join(dirname(state), ".tc-sdlc-quarantine-pending-recovery");
    mkdirSync(quarantine);
    writeFileSync(
      join(quarantine, ".tc-sdlc-quarantine.json"),
      sdlc.canonicalJson({
        schema: "tc.sdlc/quarantine-owner/v1",
        owner: "@three-cubes/tc-sdlc",
        kind: "bootstrap-state",
        originalName: "darwin-arm64",
        payloadIdentity: identity,
      }),
    );
    renameSync(state, join(quarantine, "deleting"));
    const old = new Date(Date.now() - 49 * 60 * 60 * 1_000);
    utimesSync(quarantine, old, old);
    const pending = join(stateRoot, "references", "pending");
    mkdirSync(pending, { recursive: true });
    const transaction = "00000000-0000-4000-8000-000000000009";
    writeFileSync(
      join(pending, `${transaction}.json`),
      sdlc.canonicalJson({
        schema: "tc.sdlc/bootstrap-reference-pending/v1",
        owner: "@three-cubes/tc-sdlc",
        phase: "pending",
        transaction,
        consumer: "pending-fixture",
        consumerRoot: "/fixture/pending",
        stateKey,
        stateIdentity: identity,
        pid: process.pid,
        processStartedAt: "fixture-process-start",
        createdAtMs: Date.now(),
      }),
    );

    const receipt = await sdlc.maintain({
      stateRoot,
      temporaryRoot: parent,
      receiptPath: join(evidence, "pending-recovery.json"),
      mode: "apply",
    });

    expect(receipt).toMatchObject({ status: "succeeded", removedCount: 0 });
    expect(receipt.retained).toContainEqual({ path: stateKey, reason: "referenced" });
    expect(filesystemIdentity(state)).toEqual(identity);
    expect(existsSync(quarantine)).toBe(false);
  });

  test("recovers a bootstrap-state quarantine killed in the deleting phase", async () => {
    const parent = temporary("tc-sdlc-maintenance-bootstrap-killed-temp-");
    const stateRoot = temporary("tc-sdlc-maintenance-bootstrap-killed-state-");
    const evidence = temporary("tc-sdlc-maintenance-bootstrap-killed-evidence-");
    ownedState(stateRoot);
    const currentKey = "releases/current/dependencies/darwin-arm64";
    const expiredKey = "releases/expired/dependencies/darwin-arm64";
    const current = bootstrapState(stateRoot, currentKey);
    const expired = bootstrapState(stateRoot, expiredKey);
    for (let index = 0; index < 20_000; index += 1) {
      writeFileSync(join(expired, `entry-${index}.txt`), "owned\n");
    }
    const old = new Date(Date.now() - 49 * 60 * 60 * 1_000);
    utimesSync(expired, old, old);
    mkdirSync(join(stateRoot, "references"));
    writeFileSync(
      join(
        stateRoot,
        "references",
        `${sdlc.digest({ consumer: "fixture", consumerRoot: "/fixture" }).slice("sha256:".length)}.json`,
      ),
      sdlc.canonicalJson({
        schema: "tc.sdlc/bootstrap-reference/v2",
        owner: "@three-cubes/tc-sdlc",
        phase: "committed",
        transaction: "00000000-0000-4000-8000-000000000001",
        committedAtMs: 1,
        consumer: "fixture",
        consumerRoot: "/fixture",
        currentStateKey: currentKey,
        currentStateIdentity: filesystemIdentity(current),
      }),
    );

    const child = spawn(
      process.execPath,
      [
        CLI,
        "maintain",
        "--state-root", stateRoot,
        "--temporary-root", parent,
        "--receipt", join(evidence, "killed.json"),
        "--mode", "apply",
      ],
      { stdio: "ignore" },
    );
    const quarantineParent = join(stateRoot, "releases", "expired", "dependencies");
    let quarantine: string | undefined;
    const deadline = Date.now() + 10_000;
    while (Date.now() < deadline) {
      quarantine = readdirSync(quarantineParent)
        .find((name) => name.startsWith(".tc-sdlc-quarantine-"));
      if (
        quarantine !== undefined &&
        existsSync(join(quarantineParent, quarantine, "deleting"))
      ) break;
      await new Promise((resolve) => setTimeout(resolve, 1));
    }
    expect(quarantine).toBeDefined();
    child.kill("SIGKILL");
    await new Promise<void>((resolve) => child.once("exit", () => resolve()));
    const quarantinePath = join(quarantineParent, quarantine!);
    expect(existsSync(join(quarantinePath, "deleting"))).toBe(true);
    utimesSync(quarantinePath, old, old);

    const displaced = join(quarantineParent, "displaced-quarantine");
    const racing = sdlc.maintain({
      stateRoot,
      temporaryRoot: parent,
      receiptPath: join(evidence, "replacement-race.json"),
      mode: "apply",
    });
    try {
      renameSync(quarantinePath, displaced);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
    mkdirSync(join(quarantinePath, "deleting"), { recursive: true });
    writeFileSync(
      join(quarantinePath, "deleting", "foreign.txt"),
      "foreign bootstrap replacement bytes\n",
    );
    await racing;
    expect(
      readFileSync(join(quarantinePath, "deleting", "foreign.txt"), "utf8"),
    ).toBe("foreign bootstrap replacement bytes\n");
    rmSync(quarantinePath, { recursive: true, force: true });
    let recoveryPath = quarantinePath;
    if (existsSync(displaced)) {
      renameSync(displaced, quarantinePath);
    } else {
      const recoveredName = readdirSync(quarantineParent).find((name) =>
        name.startsWith(".tc-sdlc-quarantine-"),
      );
      expect(recoveredName).toBeDefined();
      recoveryPath = join(quarantineParent, recoveredName!);
      quarantine = recoveredName;
    }
    utimesSync(recoveryPath, old, old);

    const recovered = await sdlc.maintain({
      stateRoot,
      temporaryRoot: parent,
      receiptPath: join(evidence, "recovered.json"),
      mode: "apply",
    });
    expect(recovered.candidates).toContainEqual(
      expect.objectContaining({
        kind: "quarantine",
        path: `releases/expired/dependencies/${quarantine}`,
      }),
    );
    expect(recovered.peakCleanupWorkers).toBe(1);
    expect(existsSync(recoveryPath)).toBe(false);
    expect(existsSync(join(stateRoot, currentKey))).toBe(true);
  }, 30_000);

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
        runOptions: taskRunOptions({ cpu: 1, memoryMiB: 64 }),
      });
      expect(result.status).toBe("failed");
      expect(
        readdirSync(temporaryRoot).filter((name) => name.startsWith("tc-sdlc-evaluation-")),
      ).toEqual([]);
      const rejected = await sdlc.checkAll({
        root,
        declaration,
        catalogue,
        lock: sdlc.resolveLock(declaration, catalogue),
        receiptPath: join(evidence, "evaluation-invalid-capacity.json"),
        environmentClass: `native-${process.platform}`,
        producer: "lifecycle-test",
        runOptions: taskRunOptions({ cpu: 0, memoryMiB: 64 }),
      });
      expect(rejected).toMatchObject({
        status: "failed",
        reason: "scheduler_failed",
        scheduler: {
          status: "failed",
          reason: "host capacity must be positive",
          scratchCleanup: "removed",
        },
      });
      expect(
        readdirSync(temporaryRoot).filter((name) => name.startsWith("tc-sdlc-evaluation-")),
      ).toEqual([]);
    } finally {
      if (previous === undefined) delete process.env.TMPDIR;
      else process.env.TMPDIR = previous;
    }
  });

  test("ordinary preparation recovers interrupted owned scratch on success and failure", async () => {
    const temporaryRoot = temporary("tc-sdlc-maintenance-routine-root-");
    const root = join(temporaryRoot, "source");
    const evidence = join(temporaryRoot, "evidence");
    mkdirSync(root);
    mkdirSync(evidence);
    writeFileSync(join(root, "input.txt"), "input\n");
    const catalogue = sdlc.generateReleaseCatalogue({
      releaseVersion: "3.0.0",
      workflowCommit: "1234567890abcdef1234567890abcdef12345678",
      imageDigest:
        "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    });
    const declarationFor = (command: string) =>
      sdlc.validateDeclaration({
        schema: "tc.sdlc/v1",
        project: "lifecycle-prepare",
        toolchains: sdlc.CANONICAL_SDLC_TOOLCHAINS,
        fitness: sdlc.CANONICAL_SDLC_FITNESS,
        projects: [{ name: "fixture", root: "." }],
        targets: {
          prepare: {
            command,
            mode: "prepare",
            trustBoundary: "portable",
            resources: { cpu: 1, memoryMiB: 32, ports: [], exclusive: [] },
            budget: { phaseMs: 5_000, noProgressMs: 2_000, heartbeatMs: 100 },
            inputs: ["input.txt"],
            outputs: [],
          },
        },
      });
    const previous = process.env.TMPDIR;
    const recoveries: sdlc.AutomaticRecoveryReceipt[] = [];
    try {
      for (const [name, command, status] of [
        ["success", `${process.execPath} -e ''`, "succeeded"],
        ["failure", `${process.execPath} -e 'process.exit(2)'`, "failed"],
      ] as const) {
        const runTemporaryRoot = temporary(`tc-sdlc-maintenance-routine-${name}-`);
        process.env.TMPDIR = runTemporaryRoot;
        const interrupted = managedTemporary(
          runTemporaryRoot,
          `tc-sdlc-evaluation-interrupted-${name}`,
          { pid: 2_147_483_647, old: true },
        );
        const declaration = declarationFor(command);
        const result = await sdlc.prepare({
          root,
          declaration,
          catalogue,
          lock: sdlc.resolveLock(declaration, catalogue),
          receiptPath: join(evidence, `${name}.json`),
          runOptions: taskRunOptions({ cpu: 1, memoryMiB: 64 }),
        });
        expect(result.status).toBe(status);
        expect(result.recovery).toMatchObject({
          schema: "tc.sdlc/automatic-recovery/v1",
          candidateCount: 1,
          removedCount: 1,
          cleanupFailures: 0,
        });
        expect(sdlc.canonicalJson(result.recovery)).not.toContain(runTemporaryRoot);
        recoveries.push(result.recovery);
        expect(existsSync(interrupted)).toBe(false);
      }
      expect(recoveries[0]).toEqual(recoveries[1]);
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
      cleanupWorkerMs: 120_000,
      cleanupFailures: 0,
    });
    const receipt = JSON.parse(readFileSync(receiptPath, "utf8"));
    expect(receipt.cleanupWorkerMs).toBe(120_000);
    expect(readFileSync(receiptPath, "utf8")).toBe(sdlc.canonicalJson(receipt));
  });
});
