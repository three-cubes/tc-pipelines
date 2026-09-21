import { spawnSync } from "node:child_process";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  readFileSync,
} from "node:fs";
import { rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";

import { canonicalJson } from "../canonical.js";
import { writeCanonicalEvidence } from "../evidence/index.js";

const OWNER = { schema: "tc.sdlc/state-owner/v1", owner: "@three-cubes/tc-sdlc" } as const;
const TEMPORARY_OWNER = "@three-cubes/tc-sdlc";
const TEMPORARY_SCHEMA = "tc.sdlc/temporary-owner/v1";
const TEMPORARY_PREFIX = "tc-sdlc-";
const TEMPORARY_KINDS = new Set(["evaluation-workspace", "test-run"]);
const DEFAULT_RETENTION_HOURS = 48;
const DEFAULT_CLEANUP_WORKERS = 4;
const MAX_CLEANUP_WORKERS = 16;
const MAX_ENTRIES = 256;
const SYSTEM_GIT = "/usr/bin/git";

export type MaintenanceMode = "dry-run" | "apply";

export type MaintenanceOptions = Readonly<{
  stateRoot: string;
  receiptPath: string;
  mode: MaintenanceMode;
  temporaryRoot?: string;
  retentionHours?: number;
  uvExecutable?: string;
  buildxExecutable?: string;
  dockerBuilder?: string;
  maxEntries?: number;
  cleanupWorkers?: number;
}>;

export type MaintenanceEntry = Readonly<{
  kind: "temporary";
  path: string;
  bytes?: number;
}>;

export type MaintenanceRetainedEntry = Readonly<{
  path: string;
  reason:
    | "active"
    | "dirty_worktree"
    | "retention_window"
    | "foreign"
    | "linked"
    | "changed_during_apply"
    | "inspection_failed";
}>;

export type MaintenanceToolReceipt = Readonly<{
  status: "not_requested" | "planned" | "pruned" | "failed";
  reclaimedBytes: number;
  detail?: string;
}>;

export type MaintenanceReceipt = Readonly<{
  schema: "tc.sdlc/maintenance-receipt/v1";
  status: "succeeded" | "failed";
  reason: string | null;
  mode: MaintenanceMode;
  platform: NodeJS.Platform;
  stateRoot: string;
  temporaryRoot: string;
  retentionHours: number;
  candidateCount: number;
  removedCount: number;
  reclaimedBytes: number;
  entriesTruncated: boolean;
  cleanupWorkers: number;
  cleanupFailures: number;
  candidates: readonly MaintenanceEntry[];
  retained: readonly MaintenanceRetainedEntry[];
  tools: Readonly<{
    uv: MaintenanceToolReceipt;
    buildkit: MaintenanceToolReceipt;
  }>;
}>;

type TemporaryMarker = Readonly<{
  schema: string;
  owner: string;
  kind: string;
  pid: number;
}>;

function receipt(
  options: MaintenanceOptions,
  values: Partial<MaintenanceReceipt>,
): MaintenanceReceipt {
  return {
    schema: "tc.sdlc/maintenance-receipt/v1",
    status: "succeeded",
    reason: null,
    mode: options.mode,
    platform: process.platform,
    stateRoot: resolve(options.stateRoot),
    temporaryRoot: resolve(options.temporaryRoot ?? tmpdir()),
    retentionHours: options.retentionHours ?? DEFAULT_RETENTION_HOURS,
    candidateCount: 0,
    removedCount: 0,
    reclaimedBytes: 0,
    entriesTruncated: false,
    cleanupWorkers: options.cleanupWorkers ?? DEFAULT_CLEANUP_WORKERS,
    cleanupFailures: 0,
    candidates: [],
    retained: [],
    tools: {
      uv: { status: "not_requested", reclaimedBytes: 0 },
      buildkit: { status: "not_requested", reclaimedBytes: 0 },
    },
    ...values,
  };
}

function writeReceipt(path: string, value: MaintenanceReceipt): MaintenanceReceipt {
  writeCanonicalEvidence(path, value);
  return value;
}

export function serialiseMaintenanceReceipt(receipt: MaintenanceReceipt): string {
  return canonicalJson(receipt);
}

function validOwner(stateRoot: string): boolean {
  try {
    const root = lstatSync(stateRoot);
    if (!root.isDirectory() || root.isSymbolicLink()) return false;
    const markerPath = join(stateRoot, ".tc-sdlc-owner.json");
    const marker = lstatSync(markerPath);
    if (!marker.isFile() || marker.isSymbolicLink()) return false;
    return canonicalJson(JSON.parse(readFileSync(markerPath, "utf8"))) === canonicalJson(OWNER);
  } catch {
    return false;
  }
}

function directoryBytes(path: string): number {
  let total = 0;
  for (const entry of readdirSync(path, { withFileTypes: true })) {
    const child = join(path, entry.name);
    if (entry.isSymbolicLink()) {
      total += lstatSync(child).size;
    } else if (entry.isDirectory()) {
      total += directoryBytes(child);
    } else {
      total += lstatSync(child).size;
    }
  }
  return total;
}

function processIsAlive(pid: number): boolean {
  if (!Number.isSafeInteger(pid) || pid <= 0) return true;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

function dirtyWorktree(path: string): boolean {
  if (!existsSync(join(path, ".git"))) return false;
  if (!validateExecutable(SYSTEM_GIT)) return true;
  const result = spawnSync(SYSTEM_GIT, ["status", "--porcelain", "--untracked-files=all"], {
    cwd: path,
    encoding: "utf8",
    timeout: 10_000,
  });
  if (result.status !== 0) return true;
  return result.stdout
    .split("\n")
    .filter(Boolean)
    .some((line) => line.slice(3) !== ".tc-sdlc-temporary.json");
}

function readTemporaryMarker(path: string): TemporaryMarker | undefined {
  try {
    const markerPath = join(path, ".tc-sdlc-temporary.json");
    const details = lstatSync(markerPath);
    if (!details.isFile() || details.isSymbolicLink()) return undefined;
    const marker = JSON.parse(readFileSync(markerPath, "utf8")) as TemporaryMarker;
    if (
      marker.schema !== TEMPORARY_SCHEMA ||
      marker.owner !== TEMPORARY_OWNER ||
      typeof marker.kind !== "string" ||
      !TEMPORARY_KINDS.has(marker.kind) ||
      !Number.isSafeInteger(marker.pid)
    ) {
      return undefined;
    }
    return marker;
  } catch {
    return undefined;
  }
}

function inspectTemporaryRoot(
  temporaryRoot: string,
  cutoff: number,
  maxEntries: number,
): Readonly<{
  candidates: MaintenanceEntry[];
  retained: MaintenanceRetainedEntry[];
  truncated: boolean;
}> {
  const candidates: MaintenanceEntry[] = [];
  const retained: MaintenanceRetainedEntry[] = [];
  let truncated = false;
  let entries: string[];
  try {
    const root = lstatSync(temporaryRoot);
    if (!root.isDirectory() || root.isSymbolicLink()) {
      return { candidates, retained, truncated };
    }
    entries = readdirSync(temporaryRoot).sort();
  } catch {
    return { candidates, retained, truncated };
  }
  for (const name of entries) {
    if (!name.startsWith(TEMPORARY_PREFIX)) {
      continue;
    }
    if (candidates.length + retained.length >= maxEntries) {
      truncated = true;
      continue;
    }
    const path = join(temporaryRoot, name);
    try {
      const details = lstatSync(path);
      if (details.isSymbolicLink()) {
        retained.push({ path: name, reason: "linked" });
        continue;
      }
      if (!details.isDirectory()) continue;
      const marker = readTemporaryMarker(path);
      if (marker === undefined) {
        retained.push({ path: name, reason: "foreign" });
        continue;
      }
      if (processIsAlive(marker.pid)) {
        retained.push({ path: name, reason: "active" });
        continue;
      }
      if (details.mtimeMs > cutoff) {
        retained.push({ path: name, reason: "retention_window" });
        continue;
      }
      if (dirtyWorktree(path)) {
        retained.push({ path: name, reason: "dirty_worktree" });
        continue;
      }
      candidates.push({ kind: "temporary", path: name, bytes: directoryBytes(path) });
    } catch {
      retained.push({ path: name, reason: "inspection_failed" });
    }
  }
  return { candidates, retained, truncated };
}

function stillEligible(path: string, cutoff: number): boolean {
  try {
    const details = lstatSync(path);
    const marker = readTemporaryMarker(path);
    return (
      details.isDirectory() &&
      !details.isSymbolicLink() &&
      marker !== undefined &&
      !processIsAlive(marker.pid) &&
      details.mtimeMs <= cutoff &&
      !dirtyWorktree(path)
    );
  } catch {
    return false;
  }
}

async function removeCandidates(
  temporaryRoot: string,
  candidates: readonly MaintenanceEntry[],
  cutoff: number,
  workers: number,
): Promise<Readonly<{
  removedCount: number;
  reclaimedBytes: number;
  failures: number;
  retained: MaintenanceRetainedEntry[];
}>> {
  const results: Array<
    | Readonly<{ removed: true; bytes: number }>
    | Readonly<{ removed: false; retained: MaintenanceRetainedEntry; failed: boolean }>
  > = new Array(candidates.length);
  let cursor = 0;
  const worker = async (): Promise<void> => {
    while (cursor < candidates.length) {
      const index = cursor;
      cursor += 1;
      const candidate = candidates[index]!;
      const path = join(temporaryRoot, candidate.path);
      if (!stillEligible(path, cutoff)) {
        results[index] = {
          removed: false,
          retained: { path: candidate.path, reason: "changed_during_apply" },
          failed: false,
        };
        continue;
      }
      try {
        // Independent owner roots are removed concurrently. File modes do not
        // need recursive chmod when their writable parent is owned by tc-sdlc.
        await rm(path, { recursive: true, force: false });
        results[index] = { removed: true, bytes: candidate.bytes ?? 0 };
      } catch {
        results[index] = {
          removed: false,
          retained: { path: candidate.path, reason: "inspection_failed" },
          failed: true,
        };
      }
    }
  };
  await Promise.all(
    Array.from({ length: Math.min(workers, candidates.length) }, () => worker()),
  );
  let removedCount = 0;
  let reclaimedBytes = 0;
  let failures = 0;
  const retained: MaintenanceRetainedEntry[] = [];
  for (const result of results) {
    if (result.removed) {
      removedCount += 1;
      reclaimedBytes += result.bytes;
    } else {
      retained.push(result.retained);
      if (result.failed) failures += 1;
    }
  }
  return { removedCount, reclaimedBytes, failures, retained };
}

function cacheBytes(path: string): number {
  try {
    const details = lstatSync(path);
    return details.isDirectory() && !details.isSymbolicLink() ? directoryBytes(path) : 0;
  } catch {
    return 0;
  }
}

function validateExecutable(path: string | undefined): boolean {
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
  const result = spawnSync(
    executable,
    ["du", "--builder", builder, "--format", "json"],
    { encoding: "utf8", timeout: 120_000, env: environment },
  );
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

function pruneBuildkit(
  options: MaintenanceOptions,
  stateRoot: string,
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
  const environment = { ...process.env, DOCKER_CONFIG: dockerConfig };
  const before = buildkitBytes(options.buildxExecutable!, options.dockerBuilder, environment);
  const result = spawnSync(
    options.buildxExecutable!,
    [
      "prune",
      "--builder",
      options.dockerBuilder,
      "--filter",
      `until=${options.retentionHours ?? DEFAULT_RETENTION_HOURS}h`,
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

export async function maintain(options: MaintenanceOptions): Promise<MaintenanceReceipt> {
  const retentionHours = options.retentionHours ?? DEFAULT_RETENTION_HOURS;
  const maxEntries = options.maxEntries ?? MAX_ENTRIES;
  const cleanupWorkers = options.cleanupWorkers ?? DEFAULT_CLEANUP_WORKERS;
  const temporaryRoot = resolve(options.temporaryRoot ?? tmpdir());
  const stateRoot = resolve(options.stateRoot);
  if (
    !isAbsolute(options.stateRoot) ||
    !isAbsolute(options.receiptPath) ||
    !Number.isFinite(retentionHours) ||
    retentionHours < 0 ||
    !Number.isSafeInteger(maxEntries) ||
    maxEntries <= 0 ||
    !Number.isSafeInteger(cleanupWorkers) ||
    cleanupWorkers <= 0 ||
    cleanupWorkers > MAX_CLEANUP_WORKERS ||
    (options.mode !== "dry-run" && options.mode !== "apply")
  ) {
    return writeReceipt(
      options.receiptPath,
      receipt(options, { status: "failed", reason: "invalid_options" }),
    );
  }
  if (!validOwner(stateRoot)) {
    return writeReceipt(
      options.receiptPath,
      receipt(options, { status: "failed", reason: "foreign_state" }),
    );
  }
  if (
    options.dockerBuilder !== undefined &&
    !/^tc-sdlc-[a-zA-Z0-9_.-]+$/.test(options.dockerBuilder)
  ) {
    return writeReceipt(
      options.receiptPath,
      receipt(options, { status: "failed", reason: "docker_builder_unowned" }),
    );
  }

  const cutoff = Date.now() - retentionHours * 60 * 60 * 1_000;
  const inspected = inspectTemporaryRoot(temporaryRoot, cutoff, maxEntries);
  let removedCount = 0;
  let reclaimedBytes = 0;
  let cleanupFailures = 0;
  if (options.mode === "apply") {
    const removal = await removeCandidates(
      temporaryRoot,
      inspected.candidates,
      cutoff,
      cleanupWorkers,
    );
    removedCount = removal.removedCount;
    reclaimedBytes = removal.reclaimedBytes;
    cleanupFailures = removal.failures;
    inspected.retained.push(...removal.retained);
  }

  const uv = pruneUv(options, stateRoot);
  const buildkit = pruneBuildkit(options, stateRoot);
  reclaimedBytes += uv.reclaimedBytes + buildkit.reclaimedBytes;
  const toolFailure = [uv, buildkit].find((tool) => tool.status === "failed");
  const failureReason =
    cleanupFailures > 0 ? "temporary_cleanup_failed" : toolFailure?.detail ?? null;
  return writeReceipt(
    options.receiptPath,
    receipt(options, {
      status: failureReason === null ? "succeeded" : "failed",
      reason: failureReason,
      candidateCount: inspected.candidates.length,
      removedCount,
      reclaimedBytes,
      entriesTruncated: inspected.truncated,
      cleanupWorkers,
      cleanupFailures,
      candidates: inspected.candidates,
      retained: inspected.retained,
      tools: { uv, buildkit },
    }),
  );
}
