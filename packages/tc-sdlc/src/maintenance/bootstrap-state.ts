import {
  existsSync,
  lstatSync,
  readdirSync,
  readFileSync,
  renameSync,
} from "node:fs";
import { dirname, join, relative } from "node:path";

import { canonicalJson } from "../canonical.js";
import {
  cleanupExpiredDeadPending,
  readBootstrapReferenceAuthorities,
  leaseMatches,
  referenceMatches,
  type BootstrapReferenceAuthorities,
} from "../bootstrap/references.js";
import {
  QUARANTINE_PREFIX,
  createQuarantine,
  deleteQuarantineRoot,
  filesystemIdentity,
  finishQuarantine,
  inspectQuarantine,
  inspectQuarantinePayload,
  removeQuarantineCandidate,
  sameIdentity,
  sameMoveIdentity,
} from "./quarantine.js";
import type {
  FilesystemIdentity,
  MaintenanceEntry,
  MaintenanceRetainedEntry,
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

export function inspectBootstrapStates(
  stateRoot: string,
  cutoff: number,
): Readonly<{ candidates: MaintenanceEntry[]; retained: MaintenanceRetainedEntry[] }> {
  const candidates: MaintenanceEntry[] = [];
  const retained: MaintenanceRetainedEntry[] = [];
  const references = readBootstrapReferenceAuthorities(stateRoot);
  for (const path of bootstrapQuarantinePaths(stateRoot)) {
    const inspected = inspectQuarantine(join(stateRoot, path), path, cutoff);
    if (inspected.candidate !== undefined) candidates.push(inspected.candidate);
    if (inspected.retained !== undefined) retained.push(inspected.retained);
  }
  for (const path of bootstrapStatePaths(stateRoot)) {
    const absolute = join(stateRoot, path);
    const identity = filesystemIdentity(absolute);
    if (references === undefined) {
      retained.push({ path, reason: "reference_metadata_absent" });
    } else if (leaseMatches(references, path, identity)) {
      retained.push({ path, reason: "leased" });
    } else if (referenceMatches(references, path, identity)) {
      retained.push({ path, reason: "referenced" });
    } else if (lstatSync(absolute).mtimeMs > cutoff) {
      retained.push({ path, reason: "retention_window" });
    } else {
      candidates.push({
        kind: "bootstrap-state",
        path,
        bytes: directoryBytes(absolute),
        identity,
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
  referenceMetadataRemovedCount: number;
  retained: MaintenanceRetainedEntry[];
}>;

function retainedReason(
  references: BootstrapReferenceAuthorities | undefined,
  path: string,
  identity: FilesystemIdentity,
): MaintenanceRetainedEntry["reason"] {
  return leaseMatches(references, path, identity)
    ? "leased"
    : referenceMatches(references, path, identity)
      ? "referenced"
      : "changed_during_apply";
}

type BootstrapDeletionPreparation =
  | Readonly<{ kind: "retained"; retained: MaintenanceRetainedEntry; failed: boolean }>
  | Readonly<{ kind: "quarantined"; root: string; payload: string }>;

function restoreReferencedQuarantine(
  stateRoot: string,
  candidate: MaintenanceEntry,
): MaintenanceRetainedEntry | undefined {
  const root = join(stateRoot, candidate.path);
  try {
    if (!sameIdentity(root, candidate.identity)) return undefined;
    const payload = inspectQuarantinePayload(root);
    if (payload?.kind !== "bootstrap-state") return undefined;
    const parentKey = dirname(candidate.path).replaceAll("\\", "/");
    const stateKey = `${parentKey}/${payload.originalName}`;
    const references = readBootstrapReferenceAuthorities(stateRoot);
    if (!referenceMatches(references, stateKey, payload.identity)) return undefined;
    const original = join(stateRoot, stateKey);
    if (existsSync(original)) throw new Error("referenced state path already exists");
    renameSync(payload.payload, original);
    if (!sameMoveIdentity(original, payload.identity)) {
      throw new Error("restored state identity changed");
    }
    finishQuarantine(root);
    return { path: stateKey, reason: "referenced" };
  } catch {
    return undefined;
  }
}

function prepareBootstrapDeletion(
  stateRoot: string,
  candidate: MaintenanceEntry,
  cutoff: number,
): BootstrapDeletionPreparation {
  const path = join(stateRoot, candidate.path);
  const references = readBootstrapReferenceAuthorities(stateRoot);
  try {
    if (
      references === undefined ||
      referenceMatches(references, candidate.path, candidate.identity) ||
      !sameIdentity(path, candidate.identity) ||
      lstatSync(path).mtimeMs > cutoff
    ) {
      return {
        kind: "retained",
        retained: {
          path: candidate.path,
          reason: references === undefined
            ? "reference_metadata_absent"
            : retainedReason(references, candidate.path, candidate.identity),
        },
        failed: false,
      };
    }
    const created = createQuarantine(
      dirname(path),
      path,
      "bootstrap-state",
      candidate.identity,
    );
    renameSync(path, created.payload);
    if (!sameMoveIdentity(created.payload, candidate.identity)) {
      if (!existsSync(path)) {
        renameSync(created.payload, path);
        finishQuarantine(created.root);
      }
      return {
        kind: "retained",
        retained: { path: candidate.path, reason: "changed_during_apply" },
        failed: existsSync(created.payload),
      };
    }
    const refreshedReferences = readBootstrapReferenceAuthorities(stateRoot);
    if (
      refreshedReferences === undefined ||
      referenceMatches(refreshedReferences, candidate.path, candidate.identity)
    ) {
      if (existsSync(path)) {
        return {
          kind: "retained",
          retained: { path: candidate.path, reason: "inspection_failed" },
          failed: true,
        };
      }
      renameSync(created.payload, path);
      finishQuarantine(created.root);
      return {
        kind: "retained",
        retained: {
          path: candidate.path,
          reason: refreshedReferences === undefined
            ? "reference_metadata_absent"
            : "referenced",
        },
        failed: false,
      };
    }
    return { kind: "quarantined", root: created.root, payload: created.payload };
  } catch {
    return {
      kind: "retained",
      retained: { path: candidate.path, reason: "inspection_failed" },
      failed: true,
    };
  }
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
        const restored = restoreReferencedQuarantine(stateRoot, candidate);
        if (restored !== undefined) {
          results[index] = { removed: false, retained: restored, failed: false };
          continue;
        }
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
      let prepared: BootstrapDeletionPreparation;
      try {
        prepared = prepareBootstrapDeletion(stateRoot, candidate, cutoff);
      } catch {
        results[index] = {
          removed: false,
          retained: { path: candidate.path, reason: "inspection_failed" },
          failed: true,
        };
        continue;
      }
      if (prepared.kind === "retained") {
        results[index] = {
          removed: false,
          retained: prepared.retained,
          failed: prepared.failed,
        };
        continue;
      }
      const quarantineRoot = prepared.root;
      const quarantine = prepared.payload;
      try {
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
  const referenceMetadataRemovedCount = await cleanupExpiredDeadPending(stateRoot, cutoff);
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
  return {
    removedCount,
    reclaimedBytes,
    failures,
    peakWorkers,
    referenceMetadataRemovedCount,
    retained,
  };
}
