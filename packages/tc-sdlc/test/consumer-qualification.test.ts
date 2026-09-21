import { execFileSync, spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdtempSync, readFileSync, readdirSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { beforeEach, describe, expect, test } from "vitest";

const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const fixtureManifest = fileURLToPath(
  new URL("../../../assurance/fixtures/sdlc/consumers.yaml", import.meta.url),
);

function packedCli(): string {
  const packageDirectory = mkdtempSync(join(tmpdir(), "tc-sdlc-packed-package-"));
  execFileSync("pnpm", ["pack", "--pack-destination", packageDirectory], {
    cwd: packageRoot,
    encoding: "utf8",
  });
  const archiveName = readdirSync(packageDirectory).find((name) => name.endsWith(".tgz"));
  if (archiveName === undefined) throw new Error("pnpm pack did not produce an archive");
  const archive = join(packageDirectory, archiveName);
  return archive;
}

function installPackedCli(): string {
  const archive = packedCli();
  const installation = mkdtempSync(join(tmpdir(), "tc-sdlc-packed-installation-"));
  execFileSync(
    "pnpm",
    ["add", "--ignore-scripts", "--lockfile=false", archive],
    { cwd: installation, encoding: "utf8" },
  );
  return join(installation, "node_modules", ".bin", "tc-sdlc");
}

function copiedManifest(rewrite: (manifest: string) => string): string {
  const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-consumer-manifest-"));
  cpSync(dirname(fixtureManifest), directory, { recursive: true });
  const manifest = join(directory, "consumers.yaml");
  writeFileSync(manifest, rewrite(readFileSync(manifest, "utf8")));
  return manifest;
}

function qualification(cli: string, manifest: string) {
  const root = mkdtempSync(join(tmpdir(), "tc-sdlc-consumer-qualification-"));
  const output = join(root, "qualification");
  const receipt = join(output, "consumer-qualification.json");
  return {
    output,
    receipt,
    result: spawnSync(
      cli,
      ["qualify-consumers", "--manifest", manifest, "--output", output, "--receipt", receipt],
      { encoding: "utf8" },
    ),
  };
}

function failedQualification(cli: string, manifest: string) {
  const run = qualification(cli, manifest);
  expect(run.result.error).toBeUndefined();
  expect(run.result.status).toBe(1);
  expect(run.result.stdout).toBe("");
  expect(JSON.parse(run.result.stderr)).toMatchObject({
    schema: "tc.sdlc/command-error/v1",
    command: "qualify-consumers",
    status: "error",
    error: { code: "CONSUMER_QUALIFICATION_FAILED" },
  });
  return { ...run, receipt: JSON.parse(readFileSync(run.receipt, "utf8")) };
}

describe("tc-sdlc qualify-consumers", () => {
  let cli: string;

  beforeEach(() => {
    cli = installPackedCli();
  }, 30_000);

  test("qualifies the Python, pnpm and mixed disposable consumers through the packed CLI", () => {
    const run = qualification(cli, fixtureManifest);
    const { output, receipt, result } = run;

    expect(result.status).toBe(0);
    expect(result.stderr).toBe("");
    expect(JSON.parse(result.stdout)).toMatchObject({
      schema: "tc.sdlc/command-result/v1",
      command: "qualify-consumers",
      status: "ok",
      receipt,
      receiptSchema: "tc.sdlc/consumer-qualification/v1",
    });
    expect(existsSync(receipt)).toBe(true);
    const receiptValue = JSON.parse(readFileSync(receipt, "utf8"));
    expect(receiptValue).toMatchObject({
      schema: "tc.sdlc/consumer-qualification/v1",
      status: "succeeded",
      fixtures: expect.arrayContaining([
        expect.objectContaining({ id: "python", status: "succeeded" }),
        expect.objectContaining({ id: "pnpm", status: "succeeded" }),
        expect.objectContaining({ id: "mixed", status: "succeeded" }),
      ]),
    });
  }, 180_000);

  test("rejects an unknown manifest field while retaining a terminal outer receipt", () => {
    const manifest = copiedManifest((value) => `${value}unexpected: rejected\n`);
    const run = failedQualification(cli, manifest);
    expect(run.receipt).toMatchObject({
      schema: "tc.sdlc/consumer-qualification/v1",
      status: "failed",
      fixtures: [],
    });
  });

  test("rejects duplicate consumer identities", () => {
    const manifest = copiedManifest((value) => value.replace("  - id: pnpm", "  - id: python"));
    const run = failedQualification(cli, manifest);
    expect(run.receipt.reason).toContain("consumer id must be unique");
  });

  test("rejects fixture traversal before copying a consumer", () => {
    const manifest = copiedManifest((value) => value.replace("fixture: python", "fixture: ../python"));
    const run = failedQualification(cli, manifest);
    expect(run.receipt.fixtures).toEqual([
      expect.objectContaining({ id: "python", status: "failed", fixtureDigest: null }),
    ]);
  });

  test("rejects a symlinked fixture before copying a consumer", () => {
    const manifest = copiedManifest((value) => value.replace("fixture: python", "fixture: linked-python"));
    const directory = dirname(manifest);
    symlinkSync(join(directory, "python"), join(directory, "linked-python"));
    try {
      const run = failedQualification(cli, manifest);
      expect(run.receipt.reason).toContain("symbolic links");
    } finally {
      unlinkSync(join(directory, "linked-python"));
    }
  });

  test("rejects a missing dependency lock before bootstrap", () => {
    const manifest = copiedManifest((value) => value);
    unlinkSync(join(dirname(manifest), "python", "uv.lock"));
    const run = failedQualification(cli, manifest);
    expect(run.receipt.reason).toContain("missing uv.lock");
  });

  test("rejects a complete task-set mismatch after retaining nested receipts", () => {
    const manifest = copiedManifest((value) => value.replace("complete_tasks: [node-service:check]", "complete_tasks: [not-a-task]"));
    const run = failedQualification(cli, manifest);
    const pnpm = run.receipt.fixtures.find((fixture: { id: string }) => fixture.id === "pnpm");
    expect(pnpm).toMatchObject({
      status: "failed",
      complete: { status: "succeeded", path: "pnpm/evidence/complete.json" },
    });
  }, 180_000);
});
