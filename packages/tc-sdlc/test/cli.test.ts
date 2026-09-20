import { execFileSync, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, test } from "vitest";

import * as sdlc from "../dist/index.js";

const CLI = fileURLToPath(new URL("../dist/cli.js", import.meta.url));

const declaration = `schema: tc.sdlc/v1
project: example-product
toolchains:
  python: "3.13"
  node: "24"
  packageManager: pnpm@11.22.0
  uv: "0.12.5"
fitness:
  package: three-cubes-fitness
  version: "0.17.0"
projects:
  - name: api
    root: services/api
targets:
  prepare:
    command: make prepare
    mode: prepare
    trustBoundary: portable
  check:
    command: make check
    mode: evaluate
    trustBoundary: portable
    dependsOn: [prepare]
`;

const catalogue = {
  schema: "tc.sdlc/release-catalogue/v1",
  release: {
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
      version: "0.17.0",
    },
    toolchains: {
      node: "24",
      packageManager: "pnpm@11.22.0",
      python: "3.13",
      uv: "0.12.5",
    },
    bootstrap: sdlc.CANONICAL_SDLC_BOOTSTRAP,
  },
} as const;

type Fixture = Readonly<{
  directory: string;
  declarationPath: string;
  cataloguePath: string;
  lockPath: string;
}>;

function fixture(
  declarationText = declaration,
  catalogueValue: unknown = catalogue,
): Fixture {
  const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-test-"));
  const declarationPath = join(directory, "sdlc.yaml");
  const cataloguePath = join(directory, "catalogue.json");
  const lockPath = join(directory, "tc-sdlc.lock");
  writeFileSync(declarationPath, declarationText);
  writeFileSync(cataloguePath, `${JSON.stringify(catalogueValue, null, 2)}\n`);
  return { directory, declarationPath, cataloguePath, lockPath };
}

function run(command: "lock" | "validate", input: Fixture) {
  const args =
    command === "lock"
      ? [
          "lock",
          "--declaration",
          input.declarationPath,
          "--catalogue",
          input.cataloguePath,
          "--output",
          input.lockPath,
        ]
      : [
          "validate",
          "--declaration",
          input.declarationPath,
          "--catalogue",
          input.cataloguePath,
          "--lock",
          input.lockPath,
        ];
  return spawnSync(CLI, args, { encoding: "utf8" });
}

function createLock(input: Fixture): string {
  const stdout = execFileSync(
    CLI,
    [
      "lock",
      "--declaration",
      input.declarationPath,
      "--catalogue",
      input.cataloguePath,
      "--output",
      input.lockPath,
    ],
    { encoding: "utf8" },
  );
  const result = JSON.parse(stdout) as Record<string, unknown>;
  expect(result).toMatchObject({
    schema: "tc.sdlc/command-result/v1",
    command: "lock",
    status: "ok",
  });
  return readFileSync(input.lockPath, "utf8");
}

function expectError(result: ReturnType<typeof run>, command = "validate") {
  expect(result.status).not.toBe(0);
  expect(result.stdout).toBe("");
  expect(result.stderr.trim().split("\n")).toHaveLength(1);
  const envelope = JSON.parse(result.stderr) as {
    error: { code: string };
  };
  expect(envelope).toMatchObject({
    schema: "tc.sdlc/command-error/v1",
    command,
    status: "error",
  });
  return envelope;
}

