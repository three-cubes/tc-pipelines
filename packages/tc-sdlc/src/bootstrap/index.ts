import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  accessSync,
  chmodSync,
  constants,
  existsSync,
  globSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  readlinkSync,
  realpathSync,
  readdirSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { posix } from "node:path";
import { parse } from "yaml";

import { bytesDigest, canonicalJson, digest } from "../canonical.js";
import { SdlcError } from "../errors.js";
import { writeCanonicalEvidence } from "../evidence/index.js";
import { bindGraphLock, buildGraph } from "../graph/index.js";
import { resolveInputInventory } from "../inputs/index.js";
import { assertCurrentLock } from "../lock/index.js";
import {
  recoverInterruptedTemporaryState,
  type AutomaticRecoveryReceipt,
} from "../maintenance/index.js";
import type { ReleaseCatalogue, SdlcDeclaration, SdlcLock } from "../schema/types.js";
import {
  commitBootstrapReference,
  removePendingBootstrapReference,
  writePendingBootstrapReference,
} from "./references.js";

export type BootstrapPlatform = "darwin" | "linux";
export type BootstrapCapabilityName = "node" | "pnpm" | "python" | "uv";
export type BootstrapProvider = "homebrew" | "canonical-image" | "catalogue-distribution";

export type BootstrapHost = Readonly<{
  platform: BootstrapPlatform;
  architecture: string;
  offline: boolean;
}>;

export type BootstrapDiagnostic = Readonly<{
  code: string;
  message: string;
  action: string;
  capability?: BootstrapCapabilityName;
  expected?: string;
  observed?: string;
}>;

export type BootstrapAdapterEvidence = Readonly<{
  name: BootstrapCapabilityName;
  version: string;
  provider: BootstrapProvider;
  executableDigest: string;
  launcherDigest: string;
  adapterDigest: string;
  launcher: string;
}>;

export type BootstrapDependencyInput = Readonly<{
  path: string;
  digest: string;
}>;

export type BootstrapDependencyEvidence = Readonly<{
  manager: "pnpm" | "uv";
  lockDigest: string;
  manifestDigest: string;
  environment: string;
  inputs: readonly BootstrapDependencyInput[];
  installedDigest?: string;
}>;

export type BootstrapReceipt = Readonly<{
  schema: "tc.sdlc/bootstrap-receipt/v1";
  status: "succeeded" | "failed";
  reason: string | null;
  release: string;
  lockDigest: string;
  platform: BootstrapPlatform;
  architecture: string;
  stateKey: string;
  reused: boolean;
  taskIdentities: readonly string[];
  adapters: readonly BootstrapAdapterEvidence[];
  dependencies: readonly BootstrapDependencyEvidence[];
  recovery: AutomaticRecoveryReceipt;
  diagnostics: readonly BootstrapDiagnostic[];
  diagnosticsCount: number;
  diagnosticsTruncated: boolean;
}>;

export type BootstrapOptions = Readonly<{
  root: string;
  stateRoot: string;
  declaration: SdlcDeclaration;
  catalogue: ReleaseCatalogue;
  lock: SdlcLock;
  receiptPath: string;
  host?: Partial<BootstrapHost>;
  maxDiagnostics?: number;
}>;

type CapabilityContract = Readonly<{
  name: BootstrapCapabilityName;
  expected: (declaration: SdlcDeclaration) => string;
  observed: (output: string) => string | null;
  matches: (actual: string, expected: string) => boolean;
}>;

type HostCapability = Readonly<{
  name: BootstrapCapabilityName;
  version: string;
  provider: BootstrapProvider;
  executable: string;
  executableDigest: string;
}>;

type PnpmInstaller = Readonly<{
  node: string;
  nodeRoot: string;
  corepack: string;
}>;

type HostCapabilities = Readonly<{
  adapters: readonly HostCapability[];
  installerUv: HostCapability;
  pnpmInstaller?: PnpmInstaller;
}>;

type ResolvedAdapter = BootstrapAdapterEvidence & Readonly<{ executable: string }>;

type DependencyInput = BootstrapDependencyInput & Readonly<{ sourcePath: string }>;

type DependencyLock = BootstrapDependencyEvidence & Readonly<{
  inputs: readonly DependencyInput[];
}>;

type BootstrapState = Readonly<{
  schema: "tc.sdlc/bootstrap-state/v6";
  release: string;
  lockDigest: string;
  dependencyDigest: string;
  platform: BootstrapPlatform;
  architecture: string;
  adapters: readonly ResolvedAdapter[];
  dependencies: readonly BootstrapDependencyEvidence[];
}>;

type FilesystemIdentity = Readonly<{
  device: string;
  inode: string;
  birthtimeNanoseconds: string;
}>;

const OWNER = { schema: "tc.sdlc/state-owner/v1", owner: "@three-cubes/tc-sdlc" } as const;

const contracts: readonly CapabilityContract[] = [
  {
    name: "node",
    expected: (declaration) => declaration.toolchains.node,
    observed: (output) => output.match(/\bv?(\d+)(?:\.\d+){0,2}\b/)?.[1] ?? null,
    matches: (actual, expected) => actual === expected,
  },
  {
    name: "pnpm",
    expected: (declaration) => declaration.toolchains.packageManager.replace(/^pnpm@/, ""),
    observed: (output) => output.match(/\b(\d+\.\d+\.\d+)\b/)?.[1] ?? null,
    matches: (actual, expected) => actual === expected,
  },
  {
    name: "python",
    expected: (declaration) => declaration.toolchains.python,
    observed: (output) => output.match(/\bPython\s+(\d+\.\d+)(?:\.\d+)?\b/i)?.[1] ?? null,
    matches: (actual, expected) => actual === expected,
  },
  {
    name: "uv",
    expected: (declaration) => declaration.toolchains.uv,
    observed: (output) => output.match(/\buv\s+(\d+\.\d+\.\d+)\b/i)?.[1] ?? null,
    matches: (actual, expected) => actual === expected,
  },
];

class BootstrapFailure extends Error {
  readonly reason: string;
  readonly diagnostics: readonly BootstrapDiagnostic[];

  constructor(reason: string, diagnostics: readonly BootstrapDiagnostic[]) {
    super(diagnostics[0]?.message ?? reason);
    this.reason = reason;
    this.diagnostics = diagnostics;
  }
}

function fileDigest(path: string): string {
  return `sha256:${createHash("sha256").update(readFileSync(path)).digest("hex")}`;
}

function filesystemIdentity(path: string): FilesystemIdentity {
  const details = lstatSync(path, { bigint: true });
  return {
    device: details.dev.toString(),
    inode: details.ino.toString(),
    birthtimeNanoseconds: details.birthtimeNs.toString(),
  };
}

function sameFilesystemIdentity(path: string, expected: FilesystemIdentity): boolean {
  try {
    return canonicalJson(filesystemIdentity(path)) === canonicalJson(expected);
  } catch {
    return false;
  }
}

function isPythonRuntimeCache(path: string): boolean {
  const segments = path.split("/");
  const name = segments.at(-1) ?? "";
  return segments.includes("__pycache__") || name.endsWith(".pyc") || name.endsWith(".pyo");
}

