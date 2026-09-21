import { spawnSync } from "node:child_process";
import {
  existsSync,
  lstatSync,
  readdirSync,
  readFileSync,
  renameSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import {
  QUARANTINE_PREFIX,
  DEFAULT_CLEANUP_WORKER_MS,
  createQuarantine,
  deleteQuarantineRoot,
  filesystemIdentity,
  finishQuarantine,
  inspectQuarantine,
  removeQuarantineCandidate,
  sameIdentity,
} from "./quarantine.js";
import { validateExecutable } from "./tools.js";
import type {
  AutomaticRecoveryReceipt,
  FilesystemIdentity,
  MaintenanceEntry,
  MaintenanceRetainedEntry,
} from "./types.js";

const OWNER = "@three-cubes/tc-sdlc";
const TEMPORARY_SCHEMA = "tc.sdlc/temporary-owner/v1";
const TEMPORARY_PREFIX = "tc-sdlc-";
const TEMPORARY_KINDS = new Set(["evaluation-workspace", "test-run"]);
export const DEFAULT_RETENTION_HOURS = 48;
export const DEFAULT_CLEANUP_WORKERS = 4;
export const MAX_ENTRIES = 256;
const SYSTEM_GIT = "/usr/bin/git";

type TemporaryMarker = Readonly<{
  schema: string;
  owner: string;
  kind: string;
  pid: number;
}>;

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

function processIsAlive(pid: number): boolean {
  if (!Number.isSafeInteger(pid) || pid <= 0) return true;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

function gitWorktrees(path: string): readonly string[] | undefined {
  const worktrees: string[] = [];
  for (const candidate of [path, join(path, "workspace")]) {
    try {
      if (!existsSync(candidate)) continue;
      const root = lstatSync(candidate);
      if (!root.isDirectory() || root.isSymbolicLink()) return undefined;
      const git = join(candidate, ".git");
      if (!existsSync(git)) continue;
      if (lstatSync(git).isSymbolicLink()) return undefined;
      worktrees.push(candidate);
    } catch {
      return undefined;
    }
  }
  return worktrees;
}

function isolatedGitEnvironment(): NodeJS.ProcessEnv {
  return {
    PATH: "/usr/bin:/bin",
    HOME: "/nonexistent/tc-sdlc-maintenance",
    LC_ALL: "C",
    GIT_CONFIG_NOSYSTEM: "1",
    GIT_CONFIG_GLOBAL: "/dev/null",
    GIT_OPTIONAL_LOCKS: "0",
  };
}

function dirtyWorktree(path: string): boolean {
  const worktrees = gitWorktrees(path);
  if (worktrees === undefined || !validateExecutable(SYSTEM_GIT)) return true;
  for (const worktree of worktrees) {
    const result = spawnSync(SYSTEM_GIT, [
      "-C",
      worktree,
      "status",
      "--porcelain",
      "--untracked-files=all",
    ], {
      encoding: "utf8",
      timeout: 10_000,
      env: isolatedGitEnvironment(),
    });
    if (result.status !== 0) return true;
    const dirty = result.stdout
      .split("\n")
      .filter(Boolean)
      .some((line) => worktree !== path || line.slice(3) !== ".tc-sdlc-temporary.json");
    if (dirty) return true;
  }
  return false;
}

function readTemporaryMarker(path: string): TemporaryMarker | undefined {
  try {
    const markerPath = join(path, ".tc-sdlc-temporary.json");
    const details = lstatSync(markerPath);
    if (!details.isFile() || details.isSymbolicLink()) return undefined;
    const marker = JSON.parse(readFileSync(markerPath, "utf8")) as TemporaryMarker;
    if (
      marker.schema !== TEMPORARY_SCHEMA ||
      marker.owner !== OWNER ||
      typeof marker.kind !== "string" ||
      !TEMPORARY_KINDS.has(marker.kind) ||
      !Number.isSafeInteger(marker.pid)
    ) return undefined;
    return marker;
  } catch {
    return undefined;
  }
}

export function inspectTemporaryRoot(
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
    if (!root.isDirectory() || root.isSymbolicLink()) return { candidates, retained, truncated };
    entries = readdirSync(temporaryRoot).sort();
  } catch {
    return { candidates, retained, truncated };
  }
  for (const name of entries) {
    const isQuarantine = name.startsWith(QUARANTINE_PREFIX);
    if (!name.startsWith(TEMPORARY_PREFIX) && !isQuarantine) continue;
    if (candidates.length + retained.length >= maxEntries) {
      truncated = true;
      continue;
    }
    const path = join(temporaryRoot, name);
    if (isQuarantine) {
      const inspected = inspectQuarantine(path, name, cutoff);
      if (inspected.candidate !== undefined) candidates.push(inspected.candidate);
      if (inspected.retained !== undefined) retained.push(inspected.retained);
      continue;
    }
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
      } else if (processIsAlive(marker.pid)) {
        retained.push({ path: name, reason: "active" });
      } else if (details.mtimeMs > cutoff) {
        retained.push({ path: name, reason: "retention_window" });
      } else if (dirtyWorktree(path)) {
        retained.push({ path: name, reason: "dirty_worktree" });
      } else {
        candidates.push({
          kind: "temporary",
          path: name,
          bytes: directoryBytes(path),
          identity: filesystemIdentity(path),
        });
      }
    } catch {
      retained.push({ path: name, reason: "inspection_failed" });
    }
  }
  return { candidates, retained, truncated };
}

