import * as sdlc from "../dist/index.js";
import { execFileSync, spawnSync } from "node:child_process";
import {
  chmodSync,
  existsSync,
  lstatSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { generateKeyPairSync } from "node:crypto";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, test } from "vitest";

const CLI = fileURLToPath(new URL("../dist/cli.js", import.meta.url));

const release = {
  version: "2.2.0",
  package: { name: "@three-cubes/tc-sdlc", version: "2.2.0" },
  workflowCommit: "1234567890abcdef1234567890abcdef12345678",
  imageDigest:
    "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  declarationSchema: "tc.sdlc/v1",
  lockSchema: "tc.sdlc/lock/v1",
  fitness: { package: "three-cubes-fitness", version: "0.16.1" },
  toolchains: {
    node: "24",
    packageManager: "pnpm@11.22.0",
    python: "3.13",
    uv: "0.12.5",
  },
} as const;

function target(
  command: string,
  mode: "prepare" | "evaluate",
  fields: Readonly<Record<string, unknown>> = {},
) {
  return {
    command,
    mode,
    trustBoundary: "portable",
    resources: { cpu: 1, memoryMiB: 32, ports: [], exclusive: [] },
    budget: { phaseMs: 5_000, noProgressMs: 2_000, heartbeatMs: 100 },
    inputs: ["**/*"],
    outputs: [],
    ...fields,
  };
}

function planning(
  root: string,
  targets: Readonly<Record<string, Record<string, unknown>>>,
) {
  const declaration = {
    schema: "tc.sdlc/v1",
    project: "task4-fixture",
    toolchains: release.toolchains,
    fitness: release.fitness,
    projects: [{ name: "fixture", root: "." }],
    targets,
  } as const;
  const catalogue = sdlc.createReleaseCatalogue(release);
  const lock = sdlc.resolveLock(declaration as never, catalogue);
  return { root, declaration, catalogue, lock };
}

function initialiseGit(root: string): void {
  execFileSync("git", ["init", "-q"], { cwd: root });
  execFileSync("git", ["config", "user.name", "Fixture"], { cwd: root });
  execFileSync("git", ["config", "user.email", "fixture@example.com"], {
    cwd: root,
  });
  execFileSync("git", ["add", "."], { cwd: root });
  execFileSync("git", ["commit", "-qm", "fixture"], { cwd: root });
}