function directoryDigest(root: string, ignorePythonRuntimeCache = false): string {
  if (!existsSync(root) || lstatSync(root).isSymbolicLink() || !lstatSync(root).isDirectory()) {
    throw new Error("dependency environment is not a real directory");
  }
  const rootMetadata = lstatSync(root);
  const entries: Record<string, unknown>[] = [
    { path: ".", type: "directory", mode: rootMetadata.mode & 0o7777 },
  ];
  const visit = (directory: string, prefix: string): void => {
    for (const name of readdirSync(directory).sort()) {
      const path = join(directory, name);
      const relativePath = prefix === "" ? name : posix.join(prefix, name);
      if (ignorePythonRuntimeCache && isPythonRuntimeCache(relativePath)) continue;
      const metadata = lstatSync(path);
      if (metadata.isSymbolicLink()) {
        entries.push({ path: relativePath, type: "symlink", target: readlinkSync(path) });
      } else if (metadata.isDirectory()) {
        entries.push({
          path: relativePath,
          type: "directory",
          mode: metadata.mode & 0o7777,
        });
        visit(path, relativePath);
      } else if (metadata.isFile()) {
        entries.push({
          path: relativePath,
          type: "file",
          mode: metadata.mode & 0o7777,
          digest: fileDigest(path),
        });
      } else {
        throw new Error(`dependency environment contains an unsupported entry: ${relativePath}`);
      }
    }
  };
  visit(root, "");
  return digest(entries);
}

function installedEnvironmentDigest(manager: "pnpm" | "uv", root: string): string {
  return directoryDigest(root, manager === "uv");
}

function remediation(host: BootstrapHost, catalogue: ReleaseCatalogue): string {
  return host.platform === "darwin"
    ? "/bin/bash -lc 'brew install node@24 python@3.13 uv'"
    : `docker pull ghcr.io/three-cubes/tc-sdlc@${catalogue.release.imageDigest}`;
}

function prerequisiteFailure(
  host: BootstrapHost,
  catalogue: ReleaseCatalogue,
  message: string,
  observed?: string,
): BootstrapFailure {
  return new BootstrapFailure("host_prerequisite_missing", [
    {
      code: "HOST_PREREQUISITE_MISSING",
      message,
      action: remediation(host, catalogue),
      ...(observed === undefined ? {} : { observed }),
    },
  ]);
}

function resolvesInside(parent: string, child: string): boolean {
  const value = relative(parent, child);
  return value === "" || (value !== ".." && !value.startsWith(`..${sep}`));
}

function absoluteStatePath(path: string): string {
  if (!isAbsolute(path)) {
    throw new BootstrapFailure("state_root_invalid", [
      {
        code: "STATE_ROOT_INVALID",
        message: "state root must be an absolute path outside the checkout",
        action: "provide --state-root with an absolute path outside the checkout",
      },
    ]);
  }
  return resolve(path);
}

function resolvedDestination(path: string): string {
  if (existsSync(path)) {
    if (lstatSync(path).isSymbolicLink()) {
      throw new BootstrapFailure("state_root_invalid", [
        {
          code: "STATE_ROOT_SYMLINK",
          message: "state root may not be a symbolic link",
          action: "choose a dedicated non-symlink state directory",
        },
      ]);
    }
    return realpathSync(path);
  }
  const missing: string[] = [];
  let cursor = path;
  while (!existsSync(cursor)) {
    missing.unshift(cursor.slice(dirname(cursor).length + 1));
    cursor = dirname(cursor);
  }
  return resolve(realpathSync(cursor), ...missing);
}

function validateStateRoot(root: string, value: string): string {
  const stateRoot = absoluteStatePath(value);
  const destination = resolvedDestination(stateRoot);
  if (resolvesInside(realpathSync(root), destination)) {
    throw new BootstrapFailure("state_root_invalid", [
      {
        code: "STATE_ROOT_IN_CHECKOUT",
        message: "managed bootstrap state must remain outside the checkout",
        action: "choose a dedicated state root outside the source checkout",
      },
    ]);
  }
  if (existsSync(stateRoot) && !lstatSync(stateRoot).isDirectory()) {
    throw new BootstrapFailure("state_root_invalid", [
      {
        code: "STATE_ROOT_INVALID",
        message: "state root exists but is not a directory",
        action: "choose an empty directory owned by tc-sdlc",
      },
    ]);
  }
  return stateRoot;
}

function rejectSymlinkComponents(stateRoot: string, target: string): void {
  const suffix = relative(stateRoot, target);
  if (suffix === "" || suffix === ".." || suffix.startsWith(`..${sep}`)) {
    throw new BootstrapFailure("state_corrupt", [
      {
        code: "BOOTSTRAP_STATE_PATH_INVALID",
        message: "managed state path escapes its owned root",
        action: "discard the corrupt state root and bootstrap online again",
      },
    ]);
  }
  let cursor = stateRoot;
  for (const segment of suffix.split(sep)) {
    cursor = join(cursor, segment);
    if (existsSync(cursor) && lstatSync(cursor).isSymbolicLink()) {
      throw new BootstrapFailure("state_corrupt", [
        {
          code: "BOOTSTRAP_STATE_SYMLINK",
          message: "managed release state may not traverse symbolic links",
          action: "discard the corrupt state root and bootstrap online again",
        },
      ]);
    }
  }
}

function readCanonical(path: string): unknown {
  const bytes = readFileSync(path, "utf8");
  const value = JSON.parse(bytes) as unknown;
  if (bytes !== canonicalJson(value)) {
    throw new Error("non-canonical state");
  }
  return value;
}

function inspectOwnership(stateRoot: string): "absent" | "owned" {
  if (!existsSync(stateRoot)) return "absent";
  const entries = readdirSync(stateRoot);
  const ownerPath = join(stateRoot, ".tc-sdlc-owner.json");
  if (!existsSync(ownerPath)) {
    if (entries.length === 0) return "absent";
    throw new BootstrapFailure("foreign_state", [
      {
        code: "STATE_ROOT_FOREIGN",
        message: "state root contains files not owned by tc-sdlc",
        action: "choose an empty state root or the original tc-sdlc state root",
      },
    ]);
  }
  try {
    if (
      lstatSync(ownerPath).isSymbolicLink() ||
      canonicalJson(readCanonical(ownerPath)) !== canonicalJson(OWNER)
    ) {
      throw new Error("owner mismatch");
    }
  } catch {
    throw new BootstrapFailure("foreign_state", [
      {
        code: "STATE_ROOT_FOREIGN",
        message: "state root ownership marker does not belong to tc-sdlc",
        action: "choose an empty state root or the original tc-sdlc state root",
      },
    ]);
  }
  return "owned";
}

function normalHost(value: BootstrapOptions["host"]): BootstrapHost {
  const platform = value?.platform ?? process.platform;
  if (platform !== "darwin" && platform !== "linux") {
    throw new BootstrapFailure("platform_unsupported", [
      {
        code: "PLATFORM_UNSUPPORTED",
        message: `native bootstrap does not support ${platform}`,
        action: "use supported macOS or the canonical Linux image",
      },
    ]);
  }
  return {
    platform,
    architecture: value?.architecture ?? process.arch,
    offline: value?.offline ?? false,
  };
}

