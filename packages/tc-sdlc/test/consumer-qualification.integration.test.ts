import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { chmodSync, cpSync, existsSync, lstatSync, mkdtempSync, readFileSync, readlinkSync, readdirSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { beforeEach, describe, expect, test } from "vitest";

const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const fixtureManifest = fileURLToPath(
  new URL("../../../assurance/fixtures/sdlc/consumers.yaml", import.meta.url),
);
const candidateCatalogue = fileURLToPath(new URL("../../../release/catalogue.json", import.meta.url));

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

function qualification(
  cli: string,
  manifest: string,
  receiptRelative = "consumer-qualification.json",
  environment: NodeJS.ProcessEnv = {},
) {
  const root = mkdtempSync(join(tmpdir(), "tc-sdlc-consumer-qualification-"));
  const output = join(root, "qualification");
  const receipt = join(output, receiptRelative);
  return {
    output,
    receipt,
    result: spawnSync(
      cli,
      ["qualify-consumers", "--manifest", manifest, "--catalogue", candidateCatalogue, "--output", output, "--receipt", receipt],
      { encoding: "utf8", env: { ...process.env, ...environment } },
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

function sha256(path: string): string {
  return `sha256:${createHash("sha256").update(readFileSync(path)).digest("hex")}`;
}

function independentlyDigestedFixture(root: string): string {
  const files: { digest: string; mode: number; path: string; symlink: string | null }[] = [];
  const visit = (directory: string, relative = ""): void => {
    for (const name of readdirSync(directory).sort()) {
      if (relative === "" && name === ".git") continue;
      const absolute = join(directory, name);
      const path = relative === "" ? name : `${relative}/${name}`;
      const metadata = lstatSync(absolute);
      if (metadata.isDirectory()) { visit(absolute, path); continue; }
      const symlink = metadata.isSymbolicLink() ? readlinkSync(absolute) : null;
      const bytes = symlink === null ? readFileSync(absolute) : readFileSync(join(dirname(absolute), symlink));
      files.push({
        digest: `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
        mode: metadata.mode & 0o777,
        path,
        symlink,
      });
    }
  };
  visit(root);
  return `sha256:${createHash("sha256").update(`${JSON.stringify(files, null, 2)}\n`).digest("hex")}`;
}

function evaluationIdentities(receipt: { tasks: readonly { identity: string }[] }): readonly string[] {
  return receipt.tasks.map((task) => task.identity).sort();
}

function taskInventories(receipt: { tasks: readonly { key: string; inputs: unknown; outputs: unknown }[] }): readonly unknown[] {
  return receipt.tasks
    .map((task) => ({ key: task.key, inputs: task.inputs, outputs: task.outputs }))
    .sort((left, right) => left.key.localeCompare(right.key));
}

function expectRunReceiptShape(value: Record<string, unknown>): void {
  expect(Object.keys(value).sort()).toEqual(["bootstrapContext", "declarationDigest", "lockDigest", "reason", "schema", "scratchCleanup", "scratchId", "selection", "status", "tasks"].sort());
  expect(value.schema).toBe("tc.sdlc/run-receipt/v1");
  expect(value.status).toMatch(/^(succeeded|failed|stalled|cancelled)$/);
  for (const identity of value.selection as unknown[]) expect(identity).toMatch(/^sha256:[a-f0-9]{64}$/);
  const context = value.bootstrapContext as Record<string, unknown>;
  expect(Object.keys(context).sort()).toEqual(["adapters", "architecture", "bootstrapReceiptDigest", "dependencyDigest", "fitness", "lockDigest", "platform", "release", "schema", "stateDigest", "stateGenerationIdentity", "stateKey"].sort());
  for (const task of value.tasks as Record<string, unknown>[]) {
    expect(Object.keys(task).sort()).toEqual(["events", "evidence", "executionContextDigest", "exitCode", "identity", "key", "missingEvidence", "outputTruncated", "reason", "resources", "scratchId", "status", "stderr", "stdout"].sort());
    expect(Object.keys(task.resources as Record<string, unknown>).sort()).toEqual(["cpu", "exclusive", "memoryMiB", "ports"]);
    for (const event of task.events as Record<string, unknown>[]) {
      expect(Object.keys(event).sort()).toEqual(expect.arrayContaining(["taskIdentity", "taskKey", "type"]));
      expect(Object.keys(event).every((key) => ["taskIdentity", "taskKey", "type", "stream", "text", "status", "reason"].includes(key))).toBe(true);
    }
  }
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
    expect(receiptValue.manifestDigest).toBe(sha256(fixtureManifest));
    expect(receiptValue.catalogueDigest).toBe(sha256(candidateCatalogue));
    expect(JSON.parse(readFileSync(join(output, "candidate-catalogue.json"), "utf8"))).toEqual(JSON.parse(readFileSync(candidateCatalogue, "utf8")));
    for (const fixture of receiptValue.fixtures) {
      expect(fixture.fixtureDigest).toBe(independentlyDigestedFixture(join(dirname(fixtureManifest), fixture.id)));
      expect(fixture.preparation.firstPassTaskIdentities.length).toBeGreaterThan(0);
      expect(fixture.preparation.secondPassTaskIdentities.length).toBeGreaterThan(0);
      for (const [name, schema] of [
        ["bootstrap", "tc.sdlc/bootstrap-receipt/v1"],
        ["preparation", "tc.sdlc/preparation-receipt/v1"],
        ["complete", "tc.sdlc/evaluation-receipt/v1"],
        ["affected", "tc.sdlc/evaluation-receipt/v1"],
      ] as const) {
        const reference = fixture[name];
        const nestedPath = join(output, reference.path);
        expect(reference.digest).toBe(sha256(nestedPath));
        const nested = JSON.parse(readFileSync(nestedPath, "utf8"));
        expect(nested).toMatchObject({ schema, status: "succeeded" });
        expect(Object.keys(nested).sort()).toEqual(
          schema === "tc.sdlc/bootstrap-receipt/v1"
            ? ["adapters", "architecture", "dependencies", "diagnostics", "diagnosticsCount", "diagnosticsTruncated", "lockDigest", "platform", "reason", "recovery", "release", "reused", "schema", "stateDigest", "stateKey", "status", "taskIdentities"].sort()
            : schema === "tc.sdlc/preparation-receipt/v1"
              ? ["bootstrapContext", "catalogueDigest", "declarationDigest", "finalTreeDigest", "firstPass", "lockDigest", "reason", "recovery", "schema", "secondPass", "status"].sort()
              : ["bootstrapContext", "catalogueDigest", "declarationDigest", "environmentClass", "lockDigest", "mutationCount", "mutations", "mutationsTruncated", "producer", "reason", "recovery", "schema", "source", "status", "tasks", "scheduler"].sort(),
        );
        if (schema === "tc.sdlc/preparation-receipt/v1") {
          for (const pass of [nested.firstPass, nested.secondPass]) {
            expect(Object.keys(pass).sort()).toEqual(expect.arrayContaining(["mutationCount", "mutations", "mutationsTruncated"]));
            if (pass.scheduler !== undefined) expectRunReceiptShape(pass.scheduler);
          }
        }
        if (schema === "tc.sdlc/evaluation-receipt/v1") {
          expect(Object.keys(nested.source).sort()).toEqual(["commit", "treeDigest"]);
          expectRunReceiptShape(nested.scheduler);
        }
      }
      for (const name of ["complete", "affected"] as const) {
        const receiptPath = join(output, fixture[name].path);
        const oneSlot = JSON.parse(readFileSync(`${receiptPath}.single`, "utf8"));
        const detected = JSON.parse(readFileSync(receiptPath, "utf8"));
        expect(evaluationIdentities(oneSlot)).toEqual(evaluationIdentities(detected));
        expect(taskInventories(oneSlot)).toEqual(taskInventories(detected));
      }
    }
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

  test("rejects fixture Git metadata before it can route Git outside the disposable checkout", () => {
    const manifest = copiedManifest((value) => value);
    const external = mkdtempSync(join(tmpdir(), "tc-sdlc-external-git-"));
    writeFileSync(join(dirname(manifest), "python", ".git"), `gitdir: ${external}\n`);
    const run = qualification(cli, manifest);
    expect(run.result.status).toBe(1);
    expect(run.result.stderr).toContain("fixture may not contain Git metadata");
    expect(readFileSync(join(dirname(manifest), "python", ".git"), "utf8")).toBe(`gitdir: ${external}\n`);
    expect(existsSync(join(external, "HEAD"))).toBe(false);
  });

  test("rejects platform-equivalent Git metadata before copying the fixture", () => {
    const manifest = copiedManifest((value) => value);
    writeFileSync(join(dirname(manifest), "python", ".GIT"), "foreign metadata\n");
    const run = qualification(cli, manifest);
    expect(run.result.status).toBe(1);
    expect(run.result.stderr).toContain("fixture may not contain Git metadata");
  });

  test("does not honour hostile inherited Git routing when creating a checkout", () => {
    const external = mkdtempSync(join(tmpdir(), "tc-sdlc-external-git-routing-"));
    const run = qualification(cli, fixtureManifest, "consumer-qualification.json", { GIT_DIR: external });
    expect(run.result.status).toBe(0);
    expect(existsSync(join(external, "HEAD"))).toBe(false);
  }, 180_000);

  test("does not resolve dependencies from hostile ambient command shadows", () => {
    const shadow = mkdtempSync(join(tmpdir(), "tc-sdlc-dependency-shadow-"));
    const marker = join(shadow, "used");
    for (const executable of ["uv", "pnpm"]) {
      const path = join(shadow, executable);
      writeFileSync(path, `#!/usr/bin/env node\nrequire('node:fs').writeFileSync(${JSON.stringify(marker)}, 'used')\nprocess.exit(99)\n`);
      chmodSync(path, 0o755);
    }
    const run = qualification(cli, fixtureManifest, "consumer-qualification.json", { PATH: `${shadow}:${process.env.PATH}` });
    expect(run.result.status).toBe(0);
    expect(existsSync(marker)).toBe(false);
  }, 180_000);

  test("rejects a missing dependency lock before bootstrap", () => {
    const manifest = copiedManifest((value) => value);
    unlinkSync(join(dirname(manifest), "python", "uv.lock"));
    const run = failedQualification(cli, manifest);
    expect(run.receipt.reason).toContain("missing uv.lock");
  });

  test("retains the actual failed nested preparation receipt", () => {
    const manifest = copiedManifest((value) => value);
    const preparation = join(dirname(manifest), "python", "scripts", "prepare.py");
    writeFileSync(preparation, `${readFileSync(preparation, "utf8")}\nraise SystemExit(1)\n`);
    const run = failedQualification(cli, manifest);
    const python = run.receipt.fixtures.find((fixture: { id: string }) => fixture.id === "python");
    expect(python).toMatchObject({
      status: "failed",
      preparation: { path: "python/evidence/preparation.json", status: "failed" },
    });
    expect(sha256(join(run.output, python.preparation.path))).toBe(python.preparation.digest);
    expect(JSON.parse(readFileSync(join(run.output, python.preparation.path), "utf8"))).toMatchObject({
      schema: "tc.sdlc/preparation-receipt/v1",
      status: "failed",
    });
  }, 180_000);

  test("retains an outer receipt when a hostile fixture corrupts nested evidence", () => {
    const manifest = copiedManifest((value) => value);
    const scripts = join(dirname(manifest), "python", "scripts");
    writeFileSync(join(scripts, "corrupt-preparation.py"), [
      "from pathlib import Path",
      "import time",
      "receipt = Path(__file__).resolve().parents[3] / 'python' / 'evidence' / 'preparation.json'",
      "for _ in range(500):",
      "    if receipt.exists():",
      "        receipt.write_text('null\\n')",
      "        raise SystemExit(0)",
      "    time.sleep(0.01)",
    ].join("\n"));
    const preparation = join(scripts, "prepare.py");
    writeFileSync(preparation, `${readFileSync(preparation, "utf8")}\nfrom subprocess import DEVNULL, Popen\nimport sys\nPopen([sys.executable, 'scripts/corrupt-preparation.py'], stdout=DEVNULL, stderr=DEVNULL, start_new_session=True)\n`);
    const run = failedQualification(cli, manifest);
    const python = run.receipt.fixtures.find((fixture: { id: string }) => fixture.id === "python");
    expect(python).toMatchObject({
      status: "failed",
      preparation: { path: "python/evidence/preparation.json", status: null },
    });
    expect(existsSync(join(run.output, python.preparation.path))).toBe(true);
    expect(readFileSync(join(run.output, python.preparation.path), "utf8")).toBe("null\n");
  }, 180_000);

  test("retains an outer receipt for invalid preparation selections and unknown nested fields", () => {
    const manifest = copiedManifest((value) => value);
    const scripts = join(dirname(manifest), "python", "scripts");
    writeFileSync(join(scripts, "corrupt-preparation-shape.py"), [
      "from pathlib import Path",
      "import json",
      "import time",
      "receipt = Path(__file__).resolve().parents[3] / 'python' / 'evidence' / 'preparation.json'",
      "for _ in range(500):",
      "    if receipt.exists():",
      "        value = json.loads(receipt.read_text())",
      "        value['firstPass']['scheduler']['selection'] = ['not-a-digest']",
      "        value['firstPass']['unexpected'] = True",
      "        receipt.write_text(json.dumps(value, separators=(',', ':')))",
      "        raise SystemExit(0)",
      "    time.sleep(0.01)",
    ].join("\n"));
    const preparation = join(scripts, "prepare.py");
    writeFileSync(preparation, `${readFileSync(preparation, "utf8")}\nfrom subprocess import DEVNULL, Popen\nimport sys\nPopen([sys.executable, 'scripts/corrupt-preparation-shape.py'], stdout=DEVNULL, stderr=DEVNULL, start_new_session=True)\n`);
    const run = failedQualification(cli, manifest);
    const python = run.receipt.fixtures.find((fixture: { id: string }) => fixture.id === "python");
    expect(python).toMatchObject({
      status: "failed",
      preparation: { path: "python/evidence/preparation.json", status: null, firstPassTaskIdentities: [] },
    });
  }, 180_000);

  test("reserves the outer receipt path from nested qualification evidence", () => {
    const run = qualification(cli, fixtureManifest, "python/evidence/complete.json");
    expect(run.result.status).toBe(1);
    expect(run.result.stderr).toContain("outer receipt path collides");
  });

  test("reserves consumer directories from an outer receipt collision", () => {
    const run = qualification(cli, fixtureManifest, "python");
    expect(run.result.status).toBe(1);
    expect(run.result.stderr).toContain("outer receipt path collides");
  });

  test("reserves case-equivalent owned receipt namespaces", () => {
    for (const receipt of ["CANDIDATE-CATALOGUE.JSON", "Python"]) {
      const run = qualification(cli, fixtureManifest, receipt);
      expect(run.result.status).toBe(1);
      expect(run.result.stderr).toContain("outer receipt path collides");
      expect(JSON.parse(readFileSync(run.receipt, "utf8"))).toMatchObject({ status: "failed" });
    }
  });

  test("rejects an outside receipt before creating an owned output directory", () => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-consumer-output-boundary-"));
    const output = join(root, "qualification");
    const result = spawnSync(
      cli,
      ["qualify-consumers", "--manifest", fixtureManifest, "--catalogue", candidateCatalogue, "--output", output, "--receipt", join(root, "outside.json")],
      { encoding: "utf8" },
    );
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("receipt must be below the owned output directory");
    expect(existsSync(output)).toBe(false);
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

  test("rejects an affected-closure mismatch after retaining nested affected evidence", () => {
    const manifest = copiedManifest((value) => value.replace("affected_tasks: [node-service:check]", "affected_tasks: [not-a-task]"));
    const run = failedQualification(cli, manifest);
    const pnpm = run.receipt.fixtures.find((fixture: { id: string }) => fixture.id === "pnpm");
    expect(pnpm).toMatchObject({
      status: "failed",
      affected: { status: "succeeded", path: "pnpm/evidence/affected.json" },
    });
  }, 180_000);
});
