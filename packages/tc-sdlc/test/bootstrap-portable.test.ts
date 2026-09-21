import * as sdlc from "../dist/index.js";
import {
  cpSync,
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, test } from "vitest";

const consumer = fileURLToPath(
  new URL("./fixtures/bootstrap-consumer", import.meta.url),
);
const workspaceConsumer = fileURLToPath(
  new URL("./fixtures/bootstrap-workspace", import.meta.url),
);

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "tc-sdlc-portable-consumer-"));
  for (const name of ["package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock"]) {
    writeFileSync(join(root, name), readFileSync(join(consumer, name)));
  }
  const declaration = sdlc.validateDeclaration({
    schema: "tc.sdlc/v1",
    project: "bootstrap-portable-boundary",
    toolchains: sdlc.CANONICAL_SDLC_TOOLCHAINS,
    fitness: sdlc.CANONICAL_SDLC_FITNESS,
    projects: [{ name: "consumer", root: "." }],
    targets: {
      check: {
        command: "node --version",
        mode: "evaluate",
        trustBoundary: "portable",
        inputs: ["package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock"],
      },
    },
  });
  const catalogue = sdlc.generateReleaseCatalogue({
    releaseVersion: "3.0.0",
    workflowCommit: "1234567890abcdef1234567890abcdef12345678",
    imageDigest:
      "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  });
  return {
    root,
    declaration,
    catalogue,
    lock: sdlc.resolveLock(declaration, catalogue),
  };
}

const host = {
  platform: process.platform === "darwin" ? "darwin" : "linux",
  architecture: process.arch === "x64" ? "x64" : "arm64",
  offline: true,
} as const;

describe("portable bootstrap public boundary", () => {
  test("rejects foreign, symlinked and in-checkout state without mutating it", async () => {
    const options = fixture();
    const receiptRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-portable-evidence-"));
    const foreignRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-portable-foreign-"));
    writeFileSync(join(foreignRoot, "foreign"), "preserve");
    const foreign = await sdlc.bootstrap({
      ...options,
      stateRoot: foreignRoot,
      receiptPath: join(receiptRoot, "foreign.json"),
      host,
    });
    expect(foreign).toMatchObject({ status: "failed", reason: "foreign_state" });
    expect(readFileSync(join(foreignRoot, "foreign"), "utf8")).toBe("preserve");

    const target = mkdtempSync(join(tmpdir(), "tc-sdlc-portable-target-"));
    const link = `${target}-link`;
    symlinkSync(target, link);
    const symlinked = await sdlc.bootstrap({
      ...options,
      stateRoot: link,
      receiptPath: join(receiptRoot, "symlink.json"),
      host,
    });
    expect(symlinked).toMatchObject({ status: "failed", reason: "state_root_invalid" });

    const inside = join(options.root, ".state");
    const inCheckout = await sdlc.bootstrap({
      ...options,
      stateRoot: inside,
      receiptPath: join(receiptRoot, "inside.json"),
      host,
    });
    expect(inCheckout).toMatchObject({ status: "failed", reason: "state_root_invalid" });
    expect(existsSync(inside)).toBe(false);
  });

  test("rejects a stale lock before capability discovery", async () => {
    const options = fixture();
    const stale = structuredClone(options.lock) as Record<string, unknown>;
    stale.release = "9.9.9";
    const receipt = await sdlc.bootstrap({
      ...options,
      lock: stale as never,
      stateRoot: mkdtempSync(join(tmpdir(), "tc-sdlc-portable-stale-")),
      receiptPath: join(dirname(options.root), "portable-stale.json"),
      host,
    });
    expect(receipt).toMatchObject({ status: "failed", reason: "stale_lock" });
  });

  test("rejects a workspace package omitted from the stale pnpm lock before host discovery", async () => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-portable-workspace-"));
    cpSync(workspaceConsumer, root, { recursive: true });
    mkdirSync(join(root, "packages", "new-member"), { recursive: true });
    writeFileSync(
      join(root, "packages", "new-member", "package.json"),
      `${JSON.stringify({ name: "new-member", version: "1.0.0" }, null, 2)}\n`,
    );
    const values = fixture();
    const declaration = sdlc.validateDeclaration({
      ...values.declaration,
      projects: [{ name: "consumer", root: "." }],
      targets: {
        check: {
          command: "node --version",
          mode: "evaluate",
          trustBoundary: "portable",
          inputs: ["package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", "packages/**/*.json"],
        },
      },
    });
    const lock = sdlc.resolveLock(declaration, values.catalogue);
    const receipt = await sdlc.bootstrap({
      root,
      declaration,
      catalogue: values.catalogue,
      lock,
      stateRoot: mkdtempSync(join(tmpdir(), "tc-sdlc-portable-workspace-state-")),
      receiptPath: join(dirname(root), "portable-workspace-stale-lock.json"),
      host,
    });

    expect(receipt).toMatchObject({
      status: "failed",
      reason: "dependency_lock_invalid",
      diagnostics: [{ code: "PNPM_WORKSPACE_LOCK_MISMATCH" }],
    });
  });
});