function probeOutput(
  executable: string,
  pathValue: string,
  environment: NodeJS.ProcessEnv = {},
): string {
  return execFileSync(executable, ["--version"], {
    encoding: "utf8",
    env: { ...environment, PATH: pathValue },
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
}

function capability(
  contract: CapabilityContract,
  executable: string,
  expected: string,
  provider: HostCapability["provider"],
  pathValue: string,
  environment: NodeJS.ProcessEnv = {},
): HostCapability {
  accessSync(executable, constants.X_OK);
  const resolved = realpathSync(executable);
  if (!lstatSync(resolved).isFile()) throw new Error("capability is not a regular file");
  const observed = contract.observed(probeOutput(resolved, pathValue, environment));
  if (observed === null || !contract.matches(observed, expected)) {
    throw new Error(`${contract.name} expected ${expected}, observed ${observed ?? "unrecognised"}`);
  }
  return {
    name: contract.name,
    version: expected,
    provider,
    executable: resolved,
    executableDigest: fileDigest(resolved),
  };
}

function homebrewCapabilities(
  host: BootstrapHost,
  declaration: SdlcDeclaration,
  catalogue: ReleaseCatalogue,
  stateRoot: string,
): HostCapabilities {
  const prefix = host.architecture === "arm64" ? "/opt/homebrew" : "/usr/local";
  try {
    accessSync(join(prefix, "bin", "brew"), constants.X_OK);
    const nodeRoot = realpathSync(join(prefix, "opt", "node@24"));
    const pythonRoot = realpathSync(join(prefix, "opt", "python@3.13"));
    const uvExecutable = realpathSync(join(prefix, "bin", "uv"));
    if (
      !resolvesInside(join(prefix, "Cellar", "node@24"), nodeRoot) ||
      !resolvesInside(join(prefix, "Cellar", "python@3.13"), pythonRoot) ||
      !resolvesInside(join(prefix, "Cellar", "uv"), uvExecutable)
    ) {
      throw new Error("Homebrew capability escaped its formula cellar");
    }
    const node = join(prefix, "opt", "node@24", "bin", "node");
    const python = join(prefix, "opt", "python@3.13", "libexec", "bin", "python3");
    const pathValue = [dirname(node), dirname(python), join(prefix, "bin"), "/usr/bin", "/bin"].join(":");
    const probeEnvironment = managedProbeEnvironment(
      stateRoot,
      host,
      pathValue,
    );
    const adapters = [
      capability(
        contracts[0]!,
        node,
        declaration.toolchains.node,
        "homebrew",
        pathValue,
        probeEnvironment,
      ),
      capability(
        contracts[2]!,
        python,
        declaration.toolchains.python,
        "homebrew",
        pathValue,
        probeEnvironment,
      ),
    ];
    const installerVersion = contracts[3]!.observed(
      probeOutput(uvExecutable, pathValue, probeEnvironment),
    );
    if (installerVersion === null) throw new Error("Homebrew uv version was not recognised");
    const [major, minor, patch] = installerVersion.split(".").map(Number);
    if (major !== 0 || minor !== 12 || (patch ?? 0) < 5) {
      throw new Error(`uv installer must be >=0.12.5,<0.13, observed ${installerVersion}`);
    }
    const installerUv: HostCapability = {
      name: "uv",
      version: installerVersion,
      provider: "homebrew",
      executable: uvExecutable,
      executableDigest: fileDigest(uvExecutable),
    };
    return {
      adapters,
      installerUv,
      pnpmInstaller: {
        node: realpathSync(node),
        nodeRoot,
        corepack: join(nodeRoot, "lib", "node_modules", "corepack", "dist", "corepack.js"),
      },
    };
  } catch (error) {
    throw prerequisiteFailure(
      host,
      catalogue,
      "macOS bootstrap requires the reviewed Homebrew node@24, python@3.13 and uv prerequisites",
      error instanceof Error ? error.message : "invalid Homebrew prerequisite",
    );
  }
}

function canonicalImageCapabilities(
  host: BootstrapHost,
  declaration: SdlcDeclaration,
  catalogue: ReleaseCatalogue,
  stateRoot: string,
): HostCapabilities {
  try {
    const marker = readCanonical("/etc/tc-sdlc-release.json") as Record<string, unknown>;
    if (
      marker.schema !== "tc.sdlc/image-marker/v1" ||
      marker.release !== catalogue.release.version ||
      canonicalJson(marker.toolchains) !== canonicalJson(catalogue.release.toolchains)
    ) {
      throw new Error("canonical image marker does not match the release catalogue");
    }
    const paths = [
      "/usr/local/bin/node",
      "/usr/local/bin/pnpm",
      "/usr/local/bin/python3",
      "/usr/local/bin/uv",
    ] as const;
    const pathValue = "/usr/local/bin:/usr/bin:/bin";
    const probeEnvironment = managedProbeEnvironment(
      stateRoot,
      host,
      pathValue,
    );
    const adapters = contracts.map((contract, index) =>
      capability(
        contract,
        paths[index]!,
        contract.expected(declaration),
        "canonical-image",
        pathValue,
        probeEnvironment,
      ),
    );
    return { adapters, installerUv: adapters[3]! };
  } catch (error) {
    throw prerequisiteFailure(
      host,
      catalogue,
      "Linux bootstrap requires the catalogue-selected canonical image",
      error instanceof Error ? error.message : "invalid canonical image prerequisite",
    );
  }
}

function hostCapabilities(
  host: BootstrapHost,
  declaration: SdlcDeclaration,
  catalogue: ReleaseCatalogue,
  stateRoot: string,
): HostCapabilities {
  return host.platform === "darwin"
    ? homebrewCapabilities(host, declaration, catalogue, stateRoot)
    : canonicalImageCapabilities(host, declaration, catalogue, stateRoot);
}

function pnpmLockFailure(code: string, message: string): BootstrapFailure {
  return new BootstrapFailure("dependency_lock_invalid", [
    {
      code,
      message,
      action: "regenerate pnpm-lock.yaml with the declared pnpm version",
    },
  ]);
}

function workspaceImporterPaths(
  root: string,
  workspace: Record<string, unknown>,
): readonly string[] {
  const packages = workspace.packages;
  if (!Array.isArray(packages) || packages.some((pattern) => typeof pattern !== "string")) {
    throw pnpmLockFailure(
      "PNPM_WORKSPACE_PACKAGES_INVALID",
      "pnpm-workspace.yaml must declare package directory globs",
    );
  }
  const included = new Set<string>();
  const excluded: string[] = [];
  for (const rawPattern of packages as string[]) {
    const negated = rawPattern.startsWith("!");
    const pattern = negated ? rawPattern.slice(1) : rawPattern;
    if (
      pattern === "" ||
      isAbsolute(pattern) ||
      pattern.split("/").some((segment) => segment === "..")
    ) {
      throw pnpmLockFailure(
        "PNPM_WORKSPACE_PACKAGES_INVALID",
        "pnpm workspace package globs must remain inside the checkout",
      );
    }
    const manifestPattern = `${pattern.replace(/\/$/, "")}/package.json`;
    if (negated) {
      excluded.push(manifestPattern);
      continue;
    }
    for (const match of globSync(manifestPattern, {
      cwd: root,
      exclude: ["**/node_modules/**"],
    })) {
      included.add(match.replaceAll("\\", "/"));
    }
  }
  for (const pattern of excluded) {
    for (const match of globSync(pattern, { cwd: root })) {
      included.delete(match.replaceAll("\\", "/"));
    }
  }
  return [...included]
    .map((manifest) => posix.dirname(manifest))
    .map((importer) => importer === "." ? "." : importer)
    .sort();
}

function validatedPnpmImporters(
  root: string,
  lock: Readonly<{ importers?: Record<string, unknown> }>,
  workspace: Record<string, unknown> | undefined,
): readonly string[] {
  if (lock.importers === undefined || typeof lock.importers !== "object") {
    throw pnpmLockFailure(
      "PNPM_IMPORTERS_MISSING",
      "pnpm-lock.yaml must declare its complete importer graph",
    );
  }
  const importers = Object.keys(lock.importers)
    .map((importer) => importer === "" || importer === "./" ? "." : posix.normalize(importer))
    .sort();
  if (workspace !== undefined) {
    const workspaceImporters = [...new Set([".", ...workspaceImporterPaths(root, workspace)])].sort();
    if (canonicalJson(importers) !== canonicalJson(workspaceImporters)) {
      throw pnpmLockFailure(
        "PNPM_WORKSPACE_LOCK_MISMATCH",
        "pnpm-lock.yaml importers do not match every declared workspace package",
      );
    }
  }
  return importers;
}

function workspaceSourcePaths(root: string, importer: string): readonly string[] {
  if (importer === ".") return [];
  const manifestPath = posix.join(importer, "package.json");
  const manifest = JSON.parse(readFileSync(join(root, manifestPath), "utf8")) as {
    files?: unknown;
  };
  if (
    !Array.isArray(manifest.files) ||
    manifest.files.length === 0 ||
    manifest.files.some((path) => typeof path !== "string")
  ) {
    throw pnpmLockFailure(
      "PNPM_WORKSPACE_SOURCE_INVALID",
      `workspace package ${importer} must declare a non-empty files inventory`,
    );
  }
  const packageRoot = resolve(root, importer);
  const sources = new Set<string>();
  const collect = (source: string): void => {
    if (!resolvesInside(packageRoot, source) || !existsSync(source)) {
      throw pnpmLockFailure(
        "PNPM_WORKSPACE_SOURCE_INVALID",
        `workspace package ${importer} declares a missing source path`,
      );
    }
    const metadata = lstatSync(source);
    if (metadata.isSymbolicLink()) {
      throw pnpmLockFailure(
        "PNPM_WORKSPACE_SOURCE_INVALID",
        `workspace package ${importer} source inventory may not contain symbolic links`,
      );
    }
    if (metadata.isDirectory()) {
      for (const name of readdirSync(source).sort()) collect(join(source, name));
      return;
    }
    if (!metadata.isFile()) {
      throw pnpmLockFailure(
        "PNPM_WORKSPACE_SOURCE_INVALID",
        `workspace package ${importer} source inventory contains an unsupported entry`,
      );
    }
    sources.add(posix.join(importer, relative(packageRoot, source).replaceAll("\\", "/")));
  };
  for (const declared of manifest.files as string[]) {
    if (
      declared === "" ||
      declared === "." ||
      isAbsolute(declared) ||
      declared.split("/").some((segment) => segment === "..") ||
      /[*?{[]/.test(declared)
    ) {
      throw pnpmLockFailure(
        "PNPM_WORKSPACE_SOURCE_INVALID",
        `workspace package ${importer} files must name explicit in-package files or directories`,
      );
    }
    collect(resolve(packageRoot, declared));
  }
  return [...sources].sort();
}

function dependencyLocks(root: string): readonly DependencyLock[] {
  const dependencies: DependencyLock[] = [];
  const pnpmLock = join(root, "pnpm-lock.yaml");
  if (existsSync(pnpmLock)) {
    if (!existsSync(join(root, "package.json"))) {
      throw new BootstrapFailure("dependency_lock_invalid", [
        {
          code: "PNPM_MANIFEST_MISSING",
          message: "pnpm-lock.yaml requires package.json",
          action: "restore package.json and regenerate pnpm-lock.yaml",
        },
      ]);
    }
    const lock = parse(readFileSync(pnpmLock, "utf8")) as {
      importers?: Record<string, unknown>;
    };
    const inputPaths = new Set(["package.json", "pnpm-lock.yaml"]);
    const workspacePath = join(root, "pnpm-workspace.yaml");
    let workspace: Record<string, unknown> | undefined;
    if (existsSync(workspacePath)) {
      inputPaths.add("pnpm-workspace.yaml");
      workspace = parse(readFileSync(workspacePath, "utf8")) as Record<string, unknown>;
    }
    for (const importer of validatedPnpmImporters(root, lock, workspace)) {
      inputPaths.add(importer === "." ? "package.json" : posix.join(importer, "package.json"));
      for (const source of workspaceSourcePaths(root, importer)) inputPaths.add(source);
    }
    const rootManifest = JSON.parse(readFileSync(join(root, "package.json"), "utf8")) as {
      pnpm?: { patchedDependencies?: Record<string, string> };
    };
    const patchMaps = [
      rootManifest.pnpm?.patchedDependencies,
      workspace?.patchedDependencies as Record<string, string> | undefined,
    ];
    for (const patchMap of patchMaps) {
      for (const path of Object.values(patchMap ?? {})) inputPaths.add(path);
    }
    if (existsSync(join(root, ".npmrc"))) inputPaths.add(".npmrc");
    const inputs = dependencyInputs(root, inputPaths);
    dependencies.push({
      manager: "pnpm",
      lockDigest: fileDigest(pnpmLock),
      manifestDigest: digest(
        inputs
          .filter((input) => input.path !== "pnpm-lock.yaml")
          .map(({ path, digest: value }) => ({ path, digest: value })),
      ),
      environment: "dependencies/node",
      inputs,
    });
  }
  const uvLock = join(root, "uv.lock");
  if (existsSync(uvLock)) {
    if (!existsSync(join(root, "pyproject.toml"))) {
      throw new BootstrapFailure("dependency_lock_invalid", [
        {
          code: "PYTHON_MANIFEST_MISSING",
          message: "uv.lock requires pyproject.toml",
          action: "restore pyproject.toml and regenerate uv.lock",
        },
      ]);
    }
    const inputs = dependencyInputs(root, ["pyproject.toml", "uv.lock"]);
    dependencies.push({
      manager: "uv",
      lockDigest: fileDigest(uvLock),
      manifestDigest: digest(
        inputs
          .filter((input) => input.path !== "uv.lock")
          .map(({ path, digest: value }) => ({ path, digest: value })),
      ),
      environment: "dependencies/python",
      inputs,
    });
  }
  return dependencies;
}

function dependencyInputs(
  root: string,
  paths: Iterable<string>,
): readonly DependencyInput[] {
  const rootPath = realpathSync(root);
  return [...new Set(paths)]
    .map((path) => path.replaceAll("\\", "/"))
    .sort()
    .map((path) => {
      if (path === "" || isAbsolute(path) || path === ".." || path.startsWith("../")) {
        throw new BootstrapFailure("dependency_lock_invalid", [
          {
            code: "DEPENDENCY_INPUT_INVALID",
            message: "dependency metadata must remain inside the checkout",
            action: "remove traversal paths and regenerate the dependency lock",
          },
        ]);
      }
      const sourcePath = resolve(rootPath, path);
      if (
        !resolvesInside(rootPath, sourcePath) ||
        !existsSync(sourcePath) ||
        lstatSync(sourcePath).isSymbolicLink() ||
        !lstatSync(sourcePath).isFile()
      ) {
        throw new BootstrapFailure("dependency_lock_invalid", [
          {
            code: "DEPENDENCY_INPUT_INVALID",
            message: `dependency metadata is missing or unsafe: ${path}`,
            action: "restore dependency metadata and regenerate the dependency lock",
          },
        ]);
      }
      return { path, digest: fileDigest(sourcePath), sourcePath };
    });
}

function managedEnvironment(
  stateRoot: string,
  stateDirectory: string,
  pathValue: string,
  offline = false,
): NodeJS.ProcessEnv {
  const home = join(stateDirectory, "home");
  const cache = join(stateRoot, "cache");
  mkdirSync(home, { recursive: true, mode: 0o700 });
  mkdirSync(cache, { recursive: true, mode: 0o700 });
  return {
    HOME: home,
    PATH: pathValue,
    XDG_CACHE_HOME: cache,
    UV_CACHE_DIR: join(cache, "uv"),
    COREPACK_HOME: join(stateDirectory, "corepack"),
    COREPACK_ENABLE_NETWORK: offline ? "0" : "1",
  };
}

function managedProbeEnvironment(
  stateRoot: string,
  host: BootstrapHost,
  pathValue: string,
): NodeJS.ProcessEnv {
  const directory = join(stateRoot, "probes", `${host.platform}-${host.architecture}`);
  rejectSymlinkComponents(stateRoot, directory);
  rejectSymlinkComponents(stateRoot, join(stateRoot, "cache"));
  return managedEnvironment(stateRoot, directory, pathValue, host.offline);
}

function writeAtomicExecutable(path: string, bytes: string): void {
  const temporary = `${path}.tmp-${process.pid}`;
  try {
    writeFileSync(temporary, bytes, { flag: "wx", mode: 0o755 });
    chmodSync(temporary, 0o755);
    renameSync(temporary, path);
  } catch (error) {
    rmSync(temporary, { force: true });
    throw error;
  }
}

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", `'"'"'`)}'`;
}

function pnpmDistributionRoot(executable: string): string {
  return dirname(dirname(executable));
}

function materializeCataloguePnpm(
  options: BootstrapOptions,
  host: BootstrapHost,
  stateRoot: string,
  stateDirectory: string,
  installer: PnpmInstaller | undefined,
): HostCapability {
  if (installer === undefined) {
    throw prerequisiteFailure(
      host,
      options.catalogue,
      "macOS bootstrap requires Corepack from the reviewed Homebrew node@24 prerequisite",
    );
  }
  if (host.offline) {
    throw new BootstrapFailure("offline_cold", [
      {
        code: "BOOTSTRAP_OFFLINE_COLD",
        message: "offline bootstrap requires an existing verified warm state",
        action: "retry without offline mode to materialise the release state",
      },
    ]);
  }
  let corepack: string;
  try {
    corepack = realpathSync(installer.corepack);
    if (
      !resolvesInside(installer.nodeRoot, corepack) ||
      lstatSync(corepack).isSymbolicLink() ||
      !lstatSync(corepack).isFile()
    ) {
      throw new Error("Corepack escaped the reviewed node@24 formula");
    }
  } catch (error) {
    throw prerequisiteFailure(
      host,
      options.catalogue,
      "macOS bootstrap requires Corepack from the reviewed Homebrew node@24 prerequisite",
      error instanceof Error ? error.message : "invalid Corepack prerequisite",
    );
  }
  const version = options.declaration.toolchains.packageManager.replace(/^pnpm@/, "");
  const pathValue = `${dirname(installer.node)}:/usr/bin:/bin`;
  rejectSymlinkComponents(stateRoot, join(stateDirectory, "corepack"));
  const environment = managedEnvironment(
    stateRoot,
    stateDirectory,
    pathValue,
  );
  execFileSync(
    installer.node,
    [corepack, "install", "--global", `pnpm@${version}`],
    { cwd: options.root, env: environment, stdio: "pipe" },
  );
  const distribution = join(stateDirectory, "corepack", "v1", "pnpm", version);
  const executable = join(distribution, "bin", "pnpm.cjs");
  rejectSymlinkComponents(stateRoot, executable);
  if (
    !existsSync(executable) ||
    lstatSync(executable).isSymbolicLink() ||
    !lstatSync(executable).isFile()
  ) {
    throw new BootstrapFailure("distribution_corrupt", [
      {
        code: "PNPM_DISTRIBUTION_INVALID",
        capability: "pnpm",
        expected: version,
        message: "Corepack did not materialise the exact pnpm distribution in owned state",
        action: "discard the partial state and retry online",
      },
    ]);
  }
  const observed = contracts[1]!.observed(
    execFileSync(installer.node, [executable, "--version"], {
      encoding: "utf8",
      env: { ...environment, COREPACK_ENABLE_NETWORK: "0" },
      stdio: ["ignore", "pipe", "pipe"],
    }).trim(),
  );
  if (observed === null || !contracts[1]!.matches(observed, version)) {
    throw new BootstrapFailure("distribution_corrupt", [
      {
        code: "PNPM_DISTRIBUTION_VERSION_MISMATCH",
        capability: "pnpm",
        expected: version,
        observed: observed ?? "unrecognised",
        message: "state-owned pnpm distribution does not match the declared version",
        action: "discard the partial state and retry online",
      },
    ]);
  }
  return {
    name: "pnpm",
    version,
    provider: "catalogue-distribution",
    executable,
    executableDigest: directoryDigest(distribution),
  };
}

async function materializeCatalogueUv(
  options: BootstrapOptions,
  host: BootstrapHost,
  stateRoot: string,
  stateDirectory: string,
  installerUv: HostCapability,
  python: HostCapability,
): Promise<HostCapability> {
  const platformKey = `${host.platform}-${host.architecture}` as keyof typeof options.catalogue.release.bootstrap.uv.wheels;
  const distribution = options.catalogue.release.bootstrap.uv.wheels[platformKey];
  if (distribution === undefined) {
    throw prerequisiteFailure(host, options.catalogue, `no uv distribution is declared for ${platformKey}`);
  }
  if (host.offline) {
    throw new BootstrapFailure("offline_cold", [
      {
        code: "BOOTSTRAP_OFFLINE_COLD",
        message: "offline bootstrap requires an existing verified warm state",
        action: "retry without offline mode to materialise the release state",
      },
    ]);
  }
  const response = await fetch(distribution.url, { redirect: "error" });
  if (!response.ok) throw new Error(`uv distribution download failed with HTTP ${response.status}`);
  const bytes = Buffer.from(await response.arrayBuffer());
  const observed = createHash("sha256").update(bytes).digest("hex");
  if (observed !== distribution.sha256) {
    throw new BootstrapFailure("distribution_corrupt", [
      {
        code: "DISTRIBUTION_DIGEST_MISMATCH",
        capability: "uv",
        expected: distribution.sha256,
        observed,
        message: "downloaded uv distribution does not match the release catalogue",
        action: "discard the partial state and retry from the canonical distribution",
      },
    ]);
  }
  const downloads = join(stateDirectory, "downloads");
  const environment = join(stateDirectory, "toolchains", "uv");
  mkdirSync(downloads, { recursive: true, mode: 0o700 });
  const wheelName = new URL(distribution.url).pathname.split("/").at(-1);
  if (wheelName === undefined || !wheelName.endsWith(".whl")) {
    throw new BootstrapFailure("distribution_corrupt", [
      {
        code: "DISTRIBUTION_NAME_INVALID",
        capability: "uv",
        message: "catalogue uv distribution does not have a wheel filename",
        action: "regenerate the release catalogue from immutable distribution metadata",
      },
    ]);
  }
  const wheel = join(downloads, wheelName);
  writeFileSync(wheel, bytes, { flag: "wx", mode: 0o600 });
  const hostPath = [dirname(installerUv.executable), dirname(python.executable), "/usr/bin", "/bin"].join(":");
  const env = managedEnvironment(stateRoot, stateDirectory, hostPath);
  execFileSync(installerUv.executable, ["venv", environment, "--python", python.executable], {
    cwd: options.root,
    env,
    stdio: "pipe",
  });
  const environmentPython = join(environment, "bin", "python");
  execFileSync(
    installerUv.executable,
    ["pip", "install", "--python", environmentPython, "--no-deps", "--offline", wheel],
    { cwd: options.root, env, stdio: "pipe" },
  );
  return capability(
    contracts[3]!,
    join(environment, "bin", "uv"),
    options.declaration.toolchains.uv,
    "canonical-image",
    `${join(environment, "bin")}:${hostPath}`,
  );
}

function adapterEvidence(adapter: ResolvedAdapter): BootstrapAdapterEvidence {
  return {
    name: adapter.name,
    version: adapter.version,
    provider: adapter.provider,
    executableDigest: adapter.executableDigest,
    launcherDigest: adapter.launcherDigest,
    adapterDigest: adapter.adapterDigest,
    launcher: adapter.launcher,
  };
}

function resolvedAdapter(
  stateRoot: string,
  stateKey: string,
  value: HostCapability,
  capabilities: readonly HostCapability[],
): ResolvedAdapter {
  const launcher = posix.join(stateKey, "bin", value.name);
  const launcherPath = resolve(stateRoot, launcher);
  const node = capabilities.find((capability) => capability.name === "node");
  const bytes = value.name === "pnpm"
    ? `#!/bin/sh\nset -eu\nSCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexport HOME="$SCRIPT_DIR/../home"\nexport XDG_CONFIG_HOME="$SCRIPT_DIR/../home/config"\nexport COREPACK_HOME="$SCRIPT_DIR/../corepack"\nexec ${shellQuote(node!.executable)} ${shellQuote(value.executable)} "$@"\n`
    : `#!/bin/sh\nset -eu\nexec ${shellQuote(value.executable)} "$@"\n`;
  writeAtomicExecutable(launcherPath, bytes);
  const launcherDigest = bytesDigest(bytes);
  return {
    ...value,
    launcher,
    launcherDigest,
    adapterDigest: digest({
      name: value.name,
      version: value.version,
      provider: value.provider,
      executableDigest: value.executableDigest,
      launcherDigest,
    }),
  };
}

function materializeDependencies(
  options: BootstrapOptions,
  stateRoot: string,
  stateDirectory: string,
  dependencies: readonly DependencyLock[],
  adapters: readonly ResolvedAdapter[],
): readonly BootstrapDependencyEvidence[] {
  const byName = new Map(adapters.map((adapter) => [adapter.name, adapter]));
  const pathValue = [
    dirname(byName.get("node")!.executable),
    dirname(byName.get("pnpm")!.executable),
    dirname(byName.get("python")!.executable),
    dirname(byName.get("uv")!.executable),
    "/usr/bin",
    "/bin",
  ].join(":");
  const env = managedEnvironment(stateRoot, stateDirectory, pathValue, options.host?.offline ?? false);
  const evidence: BootstrapDependencyEvidence[] = [];
  for (const dependency of dependencies) {
    const destination = resolve(stateDirectory, dependency.environment);
    mkdirSync(dirname(destination), { recursive: true, mode: 0o700 });
    if (dependency.manager === "pnpm") {
      const project = join(stateDirectory, "dependencies", "node");
      mkdirSync(project, { recursive: true, mode: 0o700 });
      for (const input of dependency.inputs) {
        const target = resolve(project, input.path);
        mkdirSync(dirname(target), { recursive: true, mode: 0o700 });
        writeFileSync(target, readFileSync(input.sourcePath), {
          flag: "wx",
          mode: lstatSync(input.sourcePath).mode & 0o7777,
        });
      }
      execFileSync(
        resolve(stateRoot, byName.get("pnpm")!.launcher),
        [
          "--dir",
          project,
          "install",
          "--frozen-lockfile",
          "--store-dir",
          join(stateRoot, "cache", "pnpm"),
        ],
        { cwd: project, env, stdio: "pipe" },
      );
      evidence.push({
        ...dependencyBinding(dependency),
        installedDigest: directoryDigest(project),
      });
    } else {
      execFileSync(
        byName.get("uv")!.executable,
        ["sync", "--frozen", "--project", options.root, "--no-install-project"],
        {
          cwd: options.root,
          env: { ...env, UV_PROJECT_ENVIRONMENT: destination },
          stdio: "pipe",
        },
      );
      evidence.push({
        ...dependencyBinding(dependency),
        installedDigest: installedEnvironmentDigest("uv", destination),
      });
    }
  }
  return evidence;
}

function dependencyBinding(dependency: DependencyLock): BootstrapDependencyEvidence {
  return {
    manager: dependency.manager,
    lockDigest: dependency.lockDigest,
    manifestDigest: dependency.manifestDigest,
    environment: dependency.environment,
    inputs: dependency.inputs.map(({ path, digest: value }) => ({ path, digest: value })),
  };
}

async function materializeState(
  options: BootstrapOptions,
  host: BootstrapHost,
  stateRoot: string,
  stateKey: string,
  lockDigest: string,
  dependencyDigest: string,
  dependencies: readonly DependencyLock[],
  prerequisites: ReturnType<typeof hostCapabilities>,
): Promise<BootstrapState> {
  const directory = resolve(stateRoot, stateKey);
  rejectSymlinkComponents(stateRoot, directory);
  if (existsSync(directory)) {
    throw new BootstrapFailure("state_corrupt", [
      {
        code: "BOOTSTRAP_STATE_PARTIAL",
        message: "release state exists without a valid completion manifest",
        action: "discard the partial release state and bootstrap online again",
      },
    ]);
  }
  mkdirSync(join(directory, "bin"), { recursive: true, mode: 0o700 });
  let capabilities = prerequisites.adapters;
  if (host.platform === "darwin") {
    const python = capabilities.find((value) => value.name === "python")!;
    const pnpm = materializeCataloguePnpm(
      options,
      host,
      stateRoot,
      directory,
      prerequisites.pnpmInstaller,
    );
    const uv = await materializeCatalogueUv(
      options,
      host,
      stateRoot,
      directory,
      prerequisites.installerUv,
      python,
    );
    const byName = new Map<string, HostCapability>([
      ...capabilities.map((capability) => [capability.name, capability] as const),
      [pnpm.name, pnpm],
      [uv.name, { ...uv, provider: "catalogue-distribution" }],
    ]);
    capabilities = contracts.map((contract) => byName.get(contract.name)!);
  }
  const adapters = capabilities.map((value) =>
    resolvedAdapter(stateRoot, stateKey, value, capabilities),
  );
  const dependencyEvidence = materializeDependencies(
    options,
    stateRoot,
    directory,
    dependencies,
    adapters,
  );
  const state: BootstrapState = {
    schema: "tc.sdlc/bootstrap-state/v6",
    release: options.catalogue.release.version,
    lockDigest,
    dependencyDigest,
    platform: host.platform,
    architecture: host.architecture,
    adapters,
    dependencies: dependencyEvidence,
  };
  writeCanonicalEvidence(join(directory, "state.json"), state);
  return state;
}

function validateWarmState(
  options: BootstrapOptions,
  host: BootstrapHost,
  stateRoot: string,
  stateKey: string,
  lockDigest: string,
  dependencyDigest: string,
  dependencies: readonly DependencyLock[],
  prerequisites: ReturnType<typeof hostCapabilities>,
): BootstrapState | null {
  const statePath = resolve(stateRoot, stateKey, "state.json");
  rejectSymlinkComponents(stateRoot, statePath);
  if (!existsSync(statePath)) {
    if (existsSync(dirname(statePath))) {
      throw new BootstrapFailure("state_corrupt", [
        {
          code: "BOOTSTRAP_STATE_PARTIAL",
          message: "release state exists without a valid completion manifest",
          action: "discard the partial release state and bootstrap online again",
        },
      ]);
    }
    return null;
  }
  try {
    const state = readCanonical(statePath) as BootstrapState;
    const expectedDependencies = dependencies.map(dependencyBinding);
    const stateDependencyBindings = state.dependencies.map(
      ({ installedDigest: _installedDigest, ...binding }) => binding,
    );
    if (
      state.schema !== "tc.sdlc/bootstrap-state/v6" ||
      state.release !== options.catalogue.release.version ||
      state.lockDigest !== lockDigest ||
      state.dependencyDigest !== dependencyDigest ||
      state.platform !== host.platform ||
      state.architecture !== host.architecture ||
      canonicalJson(stateDependencyBindings) !== canonicalJson(expectedDependencies) ||
      !Array.isArray(state.adapters) ||
      state.adapters.length !== contracts.length
    ) {
      throw new Error("state bindings mismatch");
    }
    const current = new Map(prerequisites.adapters.map((value) => [value.name, value]));
    const adapterPath = [
      ...new Set(state.adapters.map((adapter) => dirname(adapter.executable))),
      "/usr/local/bin",
      "/usr/bin",
      "/bin",
    ].join(":");
    for (const [index, contract] of contracts.entries()) {
      const adapter = state.adapters[index];
      if (
        adapter === undefined ||
        adapter.name !== contract.name ||
        adapter.version !== contract.expected(options.declaration) ||
        adapter.launcher !== posix.join(stateKey, "bin", adapter.name)
      ) {
        throw new Error("adapter bindings mismatch");
      }
      const launcher = resolve(stateRoot, adapter.launcher);
      rejectSymlinkComponents(stateRoot, launcher);
      if (adapter.provider === "catalogue-distribution") {
        rejectSymlinkComponents(
          realpathSync(stateRoot),
          realpathSync(adapter.executable),
        );
      }
      const executableDigest =
        adapter.name === "pnpm" && adapter.provider === "catalogue-distribution"
          ? directoryDigest(pnpmDistributionRoot(adapter.executable))
          : fileDigest(adapter.executable);
      if (
        !existsSync(launcher) ||
        lstatSync(launcher).isSymbolicLink() ||
        fileDigest(launcher) !== adapter.launcherDigest ||
        !existsSync(adapter.executable) ||
        lstatSync(adapter.executable).isSymbolicLink() ||
        !lstatSync(adapter.executable).isFile() ||
        executableDigest !== adapter.executableDigest
      ) {
        throw new Error("adapter artifact mismatch");
      }
      const hostCapability = current.get(adapter.name);
      if (
        adapter.provider !== "catalogue-distribution" &&
        (hostCapability === undefined ||
          hostCapability.executable !== adapter.executable ||
          hostCapability.executableDigest !== adapter.executableDigest)
      ) {
        throw new Error("host prerequisite changed");
      }
      const observed = contract.observed(
        adapter.name === "pnpm"
          ? probeOutput(
              launcher,
              adapterPath,
              managedEnvironment(
                stateRoot,
                resolve(stateRoot, stateKey),
                adapterPath,
                host.offline,
              ),
            )
          : probeOutput(adapter.executable, adapterPath),
      );
      if (observed === null || !contract.matches(observed, adapter.version)) {
        throw new Error("adapter version changed");
      }
      if (
        adapter.adapterDigest !==
        digest({
          name: adapter.name,
          version: adapter.version,
          provider: adapter.provider,
          executableDigest: adapter.executableDigest,
          launcherDigest: adapter.launcherDigest,
        })
      ) {
        throw new Error("adapter digest mismatch");
      }
    }
    for (const dependency of state.dependencies) {
      const environment = resolve(stateRoot, stateKey, dependency.environment);
      rejectSymlinkComponents(stateRoot, environment);
      if (!existsSync(environment)) {
        throw new Error("dependency environment missing");
      }
      if (
        !/^sha256:[0-9a-f]{64}$/.test(dependency.installedDigest ?? "") ||
        installedEnvironmentDigest(dependency.manager, environment) !==
          dependency.installedDigest
      ) {
        throw new Error("installed dependency environment changed");
      }
    }
    return state;
  } catch (error) {
    if (error instanceof BootstrapFailure) throw error;
    throw new BootstrapFailure("state_corrupt", [
      {
        code: "BOOTSTRAP_STATE_CORRUPT",
        message: "warm bootstrap state does not match its immutable bindings",
        action: "discard the corrupt release state and bootstrap online again",
      },
    ]);
  }
}

function failureReason(error: unknown): Readonly<{
  reason: string;
  diagnostics: readonly BootstrapDiagnostic[];
}> {
  if (error instanceof BootstrapFailure) return error;
  if (error instanceof SdlcError && error.code === "LOCK_STALE") {
    return {
      reason: "stale_lock",
      diagnostics: [
        {
          code: error.code,
          message: error.message,
          action: "regenerate the lock from the exact declaration and release catalogue",
        },
      ],
    };
  }
  return {
    reason: "bootstrap_failed",
    diagnostics: [
      {
        code: error instanceof SdlcError ? error.code : "BOOTSTRAP_FAILED",
        message: "bootstrap could not materialise the declared environment",
        action: "discard any partial release state, correct the prerequisite or lock failure, and retry",
      },
    ],
  };
}

export function serialiseBootstrapReceipt(receipt: BootstrapReceipt): string {
  return canonicalJson(receipt);
}

function failedReceipt(
  options: BootstrapOptions,
  host: BootstrapHost,
  stateKey: string,
  reused: boolean,
  taskIdentities: readonly string[],
  adapters: readonly BootstrapAdapterEvidence[],
  dependencies: readonly BootstrapDependencyEvidence[],
  failure: Readonly<{ reason: string; diagnostics: readonly BootstrapDiagnostic[] }>,
  maximumDiagnostics: number,
  recovery: AutomaticRecoveryReceipt,
): BootstrapReceipt {
  return {
    schema: "tc.sdlc/bootstrap-receipt/v1",
    status: "failed",
    reason: failure.reason,
    release: options.catalogue.release.version,
    lockDigest: digest(options.lock),
    platform: host.platform,
    architecture: host.architecture,
    stateKey,
    reused,
    taskIdentities,
    adapters,
    dependencies,
    recovery,
    diagnostics: failure.diagnostics.slice(0, maximumDiagnostics),
    diagnosticsCount: failure.diagnostics.length,
    diagnosticsTruncated: failure.diagnostics.length > maximumDiagnostics,
  };
}

export async function bootstrap(options: BootstrapOptions): Promise<BootstrapReceipt> {
  const recovery = await recoverInterruptedTemporaryState();
  const maximumDiagnostics = options.maxDiagnostics ?? 20;
  if (!Number.isSafeInteger(maximumDiagnostics) || maximumDiagnostics < 1) {
    throw new TypeError("maxDiagnostics must be a positive safe integer");
  }
  const fallbackPlatform = process.platform === "linux" ? "linux" : "darwin";
  let host: BootstrapHost = {
    platform: fallbackPlatform,
    architecture: options.host?.architecture ?? process.arch,
    offline: options.host?.offline ?? false,
  };
  const lockDigest = digest(options.lock);
  let stateKey = "unresolved";
  let reused = false;
  let taskIdentities: readonly string[] = [];
  let adapters: readonly BootstrapAdapterEvidence[] = [];
  let dependencyEvidence: readonly BootstrapDependencyEvidence[] = [];
  try {
    host = normalHost(options.host);
    assertCurrentLock(options.lock, options.declaration, options.catalogue);
    const inventory = resolveInputInventory(options.root, options.declaration);
    const bound = bindGraphLock(options.declaration, options.lock, options.catalogue, inventory);
    taskIdentities = buildGraph(options.declaration, bound).tasks.map((task) => task.identity);
    const dependencies = dependencyLocks(options.root);
    dependencyEvidence = dependencies.map(dependencyBinding);
    const dependencyDigest = digest(dependencyEvidence);
    stateKey = posix.join(
      "releases",
      lockDigest.slice("sha256:".length),
      dependencyDigest.slice("sha256:".length),
      `${host.platform}-${host.architecture}`,
    );
    const stateRoot = validateStateRoot(options.root, options.stateRoot);
    const ownership = inspectOwnership(stateRoot);
    mkdirSync(stateRoot, { recursive: true, mode: 0o700 });
    chmodSync(stateRoot, 0o700);
    if (ownership === "absent") {
      writeCanonicalEvidence(join(stateRoot, ".tc-sdlc-owner.json"), OWNER);
    }
    const prerequisites = hostCapabilities(
      host,
      options.declaration,
      options.catalogue,
      stateRoot,
    );
    if (ownership === "owned") {
      const warm = validateWarmState(
        options,
        host,
        stateRoot,
        stateKey,
        lockDigest,
        dependencyDigest,
        dependencies,
        prerequisites,
      );
      if (warm !== null) {
        reused = true;
        adapters = warm.adapters.map(adapterEvidence);
        dependencyEvidence = warm.dependencies;
      }
    }
    if (!reused) {
      if (host.offline) {
        throw new BootstrapFailure("offline_cold", [
          {
            code: "BOOTSTRAP_OFFLINE_COLD",
            message: "offline bootstrap requires an existing verified warm state",
            action: "retry without offline mode to materialise the release state",
          },
        ]);
      }
      const state = await materializeState(
        options,
        host,
        stateRoot,
        stateKey,
        lockDigest,
        dependencyDigest,
        dependencies,
        prerequisites,
      );
      adapters = state.adapters.map(adapterEvidence);
      dependencyEvidence = state.dependencies;
    }
    const finalStatePath = resolve(stateRoot, stateKey);
    const verified = validateWarmState(
      options,
      host,
      stateRoot,
      stateKey,
      lockDigest,
      dependencyDigest,
      dependencies,
      prerequisites,
    );
    if (verified === null) {
      throw new BootstrapFailure("state_changed", [
        {
          code: "BOOTSTRAP_STATE_CHANGED",
          message: "bootstrap state changed before reference publication",
          action: "retry bootstrap to materialise and reference one verified state",
        },
      ]);
    }
    const verifiedIdentity = filesystemIdentity(finalStatePath);
    const publication = writePendingBootstrapReference(
      stateRoot,
      options.declaration.project,
      realpathSync(options.root),
      stateKey,
      verifiedIdentity,
    );
    let finalState: BootstrapState | null = null;
    try {
      finalState = validateWarmState(
        options,
        host,
        stateRoot,
        stateKey,
        lockDigest,
        dependencyDigest,
        dependencies,
        prerequisites,
      );
      if (
        finalState === null ||
        !sameFilesystemIdentity(finalStatePath, verifiedIdentity)
      ) {
        throw new BootstrapFailure("state_changed", [
          {
            code: "BOOTSTRAP_STATE_CHANGED",
            message: "bootstrap state changed before reference publication",
            action: "retry bootstrap to materialise and reference one verified state",
          },
        ]);
      }
      commitBootstrapReference(stateRoot, publication);
      removePendingBootstrapReference(publication);
    } catch (error) {
      removePendingBootstrapReference(publication);
      throw error;
    }
    adapters = finalState.adapters.map(adapterEvidence);
    dependencyEvidence = finalState.dependencies;
    const receipt: BootstrapReceipt = {
      schema: "tc.sdlc/bootstrap-receipt/v1",
      status: "succeeded",
      reason: null,
      release: options.catalogue.release.version,
      lockDigest,
      platform: host.platform,
      architecture: host.architecture,
      stateKey,
      reused,
      taskIdentities,
      adapters,
      dependencies: dependencyEvidence,
      recovery,
      diagnostics: [],
      diagnosticsCount: 0,
      diagnosticsTruncated: false,
    };
    writeCanonicalEvidence(options.receiptPath, receipt);
    return receipt;
  } catch (error) {
    const receipt = failedReceipt(
      options,
      host,
      stateKey,
      reused,
      taskIdentities,
      adapters,
      dependencyEvidence,
      failureReason(error),
      maximumDiagnostics,
      recovery,
    );
    writeCanonicalEvidence(options.receiptPath, receipt);
    return receipt;
  }
}
