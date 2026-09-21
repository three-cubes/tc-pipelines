import { createHash } from "node:crypto";
import {
  existsSync,
  lstatSync,
  readFileSync,
  realpathSync,
  readlinkSync,
  readdirSync,
} from "node:fs";
import { dirname, join, posix, relative, resolve, sep } from "node:path";

import { canonicalJson, digest } from "../canonical.js";
import { SdlcError } from "../errors.js";
import type { ReleaseCatalogue, SdlcLock } from "../schema/types.js";
import { acquireBootstrapExecutionLease, type BootstrapExecutionLease } from "./execution-lease.js";
import type {
  BootstrapAdapterEvidence,
  BootstrapCapabilityName,
  BootstrapContextBinding,
  BootstrapExecutionContext,
  BootstrapReceipt,
} from "./index.js";

type ResolvedAdapter = BootstrapAdapterEvidence & Readonly<{ executable: string }>;
type DependencyEvidence = BootstrapReceipt["dependencies"][number];
type BootstrapState = Readonly<{
  schema: "tc.sdlc/bootstrap-state/v6";
  release: string;
  platform: "darwin" | "linux";
  architecture: string;
  lockDigest: string;
  dependencyDigest: string;
  adapters: readonly ResolvedAdapter[];
  dependencies: readonly DependencyEvidence[];
}>;

const OWNER = { schema: "tc.sdlc/state-owner/v1", owner: "@three-cubes/tc-sdlc" } as const;
const adapterNames: readonly BootstrapCapabilityName[] = ["node", "pnpm", "python", "uv"];

function bytesDigest(path: string): string {
  return `sha256:${createHash("sha256").update(readFileSync(path)).digest("hex")}`;
}

function readCanonical(path: string): unknown {
  const bytes = readFileSync(path, "utf8");
  const value = JSON.parse(bytes) as unknown;
  if (bytes !== canonicalJson(value)) throw new Error("managed evidence is not canonical");
  return value;
}

function rejectLinkedPath(root: string, target: string): void {
  const suffix = relative(root, target);
  if (suffix === "" || suffix === ".." || suffix.startsWith(`..${sep}`)) {
    throw new Error("managed state path escapes its owned root");
  }
  let cursor = root;
  for (const segment of suffix.split(sep)) {
    cursor = join(cursor, segment);
    if (existsSync(cursor) && lstatSync(cursor).isSymbolicLink()) {
      throw new Error("managed release state may not traverse symbolic links");
    }
  }
}

function isPythonRuntimeCache(path: string): boolean {
  const segments = path.split("/");
  const name = segments.at(-1) ?? "";
  return segments.includes("__pycache__") || name.endsWith(".pyc") || name.endsWith(".pyo");
}