describe("tc-sdlc Task 4", () => {
  test("resolves one canonical inventory that binds bytes, mode and safe symlinks", () => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-inputs-"));
    writeFileSync(join(root, "input.txt"), "one");
    chmodSync(join(root, "input.txt"), 0o640);
    symlinkSync("input.txt", join(root, "alias.txt"));
    const input = planning(root, {
      check: target("node --version", "evaluate", {
        inputs: ["input.txt", "alias.txt"],
      }),
    });

    const first = (sdlc as Record<string, any>).resolveInputInventory(
      root,
      input.declaration,
    );
    expect(first["fixture:check"]).toEqual([
      expect.objectContaining({
        path: "alias.txt",
        mode: expect.any(Number),
        symlink: "input.txt",
      }),
      expect.objectContaining({ path: "input.txt", mode: 0o640, symlink: null }),
    ]);

    chmodSync(join(root, "input.txt"), 0o600);
    const changed = (sdlc as Record<string, any>).resolveInputInventory(
      root,
      input.declaration,
    );
    expect(changed).not.toEqual(first);

    const outside = join(dirname(root), "outside-task4.txt");
    writeFileSync(outside, "outside");
    symlinkSync(outside, join(root, "escape.txt"));
    expect(() =>
      (sdlc as Record<string, any>).resolveInputInventory(root, {
        ...input.declaration,
        targets: {
          check: target("node --version", "evaluate", {
            inputs: ["escape.txt"],
          }),
        },
      }),
    ).toThrowError(expect.objectContaining({ code: "INPUT_PATH_INVALID" }));
  });

  test.each([
    ["fixed point", "writeFileSync(\"generated.txt\", \"stable\")", "succeeded"],
    ["undeclared mutation", "writeFileSync(\"leak.txt\", \"bad\")", "failed"],
    ["execution failure", "process.exit(3)", "failed"],
    [
      "non-fixed point",
      "writeFileSync(\"generated.txt\", crypto.randomUUID())",
      "failed",
    ],
  ])("records preparation %s with durable mutation evidence", async (_name, body, status) => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-prepare-"));
    writeFileSync(
      join(root, "prepare.mjs"),
      `import { writeFileSync } from "node:fs"; ${body};\n`,
    );
    const receiptPath = join(dirname(root), `${root.split("/").at(-1)}-prepare.json`);
    const input = planning(root, {
      generate: target("node prepare.mjs", "prepare", {
        inputs: ["prepare.mjs"],
        outputs: ["generated.txt"],
      }),
    });

    const receipt = await (sdlc as Record<string, any>).prepare({
      ...input,
      receiptPath,
      runOptions: { capacity: { cpu: 1, memoryMiB: 128 } },
    });

    expect(receipt.status).toBe(status);
    expect(readFileSync(receiptPath, "utf8")).toBe(
      (sdlc as Record<string, any>).serialisePreparationReceipt(receipt),
    );
    if (status === "succeeded") {
      expect(receipt.firstPass.mutations).toContainEqual(
        expect.objectContaining({ path: "generated.txt", kind: "add" }),
      );
      expect(receipt.secondPass.mutations).toEqual([]);
    }
  });

  test("check uses affected evaluate selection and rejects source mutation and dirty input", async () => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-check-"));
    writeFileSync(join(root, "input.txt"), "input");
    writeFileSync(
      join(root, "check.mjs"),
      'import { readFileSync } from "node:fs"; console.log(readFileSync("input.txt", "utf8"));\n',
    );
    const input = planning(root, {
      check: target("node check.mjs", "evaluate", {
        inputs: ["input.txt", "check.mjs"],
        outputs: ["result.txt"],
      }),
    });
    writeFileSync(join(root, "result.txt"), "result");
    initialiseGit(root);
    const receiptPath = join(dirname(root), `${root.split("/").at(-1)}-check.json`);

    const receipt = await (sdlc as Record<string, any>).check({
      ...input,
      changedPaths: ["input.txt"],
      receiptPath,
      environmentClass: "native-linux",
      producer: "local-fixture",
      runOptions: { capacity: { cpu: 1, memoryMiB: 128 } },
    });
    expect(receipt.status).toBe("succeeded");
    expect(receipt.scheduler.status).toBe("succeeded");
    expect(receipt.tasks).toHaveLength(1);

    writeFileSync(join(root, "dirty.txt"), "dirty");
    await expect(
      (sdlc as Record<string, any>).check({
        ...input,
        changedPaths: ["input.txt"],
        receiptPath: `${receiptPath}.dirty`,
        environmentClass: "native-linux",
        producer: "local-fixture",
        runOptions: { capacity: { cpu: 1, memoryMiB: 128 } },
      }),
    ).resolves.toMatchObject({ status: "failed", reason: "dirty_source_tree" });
  });

  test("rejects evaluation tree mutation with durable evidence", async () => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-eval-mutation-"));
    writeFileSync(join(root, "input.txt"), "input");
    const input = planning(root, {
      check: target(
        'node -e \'const fs=require("node:fs"); fs.writeFileSync("mutation-a.txt", "bad"); fs.writeFileSync("mutation-b.txt", "bad")\'',
        "evaluate",
        { inputs: ["input.txt"] },
      ),
    });
    initialiseGit(root);
    const receiptPath = join(dirname(root), `${root.split("/").at(-1)}.json`);

    const receipt = await (sdlc as Record<string, any>).checkAll({
      ...input,
      receiptPath,
      environmentClass: "native-linux",
      producer: "local-fixture",
      maxMutations: 1,
      runOptions: { capacity: { cpu: 1, memoryMiB: 128 } },
    });

    expect(receipt).toMatchObject({
      status: "failed",
      reason: "evaluation_mutation",
      mutations: [expect.objectContaining({ path: "mutation-a.txt", kind: "add" })],
      mutationCount: 2,
      mutationsTruncated: true,
    });
    expect(readFileSync(receiptPath, "utf8")).toBe(
      (sdlc as Record<string, any>).serialiseEvaluationReceipt(receipt),
    );
  });

  test.each([
    [
      "delete",
      'import { unlinkSync } from "node:fs"; unlinkSync("victim.txt");',
      "delete",
    ],
    [
      "mode",
      'import { chmodSync } from "node:fs"; chmodSync("victim.txt", 0o600);',
      "mode",
    ],
    [
      "symlink",
      'import { unlinkSync, symlinkSync } from "node:fs"; unlinkSync("link.txt"); symlinkSync("second.txt", "link.txt");',
      "symlink",
    ],
  ])("rejects undeclared preparation %s", async (_name, script, kind) => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-prepare-sabotage-"));
    writeFileSync(join(root, "victim.txt"), "victim");
    writeFileSync(join(root, "second.txt"), "second");
    if (_name === "symlink") {
      symlinkSync("victim.txt", join(root, "link.txt"));
    }
    writeFileSync(join(root, "prepare.mjs"), `${script}\n`);
    const receiptPath = join(dirname(root), `${root.split("/").at(-1)}.json`);
    const input = planning(root, {
      prepare: target("node prepare.mjs", "prepare", {
        inputs: ["prepare.mjs"],
        outputs: ["declared.txt"],
      }),
    });

    const receipt = await (sdlc as Record<string, any>).prepare({
      ...input,
      receiptPath,
      runOptions: { capacity: { cpu: 1, memoryMiB: 128 } },
    });

    expect(receipt).toMatchObject({
      status: "failed",
      reason: "undeclared_mutation",
    });
    expect(receipt.firstPass.mutations).toContainEqual(
      expect.objectContaining({ kind }),
    );
    expect(existsSync(receiptPath)).toBe(true);
  });

  test("writes durable failure evidence for a stale preparation lock", async () => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-prepare-stale-"));
    writeFileSync(join(root, "prepare.mjs"), "process.exit(0);\n");
    const receiptPath = join(dirname(root), `${root.split("/").at(-1)}.json`);
    const input = planning(root, {
      prepare: target("node prepare.mjs", "prepare", {
        inputs: ["prepare.mjs"],
        outputs: ["generated.txt"],
      }),
    });
    const stale = structuredClone(input.lock) as Record<string, unknown>;
    stale.release = "9.9.9";

    const receipt = await (sdlc as Record<string, any>).prepare({
      ...input,
      lock: stale,
      receiptPath,
    });

    expect(receipt.status).toBe("failed");
    expect(receipt.reason).toContain("lock does not match");
    expect(existsSync(receiptPath)).toBe(true);
  });

  test("admits only authentic matching portable evidence and restores uncorrupted cache output", async () => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-evidence-"));
    writeFileSync(join(root, "input.txt"), "input");
    writeFileSync(join(root, "shared.txt"), "shared");
    writeFileSync(join(root, "result.txt"), "result");
    const input = planning(root, {
      check: target("node -e 'process.exit(0)'", "evaluate", {
        inputs: ["input.txt"],
        sharedInputs: ["shared.txt"],
        outputs: ["result.txt"],
      }),
    });
    initialiseGit(root);
    const receipt = await (sdlc as Record<string, any>).checkAll({
      ...input,
      receiptPath: join(dirname(root), `${root.split("/").at(-1)}-all.json`),
      environmentClass: "canonical-linux",
      producer: "trusted-ci",
      runOptions: { capacity: { cpu: 1, memoryMiB: 128 } },
    });
    const { privateKey, publicKey } = generateKeyPairSync("ed25519");
    const now = new Date("2026-09-21T00:00:00.000Z");
    const signed = (sdlc as Record<string, any>).signEvaluationReceipt(receipt, {
      producer: "trusted-ci",
      keyId: "ci-2026",
      privateKey,
      signedAt: now.toISOString(),
      expiresAt: "2026-09-22T00:00:00.000Z",
    });
    const candidate = (sdlc as Record<string, any>).evaluationCandidate(receipt);
    const policy = {
      now: "2026-09-21T12:00:00.000Z",
      producers: {
        "trusted-ci": { keyId: "ci-2026", publicKey },
      },
    };

    expect(
      (sdlc as Record<string, any>).admitEvaluationReceipt(
        signed,
        candidate,
        policy,
      ),
    ).toBe(true);
    const oneByte = (value: string) =>
      `${value.slice(0, -1)}${value.endsWith("0") ? "1" : "0"}`;
    const candidateSabotage: Array<[
      string,
      (value: Record<string, any>) => void,
    ]> = [
      ["source", (value) => { value.source.commit = oneByte(value.source.commit); }],
      ["declaration", (value) => { value.declarationDigest = oneByte(value.declarationDigest); }],
      ["catalogue", (value) => { value.catalogueDigest = oneByte(value.catalogueDigest); }],
      ["lock", (value) => { value.lockDigest = oneByte(value.lockDigest); }],
      ["task", (value) => { value.tasks[0].identity = oneByte(value.tasks[0].identity); }],
      ["input", (value) => { value.tasks[0].inputs[0].digest = oneByte(value.tasks[0].inputs[0].digest); }],
      ["shared input", (value) => { value.tasks[0].inputs[1].digest = oneByte(value.tasks[0].inputs[1].digest); }],
      ["environment", (value) => { value.environmentClass = "different"; }],
      ["output", (value) => { value.tasks[0].outputs[0].digest = oneByte(value.tasks[0].outputs[0].digest); }],
    ];
    for (const [_name, sabotage] of candidateSabotage) {
      const mismatched = structuredClone(candidate) as Record<string, any>;
      sabotage(mismatched);
      expect(() =>
        (sdlc as Record<string, any>).admitEvaluationReceipt(
          signed,
          mismatched,
          policy,
        ),
      ).toThrowError(expect.objectContaining({ code: "EVIDENCE_CANDIDATE_MISMATCH" }));
    }
    expect(() =>
      (sdlc as Record<string, any>).admitEvaluationReceipt(signed, candidate, {
        ...policy,
        producers: {},
      }),
    ).toThrowError(expect.objectContaining({ code: "EVIDENCE_PRODUCER_INVALID" }));
    expect(() =>
      (sdlc as Record<string, any>).admitEvaluationReceipt(
        undefined,
        candidate,
        policy,
      ),
    ).toThrowError(expect.objectContaining({ code: "EVIDENCE_SIGNATURE_INVALID" }));
    const bad = structuredClone(signed);
    bad.signature.value = `${bad.signature.value.slice(0, -2)}AA`;
    expect(() =>
      (sdlc as Record<string, any>).admitEvaluationReceipt(bad, candidate, policy),
    ).toThrowError(expect.objectContaining({ code: "EVIDENCE_SIGNATURE_INVALID" }));
    expect(() =>
      (sdlc as Record<string, any>).admitEvaluationReceipt(signed, candidate, {
        ...policy,
        now: "2026-09-23T00:00:00.000Z",
      }),
    ).toThrowError(expect.objectContaining({ code: "EVIDENCE_EXPIRED" }));
    for (const status of ["failed", "cancelled", "stalled"] as const) {
      const terminal = structuredClone(signed) as Record<string, any>;
      terminal.receipt.status = status === "cancelled" ? "failed" : status;
      terminal.receipt.scheduler.status = status;
      expect(() =>
        (sdlc as Record<string, any>).admitEvaluationReceipt(
          terminal,
          candidate,
          policy,
        ),
      ).toThrowError(expect.objectContaining({ code: "EVIDENCE_STATUS_INVALID" }));
    }
    const hostedReceipt = structuredClone(receipt) as Record<string, any>;
    hostedReceipt.tasks[0].trustBoundary = "hosted";
    const hostedSigned = (sdlc as Record<string, any>).signEvaluationReceipt(
      hostedReceipt,
      {
        producer: "trusted-ci",
        keyId: "ci-2026",
        privateKey,
        signedAt: now.toISOString(),
        expiresAt: "2026-09-22T00:00:00.000Z",
      },
    );
    expect(() =>
      (sdlc as Record<string, any>).admitEvaluationReceipt(
        hostedSigned,
        (sdlc as Record<string, any>).evaluationCandidate(hostedReceipt),
        policy,
      ),
    ).toThrowError(expect.objectContaining({ code: "EVIDENCE_BOUNDARY_INVALID" }));

    const cache = mkdtempSync(join(tmpdir(), "tc-sdlc-cache-"));
    const entry = (sdlc as Record<string, any>).storeEvaluationCache(
      root,
      cache,
      receipt,
    );
    const manifestPath = join(cache, entry.key, "manifest.json");
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    const forged = structuredClone(manifest);
    const injectedPath = join(cache, entry.key, "files", "injected.txt");
    writeFileSync(injectedPath, "injected");
    chmodSync(injectedPath, 0o644);
    forged.receipt.tasks[0].outputs.push({
      path: "injected.txt",
      digest: (sdlc as Record<string, any>).bytesDigest("injected"),
      mode: 0o644,
      symlink: null,
    });
    writeFileSync(manifestPath, JSON.stringify(forged));
    writeFileSync(join(root, "result.txt"), "unchanged-on-rejection");
    expect(() =>
      (sdlc as Record<string, any>).restoreEvaluationCache(
        root,
        cache,
        entry.key,
        candidate,
      ),
    ).toThrowError(expect.objectContaining({ code: "CACHE_CANDIDATE_MISMATCH" }));
    expect(existsSync(join(root, "injected.txt"))).toBe(false);
    expect(readFileSync(join(root, "result.txt"), "utf8")).toBe(
      "unchanged-on-rejection",
    );
    writeFileSync(manifestPath, JSON.stringify(manifest));
    rmSync(injectedPath);
    writeFileSync(join(root, "result.txt"), "corrupt");
    expect(
      (sdlc as Record<string, any>).restoreEvaluationCache(
        root,
        cache,
        entry.key,
        candidate,
      ),
    ).toBe(true);
    expect(readFileSync(join(root, "result.txt"), "utf8")).toBe("result");
    expect(lstatSync(join(root, "result.txt")).isFile()).toBe(true);
    expect(existsSync(join(cache, entry.key))).toBe(true);
    writeFileSync(join(root, "result.txt"), "corrupt-source-output");
    expect(() =>
      (sdlc as Record<string, any>).storeEvaluationCache(root, cache, receipt),
    ).toThrowError(expect.objectContaining({ code: "CACHE_OUTPUT_MISMATCH" }));
    writeFileSync(join(cache, entry.key, "files", "result.txt"), "corrupt");
    expect(() =>
      (sdlc as Record<string, any>).restoreEvaluationCache(
        root,
        cache,
        entry.key,
        candidate,
      ),
    ).toThrowError(expect.objectContaining({ code: "CACHE_CORRUPT" }));
    expect(() =>
      (sdlc as Record<string, any>).storeEvaluationCache(
        root,
        cache,
        hostedReceipt,
      ),
    ).toThrowError(expect.objectContaining({ code: "CACHE_ENTRY_INVALID" }));
  });

  test("keeps canonical input and task identity stable across location and discovery order", () => {
    const roots = [
      mkdtempSync(join(tmpdir(), "tc-sdlc-stable-a-")),
      mkdtempSync(join(tmpdir(), "tc-sdlc-stable-b-")),
    ];
    writeFileSync(join(roots[0]!, "a.txt"), "a");
    writeFileSync(join(roots[0]!, "b.txt"), "b");
    writeFileSync(join(roots[1]!, "b.txt"), "b");
    writeFileSync(join(roots[1]!, "a.txt"), "a");
    const inputs = roots.map((root) =>
      planning(root, {
        check: target("node --version", "evaluate", {
          inputs: ["*.txt"],
        }),
      }),
    );
    const inventories = inputs.map((input) =>
      (sdlc as Record<string, any>).resolveInputInventory(
        input.root,
        input.declaration,
      ),
    );
    expect(inventories[0]).toEqual(inventories[1]);
    const identities = inputs.map((input, index) => {
      const bound = (sdlc as Record<string, any>).bindGraphLock(
        input.declaration,
        input.lock,
        input.catalogue,
        inventories[index],
      );
      return (sdlc as Record<string, any>).buildGraph(
        input.declaration,
        bound,
      ).tasks[0].identity;
    });
    expect(identities[0]).toBe(identities[1]);
  });

  test("check-all runs every evaluate task once and never runs prepare tasks", async () => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-phase-"));
    const executionLog = join(dirname(root), `${root.split("/").at(-1)}.log`);
    writeFileSync(
      join(root, "evaluate.mjs"),
      'import { appendFileSync } from "node:fs"; appendFileSync(process.env.EXECUTION_LOG, process.argv[2]);\n',
    );
    const input = planning(root, {
      prepare: target(
        'node -e \'require("node:fs").writeFileSync("prepare-ran", "bad")\'',
        "prepare",
        { inputs: ["evaluate.mjs"], outputs: ["prepare-ran"] },
      ),
      alpha: target("node evaluate.mjs a", "evaluate", {
        inputs: ["evaluate.mjs"],
      }),
      beta: target("node evaluate.mjs b", "evaluate", {
        inputs: ["evaluate.mjs"],
      }),
    });
    initialiseGit(root);

    const receipt = await (sdlc as Record<string, any>).checkAll({
      ...input,
      receiptPath: join(dirname(root), `${root.split("/").at(-1)}.json`),
      environmentClass: "native-linux",
      producer: "local-fixture",
      runOptions: {
        capacity: { cpu: 1, memoryMiB: 128 },
        environment: { EXECUTION_LOG: executionLog },
      },
    });

    expect(receipt.status).toBe("succeeded");
    expect(receipt.tasks.map((task: Record<string, unknown>) => task.key)).toEqual([
      "fixture:alpha",
      "fixture:beta",
    ]);
    expect([...readFileSync(executionLog, "utf8")].sort()).toEqual(["a", "b"]);
    expect(existsSync(join(root, "prepare-ran"))).toBe(false);
  });

  test("requires exact succeeded fixed-point preparation evidence across the phase boundary", async () => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-phase-proof-"));
    writeFileSync(
      join(root, "prepare.mjs"),
      'import { writeFileSync } from "node:fs"; writeFileSync("generated.txt", "stable");\n',
    );
    writeFileSync(
      join(root, "check.mjs"),
      'import { existsSync } from "node:fs"; if (!existsSync("generated.txt")) process.exit(7);\n',
    );
    writeFileSync(join(root, "input.txt"), "one");
    const input = planning(root, {
      prepare: target("node prepare.mjs", "prepare", {
        inputs: ["prepare.mjs"],
        outputs: ["generated.txt"],
      }),
      check: target("node check.mjs", "evaluate", {
        dependsOn: ["prepare"],
        inputs: ["input.txt", "check.mjs"],
      }),
    });
    initialiseGit(root);
    const preparation = await (sdlc as Record<string, any>).prepare({
      ...input,
      receiptPath: join(dirname(root), `${root.split("/").at(-1)}-prepare.json`),
      runOptions: { capacity: { cpu: 1, memoryMiB: 128 } },
    });
    expect(preparation.status).toBe("succeeded");
    expect(
      execFileSync("git", ["status", "--porcelain=v1", "--untracked-files=all"], {
        cwd: root,
        encoding: "utf8",
      }),
    ).toContain("generated.txt");
    const observed: Record<string, unknown>[] = [];
    const evaluation = (preparationReceipt: unknown, suffix: string) =>
      (sdlc as Record<string, any>).check({
        ...input,
        changedPaths: ["input.txt"],
        receiptPath: join(dirname(root), `${root.split("/").at(-1)}-${suffix}.json`),
        environmentClass: "native-linux",
        producer: "local-fixture",
        ...(preparationReceipt === undefined ? {} : { preparationReceipt }),
        runOptions: {
          capacity: { cpu: 1, memoryMiB: 128 },
          onEvent: (event: Record<string, unknown>) => observed.push(event),
        },
      });

    await expect(evaluation(undefined, "missing")).resolves.toMatchObject({
      status: "failed",
      reason: "preparation_evidence_invalid",
    });
    const failed = structuredClone(preparation) as Record<string, any>;
    failed.status = "failed";
    await expect(evaluation(failed, "failed")).resolves.toMatchObject({
      status: "failed",
      reason: "preparation_evidence_invalid",
    });
    const nonFixed = structuredClone(preparation) as Record<string, any>;
    nonFixed.secondPass.mutations = [{ path: "generated.txt", kind: "content" }];
    nonFixed.secondPass.mutationCount = 1;
    await expect(evaluation(nonFixed, "non-fixed")).resolves.toMatchObject({
      status: "failed",
      reason: "preparation_evidence_invalid",
    });
    expect(observed).toEqual([]);
    await expect(
      evaluation(preparation, "valid-prepared-tree"),
    ).resolves.toMatchObject({ status: "succeeded", reason: null });

    writeFileSync(join(root, "input.txt"), "two");
    await expect(evaluation(preparation, "stale-input")).resolves.toMatchObject({
      status: "failed",
      reason: "preparation_evidence_invalid",
    });
    writeFileSync(join(root, "input.txt"), "one");
    writeFileSync(join(root, "generated.txt"), "post-receipt-drift");
    await expect(evaluation(preparation, "stale-output")).resolves.toMatchObject({
      status: "failed",
      reason: "preparation_evidence_invalid",
    });
  });

  test("exposes prepare, check and check-all through the built CLI", () => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-task4-cli-"));
    const receiptRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-task4-cli-evidence-"));
    writeFileSync(
      join(root, "prepare.mjs"),
      'import { writeFileSync } from "node:fs"; writeFileSync("generated.txt", "stable");\n',
    );
    writeFileSync(join(root, "input.txt"), "input");
    writeFileSync(join(root, "result.txt"), "result");
    writeFileSync(
      join(root, "sdlc.yaml"),
      `schema: tc.sdlc/v1
project: cli-fixture
toolchains: {python: "3.13", node: "24", packageManager: pnpm@11.22.0, uv: "0.12.5"}
fitness: {package: three-cubes-fitness, version: "0.16.1"}
projects: [{name: fixture, root: .}]
targets:
  prepare:
    command: node prepare.mjs
    mode: prepare
    trustBoundary: portable
    inputs: [prepare.mjs]
    outputs: [generated.txt]
  check:
    command: node -e 'process.exit(0)'
    mode: evaluate
    trustBoundary: portable
    dependsOn: [prepare]
    inputs: [input.txt]
    outputs: [result.txt]
`,
    );
    writeFileSync(join(root, "catalogue.json"), `${JSON.stringify({
      schema: "tc.sdlc/release-catalogue/v1",
      release,
    })}\n`);
    const lockPath = join(root, "tc-sdlc.lock");
    const common = [
      "--declaration", join(root, "sdlc.yaml"),
      "--catalogue", join(root, "catalogue.json"),
      "--lock", lockPath,
      "--root", root,
    ];
    expect(spawnSync(CLI, [
      "lock", "--declaration", join(root, "sdlc.yaml"),
      "--catalogue", join(root, "catalogue.json"), "--output", lockPath,
    ]).status).toBe(0);

    const preparationReceiptPath = join(receiptRoot, "prepare.json");
    const prepared = spawnSync(CLI, [
      "prepare", ...common, "--receipt", preparationReceiptPath,
    ], { encoding: "utf8" });
    expect(prepared.status, prepared.stderr).toBe(0);
    initialiseGit(root);
    for (const [command, extra] of [
      ["check", ["--changed", "input.txt"]],
      ["check-all", []],
    ] as const) {
      const result = spawnSync(CLI, [
        command,
        ...common,
        "--receipt", join(receiptRoot, `${command}.json`),
        "--environment", "native-linux",
        "--producer", "cli-fixture",
        "--preparation-receipt", preparationReceiptPath,
        ...extra,
      ], { encoding: "utf8" });
      expect(result.status, result.stderr).toBe(0);
      expect(JSON.parse(result.stdout)).toMatchObject({
        command,
        status: "ok",
      });
    }
  });
});
