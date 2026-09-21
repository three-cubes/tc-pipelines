import {
  lstatSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmdirSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { basename, join } from "node:path";
import { Worker } from "node:worker_threads";

import { canonicalJson } from "../canonical.js";
import type { FilesystemIdentity, MaintenanceEntry, MaintenanceRetainedEntry } from "./types.js";

export const QUARANTINE_PREFIX = ".tc-sdlc-quarantine-";
export const DEFAULT_CLEANUP_WORKER_MS = 120_000;
const MARKER = ".tc-sdlc-quarantine.json";
const OWNER = "@three-cubes/tc-sdlc";

type QuarantineKind = "temporary" | "bootstrap-state";
type QuarantineMarker = Readonly<{
  schema: "tc.sdlc/quarantine-owner/v1";
  owner: typeof OWNER;
  kind: QuarantineKind;
  originalName: string;
  payloadIdentity: FilesystemIdentity;
}>;

export function filesystemIdentity(path: string): FilesystemIdentity {
  const details = lstatSync(path, { bigint: true });
  return {
    device: details.dev.toString(),
    inode: details.ino.toString(),
    birthtimeNanoseconds: details.birthtimeNs.toString(),
  };
}

export function sameIdentity(path: string, expected: FilesystemIdentity): boolean {
  try {
    return canonicalJson(filesystemIdentity(path)) === canonicalJson(expected);
  } catch {
    return false;
  }
}

function validIdentity(value: unknown): value is FilesystemIdentity {
  if (typeof value !== "object" || value === null) return false;
  const identity = value as Record<string, unknown>;
  return [identity.device, identity.inode, identity.birthtimeNanoseconds]
    .every((field) => typeof field === "string" && /^\d+$/.test(field));
}

function readMarker(root: string): QuarantineMarker | undefined {
  try {
    const path = join(root, MARKER);
    const details = lstatSync(path);
    if (!details.isFile() || details.isSymbolicLink()) return undefined;
    const bytes = readFileSync(path, "utf8");
    const marker = JSON.parse(bytes) as QuarantineMarker;
    if (
      bytes !== canonicalJson(marker) ||
      marker.schema !== "tc.sdlc/quarantine-owner/v1" ||
      marker.owner !== OWNER ||
      (marker.kind !== "temporary" && marker.kind !== "bootstrap-state") ||
      basename(marker.originalName) !== marker.originalName ||
      marker.originalName.length === 0 ||
      !validIdentity(marker.payloadIdentity)
    ) return undefined;
    return marker;
  } catch {
    return undefined;
  }
}

function payloadPhase(
  root: string,
  marker: QuarantineMarker | undefined,
): "empty" | "candidate" | "deleting" | undefined {
  const entries = readdirSync(root).sort();
  if (marker === undefined || entries[0] !== MARKER) return undefined;
  if (entries.length === 1) return "empty";
  if (
    entries.length !== 2 ||
    (entries[1] !== "candidate" && entries[1] !== "deleting") ||
    !sameIdentity(join(root, entries[1]), marker.payloadIdentity)
  ) return undefined;
  return entries[1];
}

export function deleteQuarantineRoot(
  root: string,
  identity: FilesystemIdentity,
  timeoutMs: number,
): Promise<boolean> {
  return new Promise((resolve) => {
    let worker: Worker;
    try {
      worker = new Worker(new URL("./deletion-worker.js", import.meta.url), {
        workerData: { root, identity },
      });
    } catch {
      resolve(false);
      return;
    }
    let completed = false;
    const finish = (removed: boolean): void => {
      if (completed) return;
      completed = true;
      clearTimeout(timer);
      resolve(removed);
    };
    const timer = setTimeout(() => {
      if (completed) return;
      completed = true;
      void worker.terminate().then(
        () => resolve(false),
        () => resolve(false),
      );
    }, timeoutMs);
    worker.once("message", (message: Readonly<{ status?: string }>) => {
      finish(message.status === "removed");
    });
    worker.once("error", () => {
      finish(false);
    });
    worker.once("exit", () => {
      finish(false);
    });
  });
}

export function createQuarantine(
  parent: string,
  originalPath: string,
  kind: QuarantineKind,
  payloadIdentity: FilesystemIdentity,
): Readonly<{ root: string; payload: string }> {
  const root = mkdtempSync(join(parent, `${QUARANTINE_PREFIX}${process.pid}-`));
  const marker: QuarantineMarker = {
    schema: "tc.sdlc/quarantine-owner/v1",
    owner: OWNER,
    kind,
    originalName: basename(originalPath),
    payloadIdentity,
  };
  writeFileSync(join(root, MARKER), canonicalJson(marker), { flag: "wx", mode: 0o600 });
  return { root, payload: join(root, "candidate") };
}

export function finishQuarantine(root: string): void {
  const entries = readdirSync(root).sort();
  if (entries.length !== 1 || entries[0] !== MARKER || readMarker(root) === undefined) {
    throw new Error("quarantine contains unexpected state");
  }
  unlinkSync(join(root, MARKER));
  rmdirSync(root);
}

export function inspectQuarantine(
  path: string,
  displayPath: string,
  cutoff: number,
): Readonly<{ candidate?: MaintenanceEntry; retained?: MaintenanceRetainedEntry }> {
  try {
    const details = lstatSync(path);
    if (!details.isDirectory() || details.isSymbolicLink()) {
      return { retained: { path: displayPath, reason: "foreign" } };
    }
    const marker = readMarker(path);
    if (payloadPhase(path, marker) === undefined) {
      return { retained: { path: displayPath, reason: "foreign" } };
    }
    if (details.mtimeMs > cutoff) {
      return { retained: { path: displayPath, reason: "retention_window" } };
    }
    return {
      candidate: {
        kind: "quarantine",
        path: displayPath,
        identity: filesystemIdentity(path),
      },
    };
  } catch {
    return { retained: { path: displayPath, reason: "inspection_failed" } };
  }
}

export async function removeQuarantineCandidate(
  base: string,
  candidate: MaintenanceEntry,
  cutoff: number,
  timeoutMs: number,
): Promise<Readonly<{ removed: boolean; retained?: MaintenanceRetainedEntry }>> {
  const root = join(base, candidate.path);
  const marker = readMarker(root);
  const refreshed = inspectQuarantine(root, candidate.path, cutoff).candidate;
  if (
    refreshed === undefined ||
    !sameIdentity(root, candidate.identity) ||
    payloadPhase(root, marker) === undefined
  ) {
    return { removed: false, retained: { path: candidate.path, reason: "changed_during_apply" } };
  }
  const removed = await deleteQuarantineRoot(root, candidate.identity, timeoutMs);
  return removed
    ? { removed: true }
    : { removed: false, retained: { path: candidate.path, reason: "inspection_failed" } };
}
