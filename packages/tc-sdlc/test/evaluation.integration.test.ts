import { execFileSync, spawnSync } from "node:child_process";
import { cpSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { beforeAll, describe, expect, test } from "vitest";

const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const fixtureRoot = fileURLToPath(new URL("../../../assurance/fixtures/sdlc/python", import.meta.url));
const candidateCatalogue = fileURLToPath(new URL("../../../release/catalogue.json", import.meta.url));

function installPackedCli(): string {
  const packages = mkdtempSync(join(tmpdir(), "tc-sdlc-evaluation-package-"));
  execFileSync("pnpm", ["pack", "--pack-destination", packages], { cwd: packageRoot, encoding: "utf8" });
  const archive = readdirSync(packages).find((name) => name.endsWith(".tgz"));
  if (archive === undefined) throw new Error("pnpm pack did not produce an archive");
  const installation = mkdtempSync(join(tmpdir(), "tc-sdlc-evaluation-installation-"));
  execFileSync("pnpm", ["add", "--ignore-scripts", "--lockfile=false", join(packages, archive)], {
    cwd: installation,
    encoding: "utf8",
  });
  return join(installation, "node_modules", ".bin", "tc-sdlc");
}

function run(cli: string, command: string, args: readonly string[]) {
  const result = spawnSync(cli, [command, ...args], { encoding: "utf8" });
  if (result.error !== undefined) throw result.error;
  return result;
}

function receipt(path: string): Record<string, any> {
  return JSON.parse(readFileSync(path, "utf8"));
}

describe("packed preparation and evaluation components", () => {
  let cli: string;

  beforeAll(() => {
    cli = installPackedCli();
  }, 30_000);

  test("owns successful receipts and rejects malformed preparation evidence", () => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-evaluation-"));
    const checkout = join(root, "checkout");
    cpSync(fixtureRoot, checkout, { recursive: true });
    for (const args of [
      ["init", "-q"],
      ["config", "user.name", "tc-sdlc component test"],
      ["config", "user.email", "component-test@three-cubes.invalid"],
      ["add", "."],
      ["commit", "-qm", "fixture"],
    ]) {
      execFileSync("git", args, { cwd: checkout, encoding: "utf8" });
    }

    const declaration = join(checkout, "sdlc.yaml");
    const catalogue = join(root, "catalogue.json");
    const lock = join(checkout, "tc-sdlc.lock");
    const state = join(root, "state");
    const bootstrap = join(root, "bootstrap.json");
    const preparation = join(root, "preparation.json");
    const complete = join(root, "complete.json");
    const affected = join(root, "affected.json");
    const common = ["--declaration", declaration, "--catalogue", catalogue, "--lock", lock];

    expect(run(cli, "catalogue", ["--input", candidateCatalogue, "--output", catalogue]).status).toBe(0);
    expect(run(cli, "lock", ["--declaration", declaration, "--catalogue", catalogue, "--output", lock]).status).toBe(0);
    expect(run(cli, "bootstrap", [
      ...common,
      "--root", checkout,
      "--state-root", state,
      "--receipt", bootstrap,
    ]).status).toBe(0);

    const input = join(checkout, "src", "input.txt");
    writeFileSync(input, `${readFileSync(input, "utf8")}\n`);
    const bound = [
      ...common,
      "--root", checkout,
      "--state-root", state,
      "--bootstrap-receipt", bootstrap,
    ];
    const prepare = run(cli, "prepare", [...bound, "--receipt", preparation]);
    expect(prepare.status, prepare.stderr).toBe(0);
    expect(receipt(preparation)).toMatchObject({
      schema: "tc.sdlc/preparation-receipt/v1",
      status: "succeeded",
      secondPass: { mutationCount: 0 },
    });

    const evaluation = [
      ...bound,
      "--preparation-receipt", preparation,
      "--environment", "native-test",
      "--producer", "evaluation-component-test",
    ];
    const checkAll = run(cli, "check-all", [...evaluation, "--receipt", complete]);
    expect(checkAll.status, checkAll.stderr).toBe(0);
    expect(receipt(complete)).toMatchObject({
      schema: "tc.sdlc/evaluation-receipt/v1",
      status: "succeeded",
      mutationCount: 0,
    });
    expect(receipt(complete).tasks.map((task: { key: string }) => task.key).sort()).toEqual([
      "python-service:check",
      "tc-sdlc-python-consumer:fitness",
    ]);

    const check = run(cli, "check", [
      ...evaluation,
      "--changed", "src/input.txt",
      "--receipt", affected,
    ]);
    expect(check.status, check.stderr).toBe(0);
    expect(receipt(affected)).toMatchObject({
      schema: "tc.sdlc/evaluation-receipt/v1",
      status: "succeeded",
      mutationCount: 0,
    });
    expect(receipt(affected).tasks.map((task: { key: string }) => task.key)).toEqual([
      "python-service:check",
    ]);

    const malformedValue = receipt(preparation);
    malformedValue.firstPass.scheduler.selection = ["not-a-digest"];
    malformedValue.firstPass.unexpected = true;
    const malformed = join(root, "malformed-preparation.json");
    const rejected = join(root, "rejected.json");
    writeFileSync(malformed, JSON.stringify(malformedValue));
    const rejection = run(cli, "check", [
      ...bound,
      "--preparation-receipt", malformed,
      "--changed", "src/input.txt",
      "--environment", "native-test",
      "--producer", "evaluation-component-test",
      "--receipt", rejected,
    ]);
    expect(rejection.status).toBe(1);
    expect(JSON.parse(rejection.stderr)).toMatchObject({
      schema: "tc.sdlc/command-error/v1",
      command: "check",
      status: "error",
      error: { code: "TASK_FAILED" },
    });
    expect(receipt(rejected)).toMatchObject({
      schema: "tc.sdlc/evaluation-receipt/v1",
      status: "failed",
      reason: "preparation_evidence_invalid",
      tasks: [],
    });
  }, 180_000);
});
