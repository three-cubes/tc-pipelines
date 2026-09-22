import { spawnSync } from "node:child_process";
import { existsSync, lstatSync, mkdirSync, readdirSync } from "node:fs";
import { isAbsolute, join } from "node:path";

import type {
  MaintenanceOptions,
  MaintenanceReceipt,
  MaintenanceToolReceipt,
} from "./types.js";

function directoryBytes(path: string): number {
  let total = 0;
  for (const entry of readdirSync(path, { withFileTypes: true })) {
    const child = join(path, entry.name);
    if (entry.isSymbolicLink()) total += lstatSync(child).size;
    else if (entry.isDirectory()) total += directoryBytes(child);
    else total += lstatSync(child).size;
  }
  return total;
}

function cacheBytes(path: string): number {
  try {
    const details = lstatSync(path);
    return details.isDirectory() && !details.isSymbolicLink() ? directoryBytes(path) : 0;
  } catch {
    return 0;
  }
}

export function validateExecutable(path: string | undefined): boolean {
  if (path === undefined) return false;
  try {
    const details = lstatSync(path);
    return (
      isAbsolute(path) &&
      details.isFile() &&
      !details.isSymbolicLink() &&
      (details.mode & 0o111) !== 0
    );
  } catch {
    return false;
  }
}

function ownedDirectory(
  stateRoot: string,
  segments: readonly string[],
  create: boolean,
): string | undefined {
  let current = stateRoot;
  try {
    for (const segment of segments) {
      current = join(current, segment);
      if (existsSync(current) && lstatSync(current).isSymbolicLink()) return undefined;
    }
    if (create) mkdirSync(current, { recursive: true, mode: 0o700 });
    return current;
  } catch {
    return undefined;
  }
}

function pruneUv(options: MaintenanceOptions, stateRoot: string): MaintenanceToolReceipt {
  if (options.uvExecutable === undefined) return { status: "not_requested", reclaimedBytes: 0 };
  if (!validateExecutable(options.uvExecutable)) {
    return { status: "failed", reclaimedBytes: 0, detail: "uv_executable_invalid" };
  }
  const cache = ownedDirectory(stateRoot, ["cache", "uv"], options.mode === "apply");
  if (cache === undefined) {
    return { status: "failed", reclaimedBytes: 0, detail: "uv_cache_unowned" };
  }
  if (options.mode === "dry-run") return { status: "planned", reclaimedBytes: 0 };
  const before = cacheBytes(cache);
  const result = spawnSync(options.uvExecutable, ["cache", "prune", "--cache-dir", cache], {
    encoding: "utf8",
    timeout: 120_000,
    env: { ...process.env, UV_CACHE_DIR: cache, UV_NO_CONFIG: "1" },
  });
  if (result.status !== 0) {
    return { status: "failed", reclaimedBytes: 0, detail: "uv_prune_failed" };
  }
  return { status: "pruned", reclaimedBytes: Math.max(0, before - cacheBytes(cache)) };
}

function prunePnpm(options: MaintenanceOptions, stateRoot: string): MaintenanceToolReceipt {
  if (options.pnpmExecutable === undefined) {
    return { status: "not_requested", reclaimedBytes: 0 };
  }
  if (!validateExecutable(options.pnpmExecutable)) {
    return { status: "failed", reclaimedBytes: 0, detail: "pnpm_executable_invalid" };
  }
  const cache = ownedDirectory(stateRoot, ["cache", "pnpm"], options.mode === "apply");
  if (cache === undefined) {
    return { status: "failed", reclaimedBytes: 0, detail: "pnpm_cache_unowned" };
  }
  if (options.mode === "dry-run") return { status: "planned", reclaimedBytes: 0 };
  const before = cacheBytes(cache);
  const home = ownedDirectory(stateRoot, ["maintenance", "pnpm-home"], true);
  if (home === undefined) {
    return { status: "failed", reclaimedBytes: 0, detail: "pnpm_home_unowned" };
  }
  const result = spawnSync(options.pnpmExecutable, ["store", "prune", "--store-dir", cache], {
    encoding: "utf8",
    timeout: 120_000,
    env: {
      ...process.env,
      HOME: home,
      XDG_CACHE_HOME: join(stateRoot, "cache"),
      COREPACK_HOME: join(stateRoot, "maintenance", "corepack"),
      COREPACK_ENABLE_NETWORK: "0",
    },
  });
  if (result.status !== 0) {
    return { status: "failed", reclaimedBytes: 0, detail: "pnpm_prune_failed" };
  }
  return { status: "pruned", reclaimedBytes: Math.max(0, before - cacheBytes(cache)) };
}

