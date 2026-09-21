import {
  existsSync,
  lstatSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  rmdirSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { basename, dirname, join } from "node:path";
import { parentPort, workerData } from "node:worker_threads";

import { canonicalJson } from "../canonical.js";
import type { FilesystemIdentity } from "./types.js";

const MARKER = ".tc-sdlc-quarantine.json";
const OWNER = "@three-cubes/tc-sdlc";
const PREFIX = ".tc-sdlc-quarantine-";

type Marker = Readonly<{
  schema: "tc.sdlc/quarantine-owner/v1";
  owner: typeof OWNER;
  kind: "temporary" | "bootstrap-state";
  originalName: string;
  payloadIdentity: FilesystemIdentity;
}>;

type Input = Readonly<{ root: string; identity: FilesystemIdentity }>;

function identity(path: string): FilesystemIdentity {
  const details = lstatSync(path, { bigint: true });
  return {
    device: details.dev.toString(),
    inode: details.ino.toString(),
    birthtimeNanoseconds: details.birthtimeNs.toString(),
  };
}

function same(path: string, expected: FilesystemIdentity): boolean {
  try {
    return canonicalJson(identity(path)) === canonicalJson(expected);
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

function marker(root: string): Marker | undefined {
  try {
    const path = join(root, MARKER);
    const details = lstatSync(path);
    if (!details.isFile() || details.isSymbolicLink()) return undefined;
    const bytes = readFileSync(path, "utf8");
    const value = JSON.parse(bytes) as Marker;
    if (
      bytes !== canonicalJson(value) ||
      value.schema !== "tc.sdlc/quarantine-owner/v1" ||
      value.owner !== OWNER ||
      (value.kind !== "temporary" && value.kind !== "bootstrap-state") ||
      basename(value.originalName) !== value.originalName ||
      value.originalName.length === 0 ||
      !validIdentity(value.payloadIdentity)
    ) return undefined;
    return value;
  } catch {
    return undefined;
  }
}

function validateLayout(root: string): Marker | undefined {
  const entries = readdirSync(root).sort();
  const value = marker(root);
  if (value === undefined) return undefined;
  if (entries.length === 1 && entries[0] === MARKER) return value;
  if (
    entries.length !== 2 ||
    entries[0] !== MARKER ||
    (entries[1] !== "candidate" && entries[1] !== "deleting") ||
    !same(join(root, entries[1]), value.payloadIdentity)
  ) return undefined;
  return value;
}

function envelopeAndDelete(input: Input): void {
  if (!same(input.root, input.identity)) throw new Error("quarantine identity changed");
  const value = validateLayout(input.root);
  if (value === undefined) throw new Error("quarantine layout changed");
  const envelope = mkdtempSync(join(dirname(input.root), `${PREFIX}${process.pid}-`));
  const envelopeIdentity = input.identity;
  const envelopeMarker: Marker = {
    schema: "tc.sdlc/quarantine-owner/v1",
    owner: OWNER,
    kind: value.kind,
    originalName: basename(input.root),
    payloadIdentity: envelopeIdentity,
  };
  writeFileSync(join(envelope, MARKER), canonicalJson(envelopeMarker), {
    flag: "wx",
    mode: 0o600,
  });
  const candidate = join(envelope, "candidate");
  renameSync(input.root, candidate);
  if (!same(candidate, envelopeIdentity)) {
    throw new Error("re-quarantined identity changed");
  }
  const deleting = join(envelope, "deleting");
  renameSync(candidate, deleting);
  if (!same(deleting, envelopeIdentity)) {
    throw new Error("deleting identity changed");
  }
  // This worker performs no asynchronous work between the final identity check
  // and deletion. Independent roots still execute concurrently in bounded workers.
  rmSync(deleting, { recursive: true, force: false });
  unlinkSync(join(envelope, MARKER));
  rmdirSync(envelope);
}

try {
  const input = workerData as Input;
  if (
    typeof input.root !== "string" ||
    !validIdentity(input.identity) ||
    !existsSync(input.root)
  ) {
    throw new Error("quarantine root is absent");
  }
  envelopeAndDelete(input);
  parentPort?.postMessage({ status: "removed" });
} catch (error) {
  parentPort?.postMessage({
    status: "failed",
    reason: error instanceof Error ? error.message : String(error),
  });
}
