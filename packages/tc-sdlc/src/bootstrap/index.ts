import { execFileSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import {
  accessSync,
  chmodSync,
  copyFileSync,
  constants,
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  readdirSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { delimiter, dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { posix } from "node:path";

import { bytesDigest, canonicalJson, digest } from "../canonical.js";
import { SdlcError } from "../errors.js";
import { writeCanonicalEvidence } from "../evidence/index.js";
import { bindGraphLock, buildGraph } from "../graph/index.js";
import { resolveInputInventory } from "../inputs/index.js";
import { assertCurrentLock } from "../lock/index.js";
import type {
  ReleaseCatalogue,
  SdlcDeclaration,
  SdlcLock,
} from "../schema/types.js";

export type BootstrapPlatform = "darwin" | "linux";
export type BootstrapCapabilityName = "node" | "pnpm" | "python" | "uv";

export type BootstrapHost = Readonly<{
  platform: BootstrapPlatform;
  architecture: string;
  path: string;
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
  executableDigest: string;
  launcherDigest: string;
  adapterDigest: string;
  launcher: string;
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
  executable: string;
  expected: (declaration: SdlcDeclaration) => string;
  observed: (output: string) => string | null;
  matches: (actual: string, expected: string) => boolean;
}>;

type ResolvedAdapter = BootstrapAdapterEvidence &
  Readonly<{
    artifact: string;
  }>;

type DiscoveredAdapter = Readonly<{
  name: BootstrapCapabilityName;
  version: string;
  source: string;
  executableDigest: string;
}>;

type BootstrapState = Readonly<{
  schema: "tc.sdlc/bootstrap-state/v1";
  release: string;
  lockDigest: string;
  platform: BootstrapPlatform;
  architecture: string;
  adapters: readonly ResolvedAdapter[];
}>;

const OWNER = {
  schema: "tc.sdlc/state-owner/v1",
  owner: "@three-cubes/tc-sdlc",
} as const;

const contracts: readonly CapabilityContract[] = [
  {
    name: "node",
    executable: "node",
    expected: (declaration) => declaration.toolchains.node,
    observed: (output) => output.match(/\bv?(\d+)(?:\.\d+){0,2}\b/)?.[1] ?? null,
    matches: (actual, expected) => actual === expected,
  },
  {
    name: "pnpm",
    executable: "pnpm",
    expected: (declaration) => declaration.toolchains.packageManager.replace(/^pnpm@/, ""),
    observed: (output) => output.match(/\b(\d+\.\d+\.\d+)\b/)?.[1] ?? null,
    matches: (actual, expected) => actual === expected,
  },
  {
    name: "python",
    executable: "python3",
    expected: (declaration) => declaration.toolchains.python,
    observed: (output) => output.match(/\bPython\s+(\d+\.\d+)(?:\.\d+)?\b/i)?.[1] ?? null,
    matches: (actual, expected) => actual === expected,
  },
  {
    name: "uv",
    executable: "uv",
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

function resolvesInside(parent: string, child: string): boolean {
  const value = relative(parent, child);
  return value === "" || (value !== ".." && !value.startsWith(`..${sep}`));
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

function validateStateRoot(root: string, stateRootValue: string): string {
  const stateRoot = absoluteStatePath(stateRootValue);
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
  if (!existsSync(stateRoot)) {
    return "absent";
  }
  const entries = readdirSync(stateRoot);
  const ownerPath = join(stateRoot, ".tc-sdlc-owner.json");
  if (!existsSync(ownerPath)) {
    if (entries.length === 0) {
      return "absent";
    }
    throw new BootstrapFailure("foreign_state", [
      {
        code: "STATE_ROOT_FOREIGN",
        message: "state root contains files not owned by tc-sdlc",
        action: "choose an empty state root or the original tc-sdlc state root",
      },
    ]);
  }
  if (lstatSync(ownerPath).isSymbolicLink()) {
    throw new BootstrapFailure("state_corrupt", [
      {
        code: "STATE_OWNER_CORRUPT",
        message: "state ownership marker is not a regular canonical file",
        action: "discard the corrupt state root and bootstrap online again",
      },
    ]);
  }
  try {
    if (canonicalJson(readCanonical(ownerPath)) !== canonicalJson(OWNER)) {
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

function resolveExecutable(pathValue: string, name: string): string | null {
  for (const directory of pathValue.split(delimiter).filter(Boolean)) {
    const candidate = resolve(directory, name);
    try {
      accessSync(candidate, constants.X_OK);
      const resolved = realpathSync(candidate);
      if (lstatSync(resolved).isFile()) {
        return resolved;
      }
    } catch {
      // Continue through PATH until an executable regular file is found.
    }
  }
  return null;
}

function probe(
  contract: CapabilityContract,
  executable: string,
  expected: string,
  pathValue: string,
): Readonly<{ observed: string; executableDigest: string }> {
  let output: string;
  try {
    output = execFileSync(executable, ["--version"], {
      encoding: "utf8",
      env: { PATH: pathValue },
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (error) {
    throw new BootstrapFailure("capability_version_mismatch", [
      {
        code: "CAPABILITY_PROBE_FAILED",
        capability: contract.name,
        expected,
        message: `${contract.name} could not report its version`,
        action: `install ${contract.name} ${expected} and retry bootstrap`,
        observed: error instanceof Error ? error.name : "probe_failed",
      },
    ]);
  }
  const observed = contract.observed(output.trim());
  if (observed === null || !contract.matches(observed, expected)) {
    throw new BootstrapFailure("capability_version_mismatch", [
      {
        code: "CAPABILITY_VERSION_MISMATCH",
        capability: contract.name,
        expected,
        observed: observed ?? "unrecognised",
        message: `${contract.name} does not match the catalogue-owned version`,
        action: `install ${contract.name} ${expected} and retry bootstrap`,
      },
    ]);
  }
  return { observed, executableDigest: fileDigest(executable) };
}

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", `'"'"'`)}'`;
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

function adapterEvidence(adapter: ResolvedAdapter): BootstrapAdapterEvidence {
  return {
    name: adapter.name,
    version: adapter.version,
    executableDigest: adapter.executableDigest,
    launcherDigest: adapter.launcherDigest,
    adapterDigest: adapter.adapterDigest,
    launcher: adapter.launcher,
  };
}

function discoverAdapters(
  declaration: SdlcDeclaration,
  host: BootstrapHost,
): readonly DiscoveredAdapter[] {
  const missing = contracts
    .filter((contract) => resolveExecutable(host.path, contract.executable) === null)
    .map((contract): BootstrapDiagnostic => {
      const expected = contract.expected(declaration);
      return {
        code: "CAPABILITY_MISSING",
        capability: contract.name,
        expected,
        message: `${contract.name} is missing from the declared host PATH`,
        action: `install ${contract.name} ${expected} and retry bootstrap`,
      };
    });
  if (missing.length > 0) {
    throw new BootstrapFailure("capability_missing", missing);
  }
  return contracts.map((contract) => {
    const source = resolveExecutable(host.path, contract.executable) as string;
    const expected = contract.expected(declaration);
    const result = probe(contract, source, expected, host.path);
    return {
      name: contract.name,
      version: expected,
      source,
      executableDigest: result.executableDigest,
    };
  });
}

function materializeAdapters(
  stateRoot: string,
  stateKey: string,
  release: string,
  lockDigest: string,
  host: BootstrapHost,
  discovered: ReturnType<typeof discoverAdapters>,
): readonly ResolvedAdapter[] {
  const directory = resolve(stateRoot, stateKey);
  rejectSymlinkComponents(stateRoot, directory);
  if (existsSync(directory)) {
    throw new BootstrapFailure("state_corrupt", [
      {
        code: "BOOTSTRAP_STATE_PARTIAL",
        message: "release state exists without a valid immutable manifest",
        action: "discard the partial release state and bootstrap online again",
      },
    ]);
  }
  const parent = dirname(directory);
  mkdirSync(parent, { recursive: true, mode: 0o700 });
  rejectSymlinkComponents(stateRoot, parent);
  const staging = `${directory}.tmp-${process.pid}-${randomUUID()}`;
  const bin = resolve(staging, "bin");
  const artifacts = resolve(staging, "artifacts");
  try {
    mkdirSync(bin, { recursive: true, mode: 0o700 });
    mkdirSync(artifacts, { recursive: true, mode: 0o700 });
    for (const adapter of discovered) {
      const artifact = resolve(artifacts, adapter.name);
      copyFileSync(adapter.source, artifact, constants.COPYFILE_EXCL);
      chmodSync(artifact, 0o755);
      if (fileDigest(artifact) !== adapter.executableDigest) {
        throw new BootstrapFailure("capability_changed", [
          {
            code: "CAPABILITY_CHANGED",
            capability: adapter.name,
            expected: adapter.executableDigest,
            observed: fileDigest(artifact),
            message: `${adapter.name} changed while bootstrap was materialising it`,
            action: "retry bootstrap with a stable catalogue-owned capability",
          },
        ]);
      }
    }
    const adapterPath = artifacts;
    const adapters = discovered.map((adapter): ResolvedAdapter => {
      const launcherRelative = posix.join(stateKey, "bin", adapter.name);
      const launcher = resolve(bin, adapter.name);
      const artifactRelative = posix.join(stateKey, "artifacts", adapter.name);
      const finalArtifact = resolve(stateRoot, artifactRelative);
      const verified = probe(
        contracts.find((contract) => contract.name === adapter.name)!,
        resolve(artifacts, adapter.name),
        adapter.version,
        adapterPath,
      );
      const bytes = `#!/bin/sh\nset -eu\nPATH=${shellQuote(resolve(stateRoot, stateKey, "artifacts"))}\nexport PATH\nexec ${shellQuote(finalArtifact)} "$@"\n`;
      writeAtomicExecutable(launcher, bytes);
      const launcherDigest = bytesDigest(bytes);
      return {
        name: adapter.name,
        version: adapter.version,
        executableDigest: verified.executableDigest,
        artifact: artifactRelative,
        launcher: launcherRelative,
        launcherDigest,
        adapterDigest: digest({
          name: adapter.name,
          version: adapter.version,
          executableDigest: adapter.executableDigest,
          launcherDigest,
        }),
      };
    });
    const state: BootstrapState = {
      schema: "tc.sdlc/bootstrap-state/v1",
      release,
      lockDigest,
      platform: host.platform,
      architecture: host.architecture,
      adapters,
    };
    writeCanonicalEvidence(resolve(staging, "state.json"), state);
    renameSync(staging, directory);
    return adapters;
  } catch (error) {
    rmSync(staging, { recursive: true, force: true });
    throw error;
  }
}

function validateWarmState(
  stateRoot: string,
  stateKey: string,
  release: string,
  lockDigest: string,
  host: BootstrapHost,
  declaration: SdlcDeclaration,
): readonly ResolvedAdapter[] | null {
  const statePath = resolve(stateRoot, stateKey, "state.json");
  rejectSymlinkComponents(stateRoot, statePath);
  if (!existsSync(statePath)) {
    if (existsSync(dirname(statePath))) {
      throw new BootstrapFailure("state_corrupt", [
        {
          code: "BOOTSTRAP_STATE_PARTIAL",
          message: "release state exists without a valid immutable manifest",
          action: "discard the partial release state and bootstrap online again",
        },
      ]);
    }
    return null;
  }
  try {
    if (lstatSync(statePath).isSymbolicLink()) {
      throw new Error("state manifest symlink");
    }
    const state = readCanonical(statePath) as BootstrapState;
    if (
      state.schema !== "tc.sdlc/bootstrap-state/v1" ||
      state.release !== release ||
      state.lockDigest !== lockDigest ||
      state.platform !== host.platform ||
      state.architecture !== host.architecture ||
      !Array.isArray(state.adapters) ||
      state.adapters.length !== contracts.length
    ) {
      throw new Error("state bindings mismatch");
    }
    const adapterPath = resolve(stateRoot, stateKey, "artifacts");
    for (const [index, contract] of contracts.entries()) {
      const adapter = state.adapters[index];
      if (
        adapter === undefined ||
        adapter.name !== contract.name ||
        adapter.version !== contract.expected(declaration) ||
        adapter.artifact !== posix.join(stateKey, "artifacts", adapter.name) ||
        adapter.launcher !== posix.join(stateKey, "bin", adapter.name)
      ) {
        throw new Error("adapter bindings mismatch");
      }
      const launcher = resolve(stateRoot, adapter.launcher);
      const artifact = resolve(stateRoot, adapter.artifact);
      rejectSymlinkComponents(stateRoot, launcher);
      rejectSymlinkComponents(stateRoot, artifact);
      if (
        !existsSync(launcher) ||
        lstatSync(launcher).isSymbolicLink() ||
        !lstatSync(launcher).isFile() ||
        fileDigest(launcher) !== adapter.launcherDigest ||
        !existsSync(artifact) ||
        lstatSync(artifact).isSymbolicLink() ||
        !lstatSync(artifact).isFile() ||
        fileDigest(artifact) !== adapter.executableDigest
      ) {
        throw new Error("adapter artifact mismatch");
      }
      const observed = probe(
        contract,
        artifact,
        adapter.version,
        adapterPath,
      );
      if (observed.executableDigest !== adapter.executableDigest) {
        throw new Error("adapter executable changed");
      }
      if (
        adapter.adapterDigest !==
        digest({
          name: adapter.name,
          version: adapter.version,
          executableDigest: adapter.executableDigest,
          launcherDigest: adapter.launcherDigest,
        })
      ) {
        throw new Error("adapter digest mismatch");
      }
    }
    return state.adapters;
  } catch {
    throw new BootstrapFailure("state_corrupt", [
      {
        code: "BOOTSTRAP_STATE_CORRUPT",
        message: "warm bootstrap state does not match its immutable bindings",
        action: "discard the corrupt release state and bootstrap online again",
      },
    ]);
  }
}

function normalHost(value: BootstrapOptions["host"]): BootstrapHost {
  const platform = value?.platform ?? process.platform;
  if (platform !== "darwin" && platform !== "linux") {
    throw new BootstrapFailure("platform_unsupported", [
      {
        code: "PLATFORM_UNSUPPORTED",
        message: `native bootstrap does not support ${platform}`,
        action: "use a supported macOS or Linux host or the canonical image",
      },
    ]);
  }
  return {
    platform,
    architecture: value?.architecture ?? process.arch,
    path: value?.path ?? process.env.PATH ?? "",
    offline: value?.offline ?? false,
  };
}

function failureReason(error: unknown): Readonly<{
  reason: string;
  diagnostics: readonly BootstrapDiagnostic[];
}> {
  if (error instanceof BootstrapFailure) {
    return error;
  }
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
        message: error instanceof Error ? error.message : String(error),
        action: "correct the reported bootstrap failure and retry",
      },
    ],
  };
}

export function serialiseBootstrapReceipt(receipt: BootstrapReceipt): string {
  return canonicalJson(receipt);
}

export async function bootstrap(options: BootstrapOptions): Promise<BootstrapReceipt> {
  const maximumDiagnostics = options.maxDiagnostics ?? 20;
  if (!Number.isSafeInteger(maximumDiagnostics) || maximumDiagnostics < 1) {
    throw new TypeError("maxDiagnostics must be a positive safe integer");
  }
  let host: BootstrapHost;
  try {
    host = normalHost(options.host);
  } catch (error) {
    const fallbackPlatform = process.platform === "linux" ? "linux" : "darwin";
    host = {
      platform: fallbackPlatform,
      architecture: options.host?.architecture ?? process.arch,
      path: options.host?.path ?? "",
      offline: options.host?.offline ?? false,
    };
    const failure = failureReason(error);
    const receipt = failedReceipt(options, host, "unresolved", false, [], [], failure, maximumDiagnostics);
    writeCanonicalEvidence(options.receiptPath, receipt);
    return receipt;
  }
  const lockDigest = digest(options.lock);
  const stateKey = posix.join(
    "releases",
    lockDigest.slice("sha256:".length),
    `${host.platform}-${host.architecture}`,
  );
  let reused = false;
  let taskIdentities: readonly string[] = [];
  let adapters: readonly BootstrapAdapterEvidence[] = [];
  try {
    assertCurrentLock(options.lock, options.declaration, options.catalogue);
    const inventory = resolveInputInventory(options.root, options.declaration);
    const bound = bindGraphLock(
      options.declaration,
      options.lock,
      options.catalogue,
      inventory,
    );
    taskIdentities = buildGraph(options.declaration, bound).tasks.map(
      (task) => task.identity,
    );
    const stateRoot = validateStateRoot(options.root, options.stateRoot);
    const ownership = inspectOwnership(stateRoot);
    if (ownership === "owned") {
      const warm = validateWarmState(
        stateRoot,
        stateKey,
        options.catalogue.release.version,
        lockDigest,
        host,
        options.declaration,
      );
      if (warm !== null) {
        reused = true;
        adapters = warm.map(adapterEvidence);
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
      const discovered = discoverAdapters(options.declaration, host);
      mkdirSync(stateRoot, { recursive: true, mode: 0o700 });
      chmodSync(stateRoot, 0o700);
      if (ownership === "absent") {
        writeCanonicalEvidence(join(stateRoot, ".tc-sdlc-owner.json"), OWNER);
      }
      adapters = materializeAdapters(
        stateRoot,
        stateKey,
        options.catalogue.release.version,
        lockDigest,
        host,
        discovered,
      ).map(adapterEvidence);
    }
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
      diagnostics: [],
      diagnosticsCount: 0,
      diagnosticsTruncated: false,
    };
    writeCanonicalEvidence(options.receiptPath, receipt);
    return receipt;
  } catch (error) {
    const failure = failureReason(error);
    const receipt = failedReceipt(
      options,
      host,
      stateKey,
      reused,
      taskIdentities,
      adapters,
      failure,
      maximumDiagnostics,
    );
    writeCanonicalEvidence(options.receiptPath, receipt);
    return receipt;
  }
}

function failedReceipt(
  options: BootstrapOptions,
  host: BootstrapHost,
  stateKey: string,
  reused: boolean,
  taskIdentities: readonly string[],
  adapters: readonly BootstrapAdapterEvidence[],
  failure: Readonly<{
    reason: string;
    diagnostics: readonly BootstrapDiagnostic[];
  }>,
  maximumDiagnostics: number,
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
    diagnostics: failure.diagnostics.slice(0, maximumDiagnostics),
    diagnosticsCount: failure.diagnostics.length,
    diagnosticsTruncated: failure.diagnostics.length > maximumDiagnostics,
  };
}
