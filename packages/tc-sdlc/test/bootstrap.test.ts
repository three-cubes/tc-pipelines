import * as sdlc from "../dist/index.js";
import { spawnSync } from "node:child_process";
import {
  chmodSync,
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  renameSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, test } from "vitest";

const CLI = fileURLToPath(new URL("../dist/cli.js", import.meta.url));

const release = {
  version: "3.0.0",
  package: { name: "@three-cubes/tc-sdlc", version: "3.0.0" },
  workflowCommit: "1234567890abcdef1234567890abcdef12345678",
  imageDigest:
    "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  declarationSchema: "tc.sdlc/v1",
  lockSchema: "tc.sdlc/lock/v1",
  fitness: { package: "three-cubes-fitness", version: "0.17.0" },
  toolchains: {
    node: "24",
    packageManager: "pnpm@11.22.0",
    python: "3.13",
    uv: "0.12.5",
  },
} as const;

function fixture(root: string) {
  writeFileSync(join(root, "input.txt"), "input");
  const declaration = {
    schema: "tc.sdlc/v1",
    project: "bootstrap-fixture",
    toolchains: release.toolchains,
    fitness: release.fitness,
    projects: [{ name: "fixture", root: "." }],
    targets: {
      check: {
        command: "node --version",
        mode: "evaluate",
        trustBoundary: "portable",
        inputs: ["input.txt"],
      },
    },
  } as const;
  const catalogue = sdlc.createReleaseCatalogue(release);
  const lock = sdlc.resolveLock(declaration as never, catalogue);
  return { root, declaration, catalogue, lock };
}

function capabilityPath(
  versions: Readonly<Partial<Record<"node" | "pnpm" | "python3" | "uv", string>>> = {},
): string {
  const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-capabilities-"));
  const values = {
    node: versions.node ?? "v24.21.0",
    pnpm: versions.pnpm ?? "11.22.0",
    python3: versions.python3 ?? "Python 3.13.15",
    uv: versions.uv ?? "uv 0.12.5 (fixture)",
  };
  for (const [name, version] of Object.entries(values)) {
    const executable = join(directory, name);
    writeFileSync(
      executable,
      `#!/bin/sh\n[ -n "\${PATH-}" ] || exit 71\nprintf '%s\\n' '${version}'\n`,
    );
    chmodSync(executable, 0o755);
  }
  return directory;
}

function host(path: string, offline = false) {
  return {
    platform: "darwin",
    architecture: "arm64",
    path,
    offline,
  } as const;
}

function bootstrapOptions(
  root: string,
  stateRoot: string,
  path: string,
  suffix: string,
) {
  return {
    ...fixture(root),
    stateRoot,
    receiptPath: join(dirname(root), `${root.split("/").at(-1)}-${suffix}.json`),
    host: host(path),
  };
}