describe("tc-sdlc lock", () => {
  test("writes canonical newline-terminated bytes for semantically identical inputs", () => {
    const first = fixture();
    const firstBytes = createLock(first);

    const reorderedDeclaration = `targets:
  check: {dependsOn: [prepare], command: make check, mode: evaluate, trustBoundary: portable}
  prepare: {command: make prepare, mode: prepare, trustBoundary: portable}
projects: [{root: services\\api, name: api}]
fitness: {version: "0.17.0", package: three-cubes-fitness}
toolchains: {uv: "0.12.5", packageManager: pnpm@11.22.0, node: "24", python: "3.13"}
project: example-product
schema: tc.sdlc/v1
`;
    const reorderedCatalogue = {
      release: {
        bootstrap: catalogue.release.bootstrap,
        toolchains: catalogue.release.toolchains,
        fitness: catalogue.release.fitness,
        lockSchema: catalogue.release.lockSchema,
        declarationSchema: catalogue.release.declarationSchema,
        imageDigest: catalogue.release.imageDigest,
        workflowCommit: catalogue.release.workflowCommit,
        package: catalogue.release.package,
        version: catalogue.release.version,
      },
      schema: catalogue.schema,
    };
    const second = fixture(reorderedDeclaration, reorderedCatalogue);
    const secondBytes = createLock(second);

    expect(firstBytes.endsWith("\n")).toBe(true);
    expect(firstBytes).toBe(secondBytes);
    expect(firstBytes).toBe(`${JSON.stringify(JSON.parse(firstBytes), null, 2)}\n`);
    expect(Object.keys(JSON.parse(firstBytes))).toEqual([
      "catalogueDigest",
      "declarationDigest",
      "declarationSchema",
      "fitness",
      "imageDigest",
      "package",
      "release",
      "schema",
      "toolchains",
      "workflowCommit",
    ]);
  });
});

describe("tc-sdlc validate", () => {
  test("validates a declaration, complete catalogue and generated lock", () => {
    const input = fixture();
    createLock(input);

    const result = run("validate", input);

    expect(result.status).toBe(0);
    expect(result.stderr).toBe("");
    expect(JSON.parse(result.stdout)).toMatchObject({
      schema: "tc.sdlc/command-result/v1",
      command: "validate",
      status: "ok",
      release: "2.2.0",
    });
    expect(JSON.parse(result.stdout)).toEqual(
      expect.objectContaining({
        declarationDigest: expect.stringMatching(/^sha256:[a-f0-9]{64}$/),
        catalogueDigest: expect.stringMatching(/^sha256:[a-f0-9]{64}$/),
        lockDigest: expect.stringMatching(/^sha256:[a-f0-9]{64}$/),
      }),
    );
  });

  test("rejects an unknown declaration field", () => {
    const input = fixture(`${declaration}unknownField: rejected\n`);
    const result = run("validate", input);
    expectError(result);
  });

  test.each([
    ["fitness", 'version: "0.17.0"', 'version: "0.17.0"\n  typo: rejected'],
    ["toolchains", 'uv: "0.12.5"', 'uv: "0.12.5"\n  typo: rejected'],
  ])("rejects an unknown nested %s field before generating a lock", (_name, field, sabotage) => {
    const input = fixture(declaration.replace(field, sabotage));

    const result = run("lock", input);

    const envelope = expectError(result, "lock");
    expect(envelope.error.code).toBe("SCHEMA_INVALID");
    expect(existsSync(input.lockPath)).toBe(false);
  });

  test("rejects an incomplete release catalogue", () => {
    const incomplete = structuredClone(catalogue) as Record<string, any>;
    delete incomplete.release.imageDigest;
    const input = fixture(declaration, incomplete);
    const result = run("validate", input);
    expectError(result);
  });

  test.each([
    ["stale declaration", (input: Fixture) => {
      writeFileSync(input.declarationPath, declaration.replace("example-product", "renamed-product"));
    }],
    ["changed catalogue entry", (input: Fixture) => {
      const changed = structuredClone(catalogue) as Record<string, any>;
      changed.release.workflowCommit = "abcdef1234567890abcdef1234567890abcdef12";
      writeFileSync(input.cataloguePath, `${JSON.stringify(changed)}\n`);
    }],
    ["hand-edited lock", (input: Fixture) => {
      const lock = JSON.parse(readFileSync(input.lockPath, "utf8")) as Record<string, unknown>;
      lock.release = "9.9.9";
      writeFileSync(input.lockPath, `${JSON.stringify(lock, null, 2)}\n`);
    }],
    ["partial coordinated upgrade", (input: Fixture) => {
      writeFileSync(input.declarationPath, declaration.replace('node: "24"', 'node: "22"'));
    }],
  ])("rejects a %s", (_name, sabotage) => {
    const input = fixture();
    createLock(input);
    sabotage(input);

    const result = run("validate", input);

    expectError(result);
  });
});
