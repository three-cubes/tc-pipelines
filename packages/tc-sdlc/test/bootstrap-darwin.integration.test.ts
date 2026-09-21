import * as sdlc from "../dist/index.js";
import { execFileSync, spawnSync } from "node:child_process";
import {
  chmodSync,
  cpSync,
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  renameSync,
  rmSync,
  statSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, test } from "vitest";

const consumer = fileURLToPath(
  new URL("./fixtures/bootstrap-consumer", import.meta.url),
);
const workspaceConsumer = fileURLToPath(
  new URL("./fixtures/bootstrap-workspace", import.meta.url),
);
const CLI = fileURLToPath(new URL("../dist/cli.js", import.meta.url));
const imageDigest =
  "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

function homebrewPrerequisitesAvailable(architecture: "arm64" | "x64"): boolean {
  const prefix = architecture === "arm64" ? "/opt/homebrew" : "/usr/local";
  return [
    "bin/brew",
    "opt/node@24/bin/node",
    "opt/node@24/bin/pnpm",
    "opt/python@3.13/libexec/bin/python3",
    "bin/uv",
  ].every((path) => existsSync(join(prefix, path)));
}

const unavailableDarwinArchitecture = (["arm64", "x64"] as const).find(
  (architecture) => !homebrewPrerequisitesAvailable(architecture),
);

function input(
  root: string,
  inputs = ["package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock"],
) {
  const declaration = sdlc.validateDeclaration({
    schema: "tc.sdlc/v1",
    project: "bootstrap-real-consumer",
    toolchains: sdlc.CANONICAL_SDLC_TOOLCHAINS,
    fitness: sdlc.CANONICAL_SDLC_FITNESS,
    projects: [{ name: "consumer", root: "." }],
    targets: {
      check: {
        command: "node --version",
        mode: "evaluate",
        trustBoundary: "portable",
        inputs,
      },
    },
  });
  const catalogue = sdlc.generateReleaseCatalogue({
    releaseVersion: "3.0.0",
    workflowCommit: "1234567890abcdef1234567890abcdef12345678",
    imageDigest,
  });
  return {
    root,
    declaration,
    catalogue,
    lock: sdlc.resolveLock(declaration, catalogue),
  };
}

