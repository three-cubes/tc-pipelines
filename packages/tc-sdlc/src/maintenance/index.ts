import { lstatSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";

import { canonicalJson } from "../canonical.js";
import { writeCanonicalEvidence } from "../evidence/index.js";
import { inspectBootstrapStates, removeBootstrapStates } from "./bootstrap-state.js";
import {
  DEFAULT_CLEANUP_WORKERS,
  DEFAULT_RETENTION_HOURS,
  MAX_ENTRIES,
  inspectTemporaryRoot,
  removeTemporaryCandidates,
} from "./scratch.js";
import { pruneManagedTools } from "./tools.js";
import type { MaintenanceOptions, MaintenanceReceipt } from "./types.js";

export { recoverInterruptedTemporaryState } from "./scratch.js";
export type {
  AutomaticRecoveryReceipt,
  FilesystemIdentity,
  MaintenanceEntry,
  MaintenanceMode,
  MaintenanceOptions,
  MaintenanceReceipt,
  MaintenanceRetainedEntry,
  MaintenanceToolReceipt,
} from "./types.js";

const OWNER = { schema: "tc.sdlc/state-owner/v1", owner: "@three-cubes/tc-sdlc" } as const;
const MAX_CLEANUP_WORKERS = 16;

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
    peakCleanupWorkers: 0,
    cleanupFailures: 0,
    candidates: [],
    retained: [],
    tools: {
      uv: { status: "not_requested", reclaimedBytes: 0 },
      pnpm: { status: "not_requested", reclaimedBytes: 0 },
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

function optionsAreValid(
  options: MaintenanceOptions,
  retentionHours: number,
  maxEntries: number,
  cleanupWorkers: number,
): boolean {
  return (
    isAbsolute(options.stateRoot) &&
    isAbsolute(options.receiptPath) &&
    Number.isFinite(retentionHours) &&
    retentionHours >= 0 &&
    Number.isSafeInteger(maxEntries) &&
    maxEntries > 0 &&
    Number.isSafeInteger(cleanupWorkers) &&
    cleanupWorkers > 0 &&
    cleanupWorkers <= MAX_CLEANUP_WORKERS &&
    (options.mode === "dry-run" || options.mode === "apply")
  );
}

export async function maintain(options: MaintenanceOptions): Promise<MaintenanceReceipt> {
  const retentionHours = options.retentionHours ?? DEFAULT_RETENTION_HOURS;
  const maxEntries = options.maxEntries ?? MAX_ENTRIES;
  const cleanupWorkers = options.cleanupWorkers ?? DEFAULT_CLEANUP_WORKERS;
  const temporaryRoot = resolve(options.temporaryRoot ?? tmpdir());
  const stateRoot = resolve(options.stateRoot);
  if (!optionsAreValid(options, retentionHours, maxEntries, cleanupWorkers)) {
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
  const stateInspection = inspectBootstrapStates(stateRoot, cutoff);
  const remainingEntries = Math.max(
    0,
    maxEntries - inspected.candidates.length - inspected.retained.length,
  );
  const stateCandidates = stateInspection.candidates.slice(0, remainingEntries);
  const stateRetained = stateInspection.retained.slice(
    0,
    Math.max(0, remainingEntries - stateCandidates.length),
  );
  const stateTruncated =
    stateCandidates.length + stateRetained.length <
    stateInspection.candidates.length + stateInspection.retained.length;
  let removedCount = 0;
  let reclaimedBytes = 0;
  let cleanupFailures = 0;
  let peakCleanupWorkers = 0;
  if (options.mode === "apply") {
    const removal = await removeTemporaryCandidates(
      temporaryRoot,
      inspected.candidates,
      cutoff,
      cleanupWorkers,
    );
    removedCount = removal.removedCount;
    reclaimedBytes = removal.reclaimedBytes;
    cleanupFailures = removal.failures;
    peakCleanupWorkers = removal.peakWorkers;
    inspected.retained.push(...removal.retained);
    const stateRemoval = await removeBootstrapStates(
      stateRoot,
      stateCandidates,
      cutoff,
      cleanupWorkers,
    );
    removedCount += stateRemoval.removedCount;
    reclaimedBytes += stateRemoval.reclaimedBytes;
    cleanupFailures += stateRemoval.failures;
    peakCleanupWorkers = Math.max(peakCleanupWorkers, stateRemoval.peakWorkers);
    stateRetained.push(...stateRemoval.retained);
  }

  const toolPruning = pruneManagedTools(options, stateRoot, retentionHours);
  reclaimedBytes += toolPruning.reclaimedBytes;
  const failureReason =
    cleanupFailures > 0 ? "temporary_cleanup_failed" : toolPruning.failureReason;
  return writeReceipt(
    options.receiptPath,
    receipt(options, {
      status: failureReason === null ? "succeeded" : "failed",
      reason: failureReason,
      candidateCount: inspected.candidates.length + stateCandidates.length,
      removedCount,
      reclaimedBytes,
      entriesTruncated: inspected.truncated || stateTruncated,
      cleanupWorkers,
      peakCleanupWorkers,
      cleanupFailures,
      candidates: [...inspected.candidates, ...stateCandidates],
      retained: [...inspected.retained, ...stateRetained],
      tools: toolPruning.tools,
    }),
  );
}
