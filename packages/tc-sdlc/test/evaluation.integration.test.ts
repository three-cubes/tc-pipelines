import { execFileSync, spawnSync } from "node:child_process";
import { cpSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { beforeAll, describe, expect, test } from "vitest";

const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const fixtureRoot = fileURLToPath(new URL("../../../assurance/fixtures/sdlc/python", import.meta.url));
const candidateCatalogue = fileURLToPath(new URL("../../../release/catalogue.json", import.meta.url));
const PACKAGE_COMMAND_TIMEOUT_MS = 120_000;
const PUBLIC_COMMAND_TIMEOUT_MS = 120_000;
const GIT_COMMAND_TIMEOUT_MS = 30_000;

function sanitisedEnvironment(): NodeJS.ProcessEnv {
  return {
    ...Object.fromEntries(
      Object.entries(process.env).filter(([name]) => !name.toUpperCase().startsWith("GIT_")),
    ),
    GIT_CONFIG_NOSYSTEM: "1",
    GIT_CONFIG_GLOBAL: "/dev/null",
    GIT_CONFIG_COUNT: "2",
    GIT_CONFIG_KEY_0: "commit.gpgsign",
    GIT_CONFIG_VALUE_0: "false",
    GIT_CONFIG_KEY_1: "core.hooksPath",
    GIT_CONFIG_VALUE_1: "/dev/null",
    GIT_TERMINAL_PROMPT: "0",
  };
}

function installPackedCli(): string {
  const packages = mkdtempSync(join(tmpdir(), "tc-sdlc-evaluation-package-"));
  execFileSync("pnpm", ["pack", "--pack-destination", packages], {
    cwd: packageRoot,
    encoding: "utf8",
    env: sanitisedEnvironment(),
    timeout: PACKAGE_COMMAND_TIMEOUT_MS,
  });
  const archive = readdirSync(packages).find((name) => name.endsWith(".tgz"));
  if (archive === undefined) throw new Error("pnpm pack did not produce an archive");
  const installation = mkdtempSync(join(tmpdir(), "tc-sdlc-evaluation-installation-"));
  execFileSync("pnpm", ["add", "--ignore-scripts", "--lockfile=false", join(packages, archive)], {
    cwd: installation,
    encoding: "utf8",
    env: sanitisedEnvironment(),
    timeout: PACKAGE_COMMAND_TIMEOUT_MS,
  });
  return join(installation, "node_modules", ".bin", "tc-sdlc");
}

function run(cli: string, command: string, args: readonly string[]) {
  const result = spawnSync(cli, [command, ...args], {
    encoding: "utf8",
    env: sanitisedEnvironment(),
    timeout: PUBLIC_COMMAND_TIMEOUT_MS,
    killSignal: "SIGKILL",
  });
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
      execFileSync("git", [
        "-c", "commit.gpgsign=false",
        "-c", "core.hooksPath=/dev/null",
        ...args,
      ], {
        cwd: checkout,
        encoding: "utf8",
        env: sanitisedEnvironment(),
        timeout: GIT_COMMAND_TIMEOUT_MS,
      });
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

    const sabotages = [
      ["missing-schedulers", (value: Record<string, any>) => {
        delete value.firstPass.scheduler;
        delete value.secondPass.scheduler;
      }],
      ["failed-scheduler", (value: Record<string, any>) => {
        value.firstPass.scheduler.status = "failed";
      }],
      ["inconsistent-mutations", (value: Record<string, any>) => {
        value.firstPass.mutationCount += 1;
        value.firstPass.mutationsTruncated = false;
      }],
    ] as const;
    for (const [sabotage, corrupt] of sabotages) {
      const malformedValue = receipt(preparation);
      corrupt(malformedValue);
      const malformed = join(root, `${sabotage}-preparation.json`);
      writeFileSync(malformed, JSON.stringify(malformedValue));
      for (const command of ["check", "check-all"] as const) {
        const rejected = join(root, `${command}-${sabotage}-rejected.json`);
        const rejection = run(cli, command, [
          ...bound,
          "--preparation-receipt", malformed,
          ...(command === "check" ? ["--changed", "src/input.txt"] : []),
          "--environment", "native-test",
          "--producer", "evaluation-component-test",
          "--receipt", rejected,
        ]);
        expect(rejection.status).toBe(1);
        expect(JSON.parse(rejection.stderr)).toMatchObject({
          schema: "tc.sdlc/command-error/v1",
          command,
          status: "error",
          error: { code: "TASK_FAILED" },
        });
        expect(receipt(rejected)).toMatchObject({
          schema: "tc.sdlc/evaluation-receipt/v1",
          status: "failed",
          reason: "preparation_evidence_invalid",
          tasks: [],
        });
      }
    }
  }, 180_000);
});
