import {
  existsSync,
  lstatSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmdirSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { rm } from "node:fs/promises";
import { basename, join } from "node:path";

import { canonicalJson } from "../canonical.js";
import type { FilesystemIdentity, MaintenanceEntry, MaintenanceRetainedEntry } from "./types.js";

export const QUARANTINE_PREFIX = ".tc-sdlc-quarantine-";
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
    const payload = join(path, "candidate");
    if (marker === undefined) {
      return { retained: { path: displayPath, reason: "foreign" } };
    }
    const entries = readdirSync(path).sort();
    const emptyOwned = entries.length === 1 && entries[0] === MARKER;
    if (!emptyOwned && !sameIdentity(payload, marker.payloadIdentity)) {
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
): Promise<Readonly<{ removed: boolean; retained?: MaintenanceRetainedEntry }>> {
  const root = join(base, candidate.path);
  const marker = readMarker(root);
  const payload = join(root, "candidate");
  const refreshed = inspectQuarantine(root, candidate.path, cutoff).candidate;
  if (
    marker === undefined ||
    refreshed === undefined ||
    !sameIdentity(root, candidate.identity) ||
    (existsSync(payload) && !sameIdentity(payload, marker.payloadIdentity))
  ) {
    return { removed: false, retained: { path: candidate.path, reason: "changed_during_apply" } };
  }
  try {
    if (!existsSync(payload)) {
      finishQuarantine(root);
      return { removed: true };
    }
    const deleting = join(root, "deleting");
    renameSync(payload, deleting);
    if (!sameIdentity(deleting, marker.payloadIdentity)) {
      if (!existsSync(payload)) renameSync(deleting, payload);
      return { removed: false, retained: { path: candidate.path, reason: "changed_during_apply" } };
    }
    await rm(deleting, { recursive: true, force: false });
    finishQuarantine(root);
    return { removed: true };
  } catch {
    return { removed: false, retained: { path: candidate.path, reason: "inspection_failed" } };
  }
}