function stillEligible(
  path: string,
  cutoff: number,
  identity: FilesystemIdentity,
): boolean {
  try {
    const details = lstatSync(path);
    const marker = readTemporaryMarker(path);
    return (
      details.isDirectory() &&
      !details.isSymbolicLink() &&
      marker !== undefined &&
      sameIdentity(path, identity) &&
      !processIsAlive(marker.pid) &&
      details.mtimeMs <= cutoff &&
      !dirtyWorktree(path)
    );
  } catch {
    return false;
  }
}

type RemovalResult = Readonly<{
  removedCount: number;
  reclaimedBytes: number;
  failures: number;
  peakWorkers: number;
  retained: MaintenanceRetainedEntry[];
}>;

export async function removeTemporaryCandidates(
  temporaryRoot: string,
  candidates: readonly MaintenanceEntry[],
  cutoff: number,
  workers: number,
  cleanupWorkerMs: number,
): Promise<RemovalResult> {
  const results: Array<
    | Readonly<{ removed: true; bytes: number }>
    | Readonly<{ removed: false; retained: MaintenanceRetainedEntry; failed: boolean }>
  > = new Array(candidates.length);
  let cursor = 0;
  let activeWorkers = 0;
  let peakWorkers = 0;
  const worker = async (): Promise<void> => {
    while (cursor < candidates.length) {
      const index = cursor++;
      const candidate = candidates[index]!;
      const path = join(temporaryRoot, candidate.path);
      if (candidate.kind === "quarantine") {
        activeWorkers += 1;
        peakWorkers = Math.max(peakWorkers, activeWorkers);
        let recovered: Awaited<ReturnType<typeof removeQuarantineCandidate>>;
        try {
          recovered = await removeQuarantineCandidate(
            temporaryRoot,
            candidate,
            cutoff,
            cleanupWorkerMs,
          );
        } finally {
          activeWorkers -= 1;
        }
        results[index] = recovered.removed
          ? { removed: true, bytes: candidate.bytes ?? 0 }
          : {
              removed: false,
              retained: recovered.retained ?? {
                path: candidate.path,
                reason: "inspection_failed",
              },
              failed: recovered.retained?.reason === "inspection_failed",
            };
        continue;
      }
      if (!stillEligible(path, cutoff, candidate.identity)) {
        results[index] = {
          removed: false,
          retained: { path: candidate.path, reason: "changed_during_apply" },
          failed: false,
        };
        continue;
      }
      let created: ReturnType<typeof createQuarantine>;
      try {
        created = createQuarantine(
          temporaryRoot,
          path,
          "temporary",
          candidate.identity,
        );
      } catch {
        results[index] = {
          removed: false,
          retained: { path: candidate.path, reason: "inspection_failed" },
          failed: true,
        };
        continue;
      }
      const quarantineRoot = created.root;
      const quarantine = created.payload;
      try {
        renameSync(path, quarantine);
        if (!sameIdentity(quarantine, candidate.identity)) {
          if (!existsSync(path)) {
            renameSync(quarantine, path);
            finishQuarantine(quarantineRoot);
          }
          results[index] = {
            removed: false,
            retained: {
              path: candidate.path,
              reason: existsSync(quarantine) ? "inspection_failed" : "changed_during_apply",
            },
            failed: existsSync(quarantine),
          };
          continue;
        }
        activeWorkers += 1;
        peakWorkers = Math.max(peakWorkers, activeWorkers);
        try {
          const removed = await deleteQuarantineRoot(
            quarantineRoot,
            filesystemIdentity(quarantineRoot),
            cleanupWorkerMs,
          );
          if (!removed) throw new Error("quarantine deletion failed");
        } finally {
          activeWorkers -= 1;
        }
        results[index] = { removed: true, bytes: candidate.bytes ?? 0 };
      } catch {
        try {
          if (existsSync(quarantine) && !existsSync(path)) renameSync(quarantine, path);
          if (!existsSync(quarantine)) finishQuarantine(quarantineRoot);
        } catch {
          // Both paths remain preserved for explicit operator inspection.
        }
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
  return { removedCount, reclaimedBytes, failures, retained, peakWorkers };
}

/** Recover only stale, explicitly owner-marked tc-sdlc scratch below the OS temp root. */
export async function recoverInterruptedTemporaryState(
  temporaryRoot = tmpdir(),
): Promise<AutomaticRecoveryReceipt> {
  const cutoff = Date.now() - DEFAULT_RETENTION_HOURS * 60 * 60 * 1_000;
  const inspected = inspectTemporaryRoot(resolve(temporaryRoot), cutoff, MAX_ENTRIES);
  const removed = await removeTemporaryCandidates(
    resolve(temporaryRoot),
    inspected.candidates,
    cutoff,
    DEFAULT_CLEANUP_WORKERS,
    DEFAULT_CLEANUP_WORKER_MS,
  );
  return {
    schema: "tc.sdlc/automatic-recovery/v1",
    status: removed.failures === 0 ? "succeeded" : "partial",
    boundary: "os-temporary-root",
    retentionHours: DEFAULT_RETENTION_HOURS,
    candidateCount: inspected.candidates.length,
    removedCount: removed.removedCount,
    reclaimedBytes: removed.reclaimedBytes,
    entriesTruncated: inspected.truncated,
    cleanupFailures: removed.failures,
    peakCleanupWorkers: removed.peakWorkers,
  };
}
