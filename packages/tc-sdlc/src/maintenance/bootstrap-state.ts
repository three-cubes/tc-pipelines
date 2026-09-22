import {
  existsSync,
  lstatSync,
  readdirSync,
  readFileSync,
  renameSync,
} from "node:fs";
import { dirname, isAbsolute, join, relative } from "node:path";

import { canonicalJson, digest } from "../canonical.js";
import {
  QUARANTINE_PREFIX,
  createQuarantine,
  deleteQuarantineRoot,
  filesystemIdentity,
  finishQuarantine,
  inspectQuarantine,
  removeQuarantineCandidate,
  sameIdentity,
} from "./quarantine.js";
import type {
  MaintenanceEntry,
  MaintenanceRetainedEntry,
} from "./types.js";

const OWNER = "@three-cubes/tc-sdlc";

type BootstrapReference = Readonly<{
  schema: "tc.sdlc/bootstrap-reference/v1";
  owner: typeof OWNER;
  consumer: string;
  consumerRoot: string;
  currentStateKey: string;
  predecessorStateKey?: string;
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

function bootstrapStatePaths(stateRoot: string): readonly string[] {
  const releases = join(stateRoot, "releases");
  try {
    if (lstatSync(releases).isSymbolicLink()) return [];
  } catch {
    return [];
  }
  const paths: string[] = [];
  const visit = (directory: string, depth: number): void => {
    for (const name of readdirSync(directory).sort()) {
      const child = join(directory, name);
      const details = lstatSync(child);
      if (details.isSymbolicLink() || !details.isDirectory()) continue;
      if (depth !== 2) {
        visit(child, depth + 1);
        continue;
      }
      const relativePath = relative(stateRoot, child).replaceAll("\\", "/");
      try {
        const statePath = join(child, "state.json");
        const marker = lstatSync(statePath);
        const bytes = readFileSync(statePath, "utf8");
        const state = JSON.parse(bytes) as Record<string, unknown>;
        if (
          marker.isFile() &&
          !marker.isSymbolicLink() &&
          state.schema === "tc.sdlc/bootstrap-state/v6" &&
          canonicalJson(state) === bytes
        ) paths.push(relativePath);
      } catch {
        // Incomplete or foreign-shaped state is never deletion-authorised.
      }
    }
  };
  try {
    visit(releases, 0);
  } catch {
    return [];
  }
  return paths;
}

function bootstrapQuarantinePaths(stateRoot: string): readonly string[] {
  const releases = join(stateRoot, "releases");
  const paths: string[] = [];
  const visit = (directory: string): void => {
    for (const name of readdirSync(directory).sort()) {
      const child = join(directory, name);
      const details = lstatSync(child);
      if (details.isSymbolicLink() || !details.isDirectory()) continue;
      if (name.startsWith(QUARANTINE_PREFIX)) {
        paths.push(relative(stateRoot, child).replaceAll("\\", "/"));
      } else {
        visit(child);
      }
    }
  };
  try {
    if (!lstatSync(releases).isSymbolicLink()) visit(releases);
  } catch {
    return [];
  }
  return paths;
}

function referencePathIsValid(name: string, value: BootstrapReference): boolean {
  return (
    value.schema === "tc.sdlc/bootstrap-reference/v1" &&
    value.owner === OWNER &&
    typeof value.consumer === "string" &&
    value.consumer.length > 0 &&
    typeof value.consumerRoot === "string" &&
    isAbsolute(value.consumerRoot) &&
    name ===
      `${digest({ consumer: value.consumer, consumerRoot: value.consumerRoot }).slice("sha256:".length)}.json`
  );
}

function stateKeyIsValid(value: string): boolean {
  return /^releases\/[^/]+\/[^/]+\/(darwin|linux)-[^/]+$/.test(value);
}

function bootstrapReferences(stateRoot: string): ReadonlySet<string> | undefined {
  const directory = join(stateRoot, "references");
  try {
    const root = lstatSync(directory);
    if (!root.isDirectory() || root.isSymbolicLink()) return undefined;
    const referenced = new Set<string>();
    const files = readdirSync(directory).sort();
    if (files.length === 0) return undefined;
    for (const name of files) {
      if (!/^[a-zA-Z0-9._-]+\.json$/.test(name)) return undefined;
      const path = join(directory, name);
      const details = lstatSync(path);
      if (!details.isFile() || details.isSymbolicLink()) return undefined;
      const bytes = readFileSync(path, "utf8");
      const value = JSON.parse(bytes) as BootstrapReference;
      if (bytes !== canonicalJson(value) || !referencePathIsValid(name, value)) {
        return undefined;
      }
      for (const key of [value.currentStateKey, value.predecessorStateKey]) {
        if (key === undefined) continue;
        if (!stateKeyIsValid(key)) return undefined;
        referenced.add(key);
      }
    }
    return referenced;
  } catch {
    return undefined;
  }
}

export function inspectBootstrapStates(
  stateRoot: string,
  cutoff: number,
): Readonly<{ candidates: MaintenanceEntry[]; retained: MaintenanceRetainedEntry[] }> {
  const candidates: MaintenanceEntry[] = [];
  const retained: MaintenanceRetainedEntry[] = [];
  const references = bootstrapReferences(stateRoot);
  for (const path of bootstrapQuarantinePaths(stateRoot)) {
    const inspected = inspectQuarantine(join(stateRoot, path), path, cutoff);
    if (inspected.candidate !== undefined) candidates.push(inspected.candidate);
    if (inspected.retained !== undefined) retained.push(inspected.retained);
  }
  for (const path of bootstrapStatePaths(stateRoot)) {
    const absolute = join(stateRoot, path);
    if (references === undefined) {
      retained.push({ path, reason: "reference_metadata_absent" });
    } else if (references.has(path)) {
      retained.push({ path, reason: "referenced" });
    } else if (lstatSync(absolute).mtimeMs > cutoff) {
      retained.push({ path, reason: "retention_window" });
    } else {
      candidates.push({
        kind: "bootstrap-state",
        path,
        bytes: directoryBytes(absolute),
        identity: filesystemIdentity(absolute),
      });
    }
  }
  return { candidates, retained };
}

type RemovalResult = Readonly<{
  removedCount: number;
  reclaimedBytes: number;
  failures: number;
  peakWorkers: number;
  retained: MaintenanceRetainedEntry[];
}>;

function retainedReason(
  references: ReadonlySet<string> | undefined,
  path: string,
): MaintenanceRetainedEntry["reason"] {
  return references?.has(path) === true ? "referenced" : "changed_during_apply";
}

export async function removeBootstrapStates(
  stateRoot: string,
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
      const path = join(stateRoot, candidate.path);
      if (candidate.kind === "quarantine") {
        activeWorkers += 1;
        peakWorkers = Math.max(peakWorkers, activeWorkers);
        let recovered: Awaited<ReturnType<typeof removeQuarantineCandidate>>;
        try {
          recovered = await removeQuarantineCandidate(
            stateRoot,
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
      const references = bootstrapReferences(stateRoot);
      if (
        references === undefined ||
        references.has(candidate.path) ||
        !sameIdentity(path, candidate.identity) ||
        lstatSync(path).mtimeMs > cutoff
      ) {
        results[index] = {
          removed: false,
          retained: { path: candidate.path, reason: retainedReason(references, candidate.path) },
          failed: false,
        };
        continue;
      }
      const created = createQuarantine(
        dirname(path),
        path,
        "bootstrap-state",
        candidate.identity,
      );
      const quarantineRoot = created.root;
      const quarantine = created.payload;
      try {
        renameSync(path, quarantine);
        const refreshed = bootstrapReferences(stateRoot);
        if (
          !sameIdentity(quarantine, candidate.identity) ||
          refreshed === undefined ||
          refreshed.has(candidate.path)
        ) {
          if (!existsSync(path)) {
            renameSync(quarantine, path);
            finishQuarantine(quarantineRoot);
          }
          results[index] = {
            removed: false,
            retained: {
              path: candidate.path,
              reason: existsSync(quarantine)
                ? "inspection_failed"
                : retainedReason(refreshed, candidate.path),
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
          // Preserve both paths for operator inspection if restoration races.
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
  return { removedCount, reclaimedBytes, failures, peakWorkers, retained };
}