describe("reviewed macOS bootstrap host and dependency boundary", () => {
  test("does not trust an arbitrary PATH and emits one executable Linux remediation command", async () => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-untrusted-path-"));
    for (const name of ["package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock"]) {
      writeFileSync(join(root, name), readFileSync(join(consumer, name)));
    }
    const stateRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-untrusted-state-"));
    const options = input(root);
    const receipt = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: join(dirname(root), "untrusted-path-receipt.json"),
      host: {
        platform: "linux",
        architecture: "arm64",
        path: "/an/arbitrary/path/must/not/be-used",
        offline: false,
      } as never,
    });

    expect(receipt).toMatchObject({
      status: "failed",
      reason: "host_prerequisite_missing",
      diagnosticsCount: 1,
      diagnosticsTruncated: false,
    });
    expect(receipt.diagnostics).toHaveLength(1);
    expect(receipt.diagnostics[0]?.action).toBe(
      `docker pull ghcr.io/three-cubes/tc-sdlc@${imageDigest}`,
    );
    expect(execFileSync("docker", ["--version"], { encoding: "utf8" })).toContain("Docker version");
  });

  test.skipIf(unavailableDarwinArchitecture === undefined)("emits one syntactically executable macOS prerequisite remediation command", async () => {
    expect(process.platform).toBe("darwin");
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-mac-remediation-"));
    for (const name of ["package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock"]) {
      writeFileSync(join(root, name), readFileSync(join(consumer, name)));
    }
    const values = input(root);
    expect(() => sdlc.validateDeclaration({
      ...values.declaration,
      toolchains: { ...values.declaration.toolchains, node: "25" },
    })).toThrow(/must be equal to constant/);
    const receipt = await sdlc.bootstrap({
      ...values,
      stateRoot: mkdtempSync(join(tmpdir(), "tc-sdlc-mac-remediation-state-")),
      receiptPath: join(dirname(root), "mac-remediation.json"),
      host: { platform: "darwin", architecture: unavailableDarwinArchitecture!, offline: false },
    });

    expect(receipt).toMatchObject({
      status: "failed",
      reason: "host_prerequisite_missing",
      diagnosticsCount: 1,
    });
    const action = receipt.diagnostics[0]?.action;
    expect(action).toContain("brew install node@24 python@3.13 uv");
    expect(action).toContain("pnpm@11.22.0");
    expect(spawnSync("/bin/bash", ["-n", "-c", action!]).status).toBe(0);
  });

  test("uses real platform prerequisites and materialises both dependency locks outside the checkout", async () => {
    expect(process.platform).toBe("darwin");
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-real-consumer-"));
    for (const name of ["package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock"]) {
      writeFileSync(join(root, name), readFileSync(join(consumer, name)));
    }
    const stateRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-real-state-"));
    const options = input(root);
    const receiptPath = join(dirname(stateRoot), "real-bootstrap-receipt.json");
    const receipt = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath,
      host: {
        platform: "darwin",
        architecture: process.arch,
        offline: false,
      },
    });

    expect(receipt).toMatchObject({
      status: "succeeded",
      reason: null,
      platform: "darwin",
      architecture: process.arch,
      diagnostics: [],
    });
    expect(receipt.adapters.map((adapter) => [adapter.name, adapter.provider])).toEqual([
      ["node", "homebrew"],
      ["pnpm", "homebrew"],
      ["python", "homebrew"],
      ["uv", "catalogue-distribution"],
    ]);
    expect(receipt.dependencies.map((dependency) => dependency.manager)).toEqual([
      "pnpm",
      "uv",
    ]);
    expect(receipt.dependencies.every((dependency) => dependency.lockDigest.startsWith("sha256:"))).toBe(true);
    expect(receipt.dependencies.every((dependency) => dependency.manifestDigest.startsWith("sha256:"))).toBe(true);
    expect(existsSync(join(root, "node_modules"))).toBe(false);
    expect(existsSync(join(root, ".venv"))).toBe(false);
    expect(existsSync(join(stateRoot, receipt.stateKey, "dependencies", "node", "node_modules", "yaml"))).toBe(true);
    const python = join(stateRoot, receipt.stateKey, "dependencies", "python", "bin", "python");
    expect(execFileSync(python, ["-c", "import attrs; print(attrs.__version__)"], { encoding: "utf8" }).trim()).toBe("26.1.0");
    const pnpmLauncher = join(
      stateRoot,
      receipt.adapters.find((adapter) => adapter.name === "pnpm")!.launcher,
    );
    const emptyHome = join(dirname(stateRoot), "empty-home-is-a-file");
    writeFileSync(emptyHome, "unchanged");
    expect(execFileSync(pnpmLauncher, ["--version"], {
      encoding: "utf8",
      env: { HOME: emptyHome, PATH: "/usr/bin:/bin", COREPACK_ENABLE_NETWORK: "0" },
    }).trim()).toBe("11.22.0");
    expect(readFileSync(receiptPath, "utf8")).toBe(sdlc.serialiseBootstrapReceipt(receipt));

    const relocatedRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-relocated-consumer-"));
    for (const name of ["package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock"]) {
      writeFileSync(join(relocatedRoot, name), readFileSync(join(consumer, name)));
    }
    const relocatedOptions = input(relocatedRoot);
    const relocated = await sdlc.bootstrap({
      ...relocatedOptions,
      stateRoot,
      receiptPath: `${receiptPath}.relocated`,
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(relocated).toMatchObject({ status: "succeeded", reused: true });
    expect(relocated.dependencies).toEqual(receipt.dependencies);

    const warm = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: `${receiptPath}.offline`,
      host: {
        platform: "darwin",
        architecture: process.arch,
        offline: true,
      },
    });
    expect(warm).toMatchObject({ status: "succeeded", reused: true });
    const uvDependency = receipt.dependencies.find((dependency) => dependency.manager === "uv")!;
    expect(uvDependency.installedDigest).toMatch(/^sha256:[0-9a-f]{64}$/);
    const attrsDirectory = execFileSync(
      python,
      ["-c", "import attrs; print(attrs.__path__[0])"],
      { encoding: "utf8" },
    ).trim();
    const movedAttrsDirectory = `${attrsDirectory}.renamed`;
    renameSync(attrsDirectory, movedAttrsDirectory);
    expect(() => execFileSync(python, ["-c", "import attrs"], { stdio: "pipe" })).toThrow();
    const renamedPythonTree = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: `${receiptPath}.renamed-python-tree`,
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(renamedPythonTree).toMatchObject({ status: "failed", reason: "state_corrupt" });
    renameSync(movedAttrsDirectory, attrsDirectory);
    const attrModule = execFileSync(
      python,
      ["-c", "import attr._make; print(attr._make.__file__)"],
      { encoding: "utf8" },
    ).trim();
    const attrModuleBytes = readFileSync(attrModule);
    rmSync(attrModule);
    rmSync(join(dirname(attrModule), "__pycache__"), { recursive: true, force: true });
    expect(() => execFileSync(python, ["-c", "import attr._make"], { stdio: "pipe" })).toThrow();
    const deletedPythonFile = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: `${receiptPath}.deleted-python-file`,
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(deletedPythonFile).toMatchObject({ status: "failed", reason: "state_corrupt" });
    writeFileSync(attrModule, attrModuleBytes);
    const restoredPythonTree = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: `${receiptPath}.restored-python-tree`,
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(restoredPythonTree).toMatchObject({ status: "succeeded", reused: true });

    const declarationPath = join(root, "sdlc.json");
    const cataloguePath = join(root, "catalogue.json");
    const lockPath = join(root, "tc-sdlc.lock");
    writeFileSync(declarationPath, sdlc.canonicalJson(options.declaration));
    writeFileSync(cataloguePath, sdlc.canonicalJson(options.catalogue));
    sdlc.writeLock(lockPath, options.lock);
    const ambientCorepack = join(homedir(), ".cache", "node", "corepack");
    const sandboxedWarm = spawnSync(
      "/usr/bin/sandbox-exec",
      [
        "-p",
        `(version 1)(allow default)(deny file-read* file-write* (subpath ${JSON.stringify(ambientCorepack)}))`,
        process.execPath,
        CLI,
        "bootstrap",
        "--declaration", declarationPath,
        "--catalogue", cataloguePath,
        "--lock", lockPath,
        "--root", root,
        "--state-root", stateRoot,
        "--receipt", `${receiptPath}.sandboxed`,
        "--offline", "true",
      ],
      {
        encoding: "utf8",
        env: {
          ...process.env,
          HOME: emptyHome,
          PATH: "/untrusted",
          XDG_CACHE_HOME: join(homedir(), ".cache"),
          COREPACK_HOME: ambientCorepack,
        },
      },
    );
    expect(sandboxedWarm.status, sandboxedWarm.stderr).toBe(0);
    expect(JSON.parse(sandboxedWarm.stdout)).toMatchObject({ status: "ok", reused: true });

    const originalManifest = readFileSync(join(root, "package.json"), "utf8");
    const changedManifest = JSON.parse(originalManifest);
    changedManifest.description = "identity-affecting manifest change";
    writeFileSync(join(root, "package.json"), `${JSON.stringify(changedManifest, null, 2)}\n`);
    const changed = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: `${receiptPath}.changed`,
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(changed).toMatchObject({ status: "failed", reason: "offline_cold", reused: false });
    expect(changed.stateKey).not.toBe(receipt.stateKey);
    writeFileSync(join(root, "package.json"), originalManifest);

    const launcher = join(stateRoot, warm.adapters[0]!.launcher);
    writeFileSync(launcher, "corrupt");
    const corrupt = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: `${receiptPath}.corrupt`,
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(corrupt).toMatchObject({ status: "failed", reason: "state_corrupt" });
    expect(readFileSync(launcher, "utf8")).toBe("corrupt");
  }, 30_000);

  test("materialises and identity-binds the complete pnpm workspace graph", async () => {
    expect(process.platform).toBe("darwin");
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-workspace-consumer-"));
    cpSync(workspaceConsumer, root, { recursive: true });
    const undeclaredCache = join(root, "packages", "b", ".cache", "untracked");
    mkdirSync(dirname(undeclaredCache), { recursive: true });
    writeFileSync(undeclaredCache, "must not enter managed state");
    const stateRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-workspace-state-"));
    const options = input(root, [
      "package.json",
      "pnpm-lock.yaml",
      "pnpm-workspace.yaml",
      "packages/**/*.json",
    ]);
    const receipt = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: join(dirname(stateRoot), "workspace-receipt.json"),
      host: { platform: "darwin", architecture: process.arch, offline: false },
    });

    expect(receipt).toMatchObject({ status: "succeeded", dependencies: [{ manager: "pnpm" }] });
    expect(receipt.dependencies[0]?.inputs.map((input) => input.path)).toEqual([
      "package.json",
      "packages/a/index.js",
      "packages/a/package.json",
      "packages/b/index.js",
      "packages/b/package.json",
      "patches/is-number@7.0.0.patch",
      "pnpm-lock.yaml",
      "pnpm-workspace.yaml",
    ]);
    const environment = join(stateRoot, receipt.stateKey, receipt.dependencies[0]!.environment);
    expect(existsSync(join(environment, "packages", "b", ".cache"))).toBe(false);
    expect(existsSync(join(environment, "packages", "a", "node_modules", "yaml"))).toBe(true);
    expect(existsSync(join(environment, "packages", "a", "node_modules", "workspace-b"))).toBe(true);
    const nodeLauncher = join(
      stateRoot,
      receipt.adapters.find((adapter) => adapter.name === "node")!.launcher,
    );
    expect(execFileSync(nodeLauncher, [
      "-e",
      `if (!require(${JSON.stringify(join(environment, "node_modules", "is-number"))}).tcSdlcPatched) process.exit(1)`,
    ], { encoding: "utf8" })).toBe("");
    for (const source of [
      join(root, "packages", "b"),
      join(environment, "node_modules", "workspace-a"),
    ]) {
      expect(execFileSync(nodeLauncher, [
        "-e",
        `if (require(${JSON.stringify(source)}) !== "workspace-source-contract") process.exit(1)`,
      ], { encoding: "utf8" })).toBe("");
    }

    const workspaceSource = join(root, "packages", "b", "index.js");
    const originalWorkspaceSource = readFileSync(workspaceSource, "utf8");
    writeFileSync(workspaceSource, `${originalWorkspaceSource}\nmodule.exports = "changed";\n`);
    const staleSource = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: join(dirname(stateRoot), "workspace-stale-source.json"),
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(staleSource).toMatchObject({ status: "failed", reason: "offline_cold" });
    expect(staleSource.stateKey).not.toBe(receipt.stateKey);
    writeFileSync(workspaceSource, originalWorkspaceSource);
    const restoredSource = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: join(dirname(stateRoot), "workspace-restored-source.json"),
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(restoredSource).toMatchObject({ status: "succeeded", reused: true });

    const memberManifest = join(root, "packages", "b", "package.json");
    const changed = JSON.parse(readFileSync(memberManifest, "utf8"));
    changed.description = "workspace identity sabotage";
    writeFileSync(memberManifest, `${JSON.stringify(changed, null, 2)}\n`);
    const stale = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: join(dirname(stateRoot), "workspace-stale.json"),
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(stale).toMatchObject({ status: "failed", reason: "offline_cold" });
    expect(stale.stateKey).not.toBe(receipt.stateKey);
    delete changed.description;
    writeFileSync(memberManifest, `${JSON.stringify(changed, null, 2)}\n`);

    const patch = join(root, "patches", "is-number@7.0.0.patch");
    const originalPatch = readFileSync(patch, "utf8");
    writeFileSync(patch, `${originalPatch}\n`);
    const stalePatch = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: join(dirname(stateRoot), "workspace-stale-patch.json"),
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(stalePatch).toMatchObject({ status: "failed", reason: "offline_cold" });
    expect(stalePatch.stateKey).not.toBe(receipt.stateKey);
    writeFileSync(patch, originalPatch);

    expect(receipt.dependencies[0]?.installedDigest).toMatch(/^sha256:[0-9a-f]{64}$/);
    const installedManifest = join(environment, "packages", "a", "node_modules", "yaml", "package.json");
    const originalInstalledManifest = readFileSync(installedManifest, "utf8");
    writeFileSync(installedManifest, `${originalInstalledManifest}\n`);
    const tamperedInstalledTree = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: join(dirname(stateRoot), "workspace-tampered-installed-tree.json"),
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(tamperedInstalledTree).toMatchObject({ status: "failed", reason: "state_corrupt" });
    writeFileSync(installedManifest, originalInstalledManifest);

    const installedExecutable = join(
      environment,
      "packages",
      "a",
      "node_modules",
      ".bin",
      "yaml",
    );
    const executableMode = statSync(installedExecutable).mode & 0o777;
    chmodSync(installedExecutable, 0o644);
    const nonExecutableInstalledTree = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: join(dirname(stateRoot), "workspace-non-executable-installed-tree.json"),
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(nonExecutableInstalledTree).toMatchObject({ status: "failed", reason: "state_corrupt" });
    chmodSync(installedExecutable, executableMode);

    rmSync(join(environment, "node_modules"), { recursive: true });
    const missingInstalledTree = await sdlc.bootstrap({
      ...options,
      stateRoot,
      receiptPath: join(dirname(stateRoot), "workspace-missing-installed-tree.json"),
      host: { platform: "darwin", architecture: process.arch, offline: true },
    });
    expect(missingInstalledTree).toMatchObject({ status: "failed", reason: "state_corrupt" });
  }, 30_000);

  test("rejects foreign, symlinked, in-checkout and stale state before host use", async () => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-state-sabotage-"));
    for (const name of ["package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock"]) {
      writeFileSync(join(root, name), readFileSync(join(consumer, name)));
    }
    const options = input(root);
    const host = { platform: "linux", architecture: "x64", offline: false } as const;
    const foreignRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-foreign-state-"));
    writeFileSync(join(foreignRoot, "foreign"), "preserve");
    const foreign = await sdlc.bootstrap({
      ...options,
      stateRoot: foreignRoot,
      receiptPath: join(dirname(root), "foreign-receipt.json"),
      host,
    });
    expect(foreign).toMatchObject({ status: "failed", reason: "foreign_state" });
    expect(readFileSync(join(foreignRoot, "foreign"), "utf8")).toBe("preserve");

    const target = mkdtempSync(join(tmpdir(), "tc-sdlc-state-target-"));
    const link = `${target}-link`;
    symlinkSync(target, link);
    const symlinked = await sdlc.bootstrap({
      ...options,
      stateRoot: link,
      receiptPath: join(dirname(root), "symlink-receipt.json"),
      host,
    });
    expect(symlinked).toMatchObject({ status: "failed", reason: "state_root_invalid" });

    const inside = join(root, ".state");
    const inCheckout = await sdlc.bootstrap({
      ...options,
      stateRoot: inside,
      receiptPath: join(dirname(root), "inside-receipt.json"),
      host,
    });
    expect(inCheckout).toMatchObject({ status: "failed", reason: "state_root_invalid" });
    expect(existsSync(inside)).toBe(false);

    const stale = structuredClone(options.lock) as Record<string, unknown>;
    stale.release = "9.9.9";
    const staleReceipt = await sdlc.bootstrap({
      ...options,
      lock: stale as never,
      stateRoot: mkdtempSync(join(tmpdir(), "tc-sdlc-stale-state-")),
      receiptPath: join(dirname(root), "stale-receipt.json"),
      host,
    });
    expect(staleReceipt).toMatchObject({ status: "failed", reason: "stale_lock" });
  });

  test("built CLI ignores PATH and HOME while using reviewed macOS prerequisites", () => {
    expect(process.platform).toBe("darwin");
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-bootstrap-cli-"));
    for (const name of ["package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock"]) {
      writeFileSync(join(root, name), readFileSync(join(consumer, name)));
    }
    const options = input(root);
    const stateRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-cli-state-"));
    const evidenceRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-cli-evidence-"));
    const declarationPath = join(root, "sdlc.json");
    const cataloguePath = join(root, "catalogue.json");
    const lockPath = join(root, "tc-sdlc.lock");
    const receiptPath = join(evidenceRoot, "bootstrap.json");
    writeFileSync(declarationPath, sdlc.canonicalJson(options.declaration));
    writeFileSync(cataloguePath, sdlc.canonicalJson(options.catalogue));
    sdlc.writeLock(lockPath, options.lock);
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
      { encoding: "utf8", env: { ...process.env, HOME: homeTrap, PATH: "/untrusted" } },
    );
    expect(result.status, result.stderr).toBe(0);
    expect(JSON.parse(result.stdout)).toMatchObject({
      schema: "tc.sdlc/command-result/v1",
      command: "bootstrap",
      status: "ok",
      release: "3.0.0",
    });
    expect(readFileSync(homeTrap, "utf8")).toBe("unchanged");
  }, 30_000);
});