describe("tc-sdlc bootstrap", () => {
  test("materialises catalogue-bound adapters and stable planner identities outside the checkout", async () => {
    const roots = [
      mkdtempSync(join(tmpdir(), "tc-sdlc-bootstrap-a-")),
      mkdtempSync(join(tmpdir(), "tc-sdlc-bootstrap-b-")),
    ];
    const states = roots.map(() => mkdtempSync(join(tmpdir(), "tc-sdlc-state-")));
    const path = capabilityPath();
    const options = roots.map((root, index) => ({
      ...bootstrapOptions(root, states[index]!, path, `cold-${index}`),
      host:
        index === 0
          ? host(path)
          : { platform: "linux", architecture: "x64", path, offline: false } as const,
    }));

    const receipts = await Promise.all(
      options.map((value) => (sdlc as Record<string, any>).bootstrap(value)),
    );

    for (const [index, receipt] of receipts.entries()) {
      expect(receipt).toMatchObject({
        schema: "tc.sdlc/bootstrap-receipt/v1",
        status: "succeeded",
        reason: null,
        release: "3.0.0",
        platform: options[index]!.host.platform,
        architecture: options[index]!.host.architecture,
        reused: false,
        diagnostics: [],
        diagnosticsCount: 0,
        diagnosticsTruncated: false,
      });
      expect(receipt.lockDigest).toMatch(/^sha256:[a-f0-9]{64}$/);
      expect(receipt.taskIdentities).toEqual([
        expect.stringMatching(/^sha256:[a-f0-9]{64}$/),
      ]);
      expect(receipt.adapters.map((value: Record<string, unknown>) => value.name)).toEqual([
        "node",
        "pnpm",
        "python",
        "uv",
      ]);
      expect(receipt.adapters).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ name: "node", version: "24" }),
          expect.objectContaining({ name: "pnpm", version: "11.22.0" }),
          expect.objectContaining({ name: "python", version: "3.13" }),
          expect.objectContaining({ name: "uv", version: "0.12.5" }),
        ]),
      );
      expect(readFileSync(options[index]!.receiptPath, "utf8")).toBe(
        (sdlc as Record<string, any>).serialiseBootstrapReceipt(receipt),
      );
      expect(receipt.stateKey).not.toContain(roots[index]);
      expect(existsSync(join(states[index]!, receipt.stateKey))).toBe(true);
      for (const adapter of receipt.adapters) {
        const invocation = spawnSync(join(states[index]!, adapter.launcher), ["--version"], {
          encoding: "utf8",
          env: { PATH: "" },
        });
        expect(invocation.status, invocation.stderr).toBe(0);
      }
    }
    expect(receipts[0].taskIdentities).toEqual(receipts[1].taskIdentities);

    writeFileSync(join(roots[1]!, "input.txt"), "changed");
    const changed = await (sdlc as Record<string, any>).bootstrap({
      ...options[1],
      receiptPath: join(dirname(roots[1]!), "changed.json"),
    });
    expect(changed.taskIdentities).not.toEqual(receipts[1].taskIdentities);
    expect(changed.reused).toBe(true);
  });

  test("uses a verified warm state offline and fails cold offline with bounded guidance", async () => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-bootstrap-offline-"));
    const stateRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-state-offline-"));
    const path = capabilityPath();
    const first = await (sdlc as Record<string, any>).bootstrap(
      bootstrapOptions(root, stateRoot, path, "online"),
    );
    expect(first.status).toBe("succeeded");
    rmSync(path, { recursive: true });

    const emptyPath = mkdtempSync(join(tmpdir(), "tc-sdlc-empty-path-"));
    const warm = await (sdlc as Record<string, any>).bootstrap({
      ...bootstrapOptions(root, stateRoot, emptyPath, "warm-offline"),
      host: host(emptyPath, true),
    });
    expect(warm).toMatchObject({ status: "succeeded", reused: true });
    for (const adapter of warm.adapters) {
      const invocation = spawnSync(join(stateRoot, adapter.launcher), ["--version"], {
        encoding: "utf8",
        env: { PATH: "" },
      });
      expect(invocation.status, invocation.stderr).toBe(0);
    }

    const coldState = join(tmpdir(), `tc-sdlc-cold-${process.pid}-${Date.now()}`);
    const cold = await (sdlc as Record<string, any>).bootstrap({
      ...bootstrapOptions(root, coldState, emptyPath, "cold-offline"),
      host: host(emptyPath, true),
      maxDiagnostics: 1,
    });
    expect(cold).toMatchObject({
      status: "failed",
      reason: "offline_cold",
      diagnosticsCount: 1,
      diagnosticsTruncated: false,
    });
    expect(cold.diagnostics).toHaveLength(1);
    expect(cold.diagnostics[0].action).toContain("retry without offline mode");
    expect(existsSync(coldState)).toBe(false);

    const missing = await (sdlc as Record<string, any>).bootstrap({
      ...bootstrapOptions(
        root,
        join(tmpdir(), `tc-sdlc-missing-${process.pid}-${Date.now()}`),
        emptyPath,
        "missing",
      ),
      maxDiagnostics: 1,
    });
    expect(missing).toMatchObject({
      status: "failed",
      reason: "capability_missing",
      diagnosticsCount: 4,
      diagnosticsTruncated: true,
    });
    expect(missing.diagnostics).toHaveLength(1);
    expect(missing.diagnostics[0].action).toContain("install node 24");
  });

  test("rejects version mismatch, foreign state, symlink state and in-checkout state", async () => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-bootstrap-reject-"));
    const wrong = await (sdlc as Record<string, any>).bootstrap(
      bootstrapOptions(
        root,
        mkdtempSync(join(tmpdir(), "tc-sdlc-wrong-version-")),
        capabilityPath({ uv: "uv 0.12.4 (fixture)" }),
        "wrong-version",
      ),
    );
    expect(wrong).toMatchObject({
      status: "failed",
      reason: "capability_version_mismatch",
    });
    expect(wrong.diagnostics).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ capability: "uv", expected: "0.12.5" }),
      ]),
    );

    const foreignRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-foreign-state-"));
    writeFileSync(join(foreignRoot, "foreign.txt"), "foreign");
    const foreign = await (sdlc as Record<string, any>).bootstrap(
      bootstrapOptions(root, foreignRoot, capabilityPath(), "foreign"),
    );
    expect(foreign).toMatchObject({ status: "failed", reason: "foreign_state" });
    expect(readFileSync(join(foreignRoot, "foreign.txt"), "utf8")).toBe("foreign");

    const stateTarget = mkdtempSync(join(tmpdir(), "tc-sdlc-state-target-"));
    const stateLink = join(dirname(stateTarget), `${stateTarget.split("/").at(-1)}-link`);
    symlinkSync(stateTarget, stateLink);
    const symlinked = await (sdlc as Record<string, any>).bootstrap(
      bootstrapOptions(root, stateLink, capabilityPath(), "symlink"),
    );
    expect(symlinked).toMatchObject({
      status: "failed",
      reason: "state_root_invalid",
    });

    const inside = join(root, ".managed-state");
    const inCheckout = await (sdlc as Record<string, any>).bootstrap(
      bootstrapOptions(root, inside, capabilityPath(), "inside"),
    );
    expect(inCheckout).toMatchObject({
      status: "failed",
      reason: "state_root_invalid",
    });
    expect(existsSync(inside)).toBe(false);

    const redirectedRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-redirect-state-"));
    const redirectOptions = bootstrapOptions(root, redirectedRoot, capabilityPath(), "redirect");
    const redirectFirst = await (sdlc as Record<string, any>).bootstrap(redirectOptions);
    expect(redirectFirst.status).toBe("succeeded");
    const releases = join(redirectedRoot, "releases");
    const redirectedTarget = `${redirectedRoot}-outside`;
    rmSync(redirectedTarget, { force: true, recursive: true });
    renameSync(releases, redirectedTarget);
    symlinkSync(redirectedTarget, releases);
    const redirected = await (sdlc as Record<string, any>).bootstrap({
      ...redirectOptions,
      receiptPath: `${redirectOptions.receiptPath}.redirected`,
    });
    expect(redirected).toMatchObject({ status: "failed", reason: "state_corrupt" });
  });

  test("rejects corrupted warm state and a stale lock without repair", async () => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-bootstrap-corrupt-"));
    const stateRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-corrupt-state-"));
    const path = capabilityPath();
    const options = bootstrapOptions(root, stateRoot, path, "first");
    const first = await (sdlc as Record<string, any>).bootstrap(options);
    expect(first.status).toBe("succeeded");
    const launcher = join(stateRoot, first.adapters[0].launcher);
    writeFileSync(launcher, "corrupt");

    const corrupt = await (sdlc as Record<string, any>).bootstrap({
      ...options,
      receiptPath: `${options.receiptPath}.corrupt`,
    });
    expect(corrupt).toMatchObject({
      status: "failed",
      reason: "state_corrupt",
    });
    expect(readFileSync(launcher, "utf8")).toBe("corrupt");

    const stale = structuredClone(options.lock) as Record<string, unknown>;
    stale.release = "9.9.9";
    const staleReceipt = await (sdlc as Record<string, any>).bootstrap({
      ...options,
      lock: stale,
      stateRoot: mkdtempSync(join(tmpdir(), "tc-sdlc-stale-state-")),
      receiptPath: `${options.receiptPath}.stale`,
    });
    expect(staleReceipt).toMatchObject({ status: "failed", reason: "stale_lock" });

    const partialState = mkdtempSync(join(tmpdir(), "tc-sdlc-partial-state-"));
    const partialOptions = bootstrapOptions(root, partialState, path, "partial-first");
    const partialFirst = await (sdlc as Record<string, any>).bootstrap(partialOptions);
    expect(partialFirst.status).toBe("succeeded");
    const releaseState = join(partialState, partialFirst.stateKey);
    rmSync(join(releaseState, "state.json"));
    const sentinel = join(releaseState, "partial-sentinel");
    writeFileSync(sentinel, "do-not-repair");
    const partial = await (sdlc as Record<string, any>).bootstrap({
      ...partialOptions,
      receiptPath: `${partialOptions.receiptPath}.partial`,
    });
    expect(partial).toMatchObject({ status: "failed", reason: "state_corrupt" });
    expect(readFileSync(sentinel, "utf8")).toBe("do-not-repair");
  });

  test("exposes bootstrap through the built CLI without reading HOME", () => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-bootstrap-cli-"));
    const input = fixture(root);
    const stateRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-cli-state-"));
    const evidenceRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-cli-evidence-"));
    const declarationPath = join(root, "sdlc.json");
    const cataloguePath = join(root, "catalogue.json");
    const lockPath = join(root, "tc-sdlc.lock");
    const receiptPath = join(evidenceRoot, "bootstrap.json");
    writeFileSync(declarationPath, `${JSON.stringify(input.declaration)}\n`);
    writeFileSync(cataloguePath, `${JSON.stringify(input.catalogue)}\n`);
    (sdlc as Record<string, any>).writeLock(lockPath, input.lock);
    const homeTrap = join(evidenceRoot, "home-is-a-file");
    writeFileSync(homeTrap, "unchanged");

    const result = spawnSync(
      process.execPath,
      [
        CLI,
        "bootstrap",
        "--declaration", declarationPath,
        "--catalogue", cataloguePath,
        "--lock", lockPath,
        "--root", root,
        "--state-root", stateRoot,
        "--receipt", receiptPath,
      ],
      {
        encoding: "utf8",
        env: { ...process.env, HOME: homeTrap, PATH: capabilityPath() },
      },
    );

    expect(result.status, result.stderr).toBe(0);
    expect(result.stderr).toBe("");
    expect(JSON.parse(result.stdout)).toMatchObject({
      schema: "tc.sdlc/command-result/v1",
      command: "bootstrap",
      status: "ok",
      release: "3.0.0",
    });
    expect(JSON.parse(readFileSync(receiptPath, "utf8"))).toMatchObject({
      schema: "tc.sdlc/bootstrap-receipt/v1",
      status: "succeeded",
    });
    expect(readFileSync(homeTrap, "utf8")).toBe("unchanged");
  });
});