function directoryDigest(root: string, ignorePythonRuntimeCache = false): string {
  const rootMetadata = lstatSync(root);
  if (!rootMetadata.isDirectory() || rootMetadata.isSymbolicLink()) {
    throw new Error("dependency environment is not a real directory");
  }
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
        entries.push({ path: relativePath, type: "directory", mode: metadata.mode & 0o7777 });
        visit(path, relativePath);
      } else if (metadata.isFile()) {
        entries.push({ path: relativePath, type: "file", mode: metadata.mode & 0o7777, digest: bytesDigest(path) });
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

function executableDigest(adapter: ResolvedAdapter): string {
  if (adapter.name === "pnpm" && adapter.provider === "catalogue-distribution") {
    return directoryDigest(dirname(dirname(adapter.executable)));
  }
  return bytesDigest(adapter.executable);
}

function adapterEvidence(adapter: ResolvedAdapter): BootstrapAdapterEvidence {
  const { executable: _executable, ...evidence } = adapter;
  return evidence;
}

/** Resolve a verified bootstrap receipt into the only PATH/runtime accepted by public tasks. */
export function loadBootstrapExecutionContext(
  receiptPath: string,
  stateRootValue: string,
  lock: SdlcLock,
  catalogue: ReleaseCatalogue,
): BootstrapExecutionContext {
  let lease: BootstrapExecutionLease | undefined;
  try {
    const receiptBytes = readFileSync(receiptPath, "utf8");
    const receipt = JSON.parse(receiptBytes) as BootstrapReceipt;
    if (receiptBytes !== canonicalJson(receipt)) throw new Error("bootstrap receipt is not canonical");
    if (
      receipt.schema !== "tc.sdlc/bootstrap-receipt/v1" ||
      receipt.status !== "succeeded" ||
      receipt.release !== catalogue.release.version ||
      receipt.lockDigest !== digest(lock) ||
      !/^sha256:[0-9a-f]{64}$/.test(receipt.stateDigest ?? "") ||
      !Array.isArray(receipt.adapters) ||
      !Array.isArray(receipt.dependencies)
    ) {
      throw new Error("bootstrap receipt is not bound to the supplied release lock");
    }

    const stateRoot = resolve(stateRootValue);
    const canonicalRoot = realpathSync(stateRoot);
    const rootMetadata = lstatSync(canonicalRoot);
    if (!rootMetadata.isDirectory() || rootMetadata.isSymbolicLink()) {
      throw new Error("bootstrap state root is not a real directory");
    }
    if (canonicalJson(readCanonical(join(canonicalRoot, ".tc-sdlc-owner.json"))) !== canonicalJson(OWNER)) {
      throw new Error("bootstrap state root is not owned by tc-sdlc");
    }
    if (
      typeof receipt.stateKey !== "string" ||
      receipt.stateKey.length === 0 ||
      posix.isAbsolute(receipt.stateKey) ||
      receipt.stateKey.split("/").some((part) => part === "" || part === "." || part === "..")
    ) {
      throw new Error("bootstrap state key is unsafe");
    }
    lease = acquireBootstrapExecutionLease(stateRoot, receipt.stateKey);
    lease.assertCurrent();
    const stateDirectory = resolve(canonicalRoot, receipt.stateKey);
    rejectLinkedPath(canonicalRoot, stateDirectory);
    const statePath = join(stateDirectory, "state.json");
    rejectLinkedPath(canonicalRoot, statePath);
    if (bytesDigest(statePath) !== receipt.stateDigest) {
      throw new Error("bootstrap state digest does not match its receipt");
    }
    const state = readCanonical(statePath) as BootstrapState;
    if (
      state.schema !== "tc.sdlc/bootstrap-state/v6" ||
      state.release !== receipt.release ||
      state.platform !== receipt.platform ||
      state.architecture !== receipt.architecture ||
      state.lockDigest !== receipt.lockDigest ||
      !Array.isArray(state.adapters) ||
      !Array.isArray(state.dependencies) ||
      canonicalJson(state.adapters.map(adapterEvidence)) !== canonicalJson(receipt.adapters) ||
      canonicalJson(state.dependencies) !== canonicalJson(receipt.dependencies)
    ) {
      throw new Error("bootstrap state identity differs from its receipt");
    }
    const expectedPlatform = process.platform === "linux" ? "linux" : "darwin";
    if (
      receipt.platform !== expectedPlatform ||
      receipt.architecture !== process.arch
    ) {
      throw new Error("bootstrap receipt belongs to a different platform or architecture");
    }

    const versions: Readonly<Record<BootstrapCapabilityName, string>> = {
      node: lock.toolchains.node!,
      pnpm: lock.toolchains.packageManager!.replace(/^pnpm@/, ""),
      python: lock.toolchains.python!,
      uv: lock.toolchains.uv!,
    };
    if (state.adapters.length !== adapterNames.length) {
      throw new Error("bootstrap state does not provide every catalogue adapter");
    }
    const adapterDirectories: string[] = [];
    const validatedAdapters: Array<{
      launcherPath: string;
      executablePath: string;
      adapter: ResolvedAdapter;
    }> = [];
    for (const [index, name] of adapterNames.entries()) {
      const adapter = state.adapters[index];
      if (
        adapter === undefined ||
        adapter.name !== name ||
        adapter.version !== versions[name] ||
        !providerAllowed(name, adapter.provider) ||
        adapter.launcher !== posix.join(receipt.stateKey, "bin", adapter.name)
      ) {
        throw new Error("bootstrap adapter does not match the release toolchain lock");
      }
      const launcherPath = resolve(canonicalRoot, adapter.launcher);
      rejectLinkedPath(canonicalRoot, launcherPath);
      const launcherMetadata = lstatSync(launcherPath);
      const executableMetadata = lstatSync(adapter.executable);
      if (
        !launcherMetadata.isFile() || launcherMetadata.isSymbolicLink() ||
        !executableMetadata.isFile() || executableMetadata.isSymbolicLink() ||
        bytesDigest(launcherPath) !== adapter.launcherDigest ||
        executableDigest(adapter) !== adapter.executableDigest ||
        adapter.adapterDigest !== digest({
          name: adapter.name,
          version: adapter.version,
          provider: adapter.provider,
          executableDigest: adapter.executableDigest,
          launcherDigest: adapter.launcherDigest,
        })
      ) {
        throw new Error("bootstrap adapter artifact is missing or changed");
      }
      adapterDirectories.push(dirname(launcherPath));
      validatedAdapters.push({ launcherPath, executablePath: adapter.executable, adapter });
    }

    const bindings = state.dependencies.map(({ installedDigest: _installedDigest, ...binding }) => binding);
    if (state.dependencyDigest !== digest(bindings)) {
      throw new Error("bootstrap dependency bindings do not match state identity");
    }
    const dependencyPaths = new Map<string, string>();
    const validatedDependencies: Array<{
      manager: "pnpm" | "uv";
      path: string;
      digest: string;
    }> = [];
    for (const dependency of state.dependencies) {
      if (
        (dependency.manager !== "pnpm" && dependency.manager !== "uv") ||
        !/^dependencies\/[a-z0-9-]+$/.test(dependency.environment)
      ) {
        throw new Error("bootstrap dependency environment path is invalid");
      }
      const environmentPath = resolve(stateDirectory, dependency.environment);
      rejectLinkedPath(canonicalRoot, environmentPath);
      if (
        !/^sha256:[0-9a-f]{64}$/.test(dependency.installedDigest ?? "") ||
        installedEnvironmentDigest(dependency.manager, environmentPath) !== dependency.installedDigest
      ) {
        throw new Error("bootstrap dependency environment is missing or changed");
      }
      dependencyPaths.set(dependency.manager, environmentPath);
      validatedDependencies.push({
        manager: dependency.manager,
        path: environmentPath,
        digest: dependency.installedDigest!,
      });
    }

    const uvEnvironment = dependencyPaths.get("uv");
    const pnpmEnvironment = dependencyPaths.get("pnpm");
    const toolPath = [
      ...(uvEnvironment === undefined ? [] : [join(uvEnvironment, "bin")]),
      ...(pnpmEnvironment === undefined ? [] : [join(pnpmEnvironment, "node_modules", ".bin")]),
      ...adapterDirectories,
      ...(process.platform === "darwin"
        ? ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
        : ["/usr/local/bin", "/usr/bin", "/bin"]),
    ].join(":");
    const binding: BootstrapContextBinding = {
      schema: "tc.sdlc/execution-context/v1",
      release: receipt.release,
      platform: receipt.platform,
      architecture: receipt.architecture,
      lockDigest: receipt.lockDigest,
      stateKey: receipt.stateKey,
      bootstrapReceiptDigest: bytesDigest(receiptPath),
      stateDigest: receipt.stateDigest,
      dependencyDigest: state.dependencyDigest,
      fitness: lock.fitness,
      adapters: state.adapters.map((adapter) => ({
        name: adapter.name,
        version: adapter.version,
        adapterDigest: adapter.adapterDigest,
      })),
    };
    const environment: Record<string, string> = {
      PATH: toolPath,
      TC_SDLC_EXECUTION_CONTEXT_DIGEST: digest(binding),
      TC_SDLC_BOOTSTRAP_STATE_KEY: receipt.stateKey,
      TC_SDLC_FITNESS_VERSION: lock.fitness.version,
    };
    if (uvEnvironment !== undefined) {
      environment.VIRTUAL_ENV = uvEnvironment;
      environment.UV_PROJECT_ENVIRONMENT = uvEnvironment;
    }
    const verifyIntegrity = (): void => {
      lease!.assertCurrent();
      if (bytesDigest(statePath) !== receipt.stateDigest) {
        throw new SdlcError("BOOTSTRAP_STATE_CHANGED", "bootstrap state metadata changed during task execution");
      }
      for (const entry of validatedAdapters) {
        rejectLinkedPath(canonicalRoot, entry.launcherPath);
        if (bytesDigest(entry.launcherPath) !== entry.adapter.launcherDigest ||
            executableDigest(entry.adapter) !== entry.adapter.executableDigest) {
          throw new SdlcError("BOOTSTRAP_STATE_CHANGED", "bootstrap adapter changed during task execution");
        }
      }
      for (const dependency of validatedDependencies) {
        if (installedEnvironmentDigest(dependency.manager, dependency.path) !== dependency.digest) {
          throw new SdlcError("BOOTSTRAP_STATE_CHANGED", "bootstrap dependency environment changed during task execution");
        }
      }
      lease!.assertCurrent();
    };
    verifyIntegrity();
    return {
      binding,
      stateRoot: canonicalRoot,
      stateDirectory,
      environment,
      lease,
      verifyIntegrity,
    };
  } catch (error) {
    lease?.release();
    throw new SdlcError(
      "BOOTSTRAP_CONTEXT_INVALID",
      `bootstrap receipt/state is invalid: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}

function providerAllowed(
  name: BootstrapCapabilityName,
  provider: BootstrapAdapterEvidence["provider"],
): boolean {
  const allowed: Readonly<Record<BootstrapCapabilityName, readonly BootstrapAdapterEvidence["provider"][]>> = {
    node: ["homebrew", "canonical-image", "catalogue-distribution"],
    pnpm: ["catalogue-distribution", "canonical-image"],
    python: ["homebrew", "canonical-image", "catalogue-distribution"],
    uv: ["catalogue-distribution", "canonical-image"],
  };
  return allowed[name].includes(provider);
}