function parseByteSize(value: string): number | undefined {
  const match = /^([0-9]+(?:\.[0-9]+)?)(B|kB|MB|GB|TB|KiB|MiB|GiB|TiB)$/.exec(value);
  if (match === null) return undefined;
  const amount = Number(match[1]);
  const factors: Readonly<Record<string, number>> = {
    B: 1,
    kB: 1_000,
    MB: 1_000_000,
    GB: 1_000_000_000,
    TB: 1_000_000_000_000,
    KiB: 1_024,
    MiB: 1_048_576,
    GiB: 1_073_741_824,
    TiB: 1_099_511_627_776,
  };
  return Number.isFinite(amount) ? Math.round(amount * factors[match[2]!]!) : undefined;
}

function buildkitBytes(
  executable: string,
  builder: string,
  environment: NodeJS.ProcessEnv,
): number | undefined {
  const result = spawnSync(executable, ["du", "--builder", builder, "--format", "json"], {
    encoding: "utf8",
    timeout: 120_000,
    env: environment,
  });
  if (result.status !== 0) return undefined;
  let total = 0;
  try {
    for (const line of result.stdout.split("\n").filter(Boolean)) {
      const item = JSON.parse(line) as { Size?: unknown };
      if (typeof item.Size !== "string") return undefined;
      const size = parseByteSize(item.Size);
      if (size === undefined) return undefined;
      total += size;
    }
    return total;
  } catch {
    return undefined;
  }
}

function ownedDockerEnvironment(dockerConfig: string): NodeJS.ProcessEnv {
  const environment: NodeJS.ProcessEnv = { ...process.env, DOCKER_CONFIG: dockerConfig };
  for (const name of [
    "BUILDX_CONFIG",
    "BUILDER_NODE",
    "BUILDKIT_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_HOST",
    "DOCKER_CERT_PATH",
    "DOCKER_TLS_VERIFY",
  ]) delete environment[name];
  return environment;
}

function pruneBuildkit(
  options: MaintenanceOptions,
  stateRoot: string,
  retentionHours: number,
): MaintenanceToolReceipt {
  if (options.dockerBuilder === undefined) {
    return { status: "not_requested", reclaimedBytes: 0 };
  }
  if (!/^tc-sdlc-[a-zA-Z0-9_.-]+$/.test(options.dockerBuilder)) {
    return { status: "failed", reclaimedBytes: 0, detail: "docker_builder_unowned" };
  }
  if (options.mode === "dry-run") return { status: "planned", reclaimedBytes: 0 };
  if (!validateExecutable(options.buildxExecutable)) {
    return { status: "failed", reclaimedBytes: 0, detail: "buildx_executable_invalid" };
  }
  const dockerConfig = ownedDirectory(stateRoot, ["cache", "docker"], true);
  if (dockerConfig === undefined) {
    return { status: "failed", reclaimedBytes: 0, detail: "docker_config_unowned" };
  }
  const environment = ownedDockerEnvironment(dockerConfig);
  const before = buildkitBytes(options.buildxExecutable!, options.dockerBuilder, environment);
  const result = spawnSync(
    options.buildxExecutable!,
    [
      "prune",
      "--builder",
      options.dockerBuilder,
      "--filter",
      `until=${retentionHours}h`,
      "--force",
    ],
    { encoding: "utf8", timeout: 120_000, env: environment },
  );
  if (result.status !== 0) {
    return { status: "failed", reclaimedBytes: 0, detail: "buildkit_prune_failed" };
  }
  const after = buildkitBytes(options.buildxExecutable!, options.dockerBuilder, environment);
  return {
    status: "pruned",
    reclaimedBytes:
      before === undefined || after === undefined ? 0 : Math.max(0, before - after),
  };
}

export function pruneManagedTools(
  options: MaintenanceOptions,
  stateRoot: string,
  retentionHours: number,
): Readonly<{
  tools: MaintenanceReceipt["tools"];
  reclaimedBytes: number;
  failureReason: string | null;
}> {
  const uv = pruneUv(options, stateRoot);
  const pnpm = prunePnpm(options, stateRoot);
  const buildkit = pruneBuildkit(options, stateRoot, retentionHours);
  const reclaimedBytes = uv.reclaimedBytes + pnpm.reclaimedBytes + buildkit.reclaimedBytes;
  const failure = [uv, pnpm, buildkit].find((tool) => tool.status === "failed");
  return { tools: { uv, pnpm, buildkit }, reclaimedBytes, failureReason: failure?.detail ?? null };
}
