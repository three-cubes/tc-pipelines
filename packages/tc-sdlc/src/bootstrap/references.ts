import { randomUUID } from "node:crypto";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
} from "node:fs";
import { isAbsolute, join, relative, sep } from "node:path";

import { canonicalJson, digest } from "../canonical.js";
import { writeCanonicalEvidence } from "../evidence/index.js";
import type { FilesystemIdentity } from "../maintenance/types.js";

const OWNER = "@three-cubes/tc-sdlc";
const COMMITTED_SCHEMA = "tc.sdlc/bootstrap-reference/v2";
const PENDING_SCHEMA = "tc.sdlc/bootstrap-reference-pending/v1";

export type BootstrapReference = Readonly<{
  schema: typeof COMMITTED_SCHEMA;
  owner: typeof OWNER;
  phase: "committed";
  transaction: string;
  committedAtMs: number;
  consumer: string;
  consumerRoot: string;
  currentStateKey: string;
  currentStateIdentity: FilesystemIdentity;
  predecessorStateKey?: string;
  predecessorStateIdentity?: FilesystemIdentity;
}>;

export type PendingBootstrapReference = Readonly<{
  schema: typeof PENDING_SCHEMA;
  owner: typeof OWNER;
  phase: "pending";
  transaction: string;
  consumer: string;
  consumerRoot: string;
  stateKey: string;
  stateIdentity: FilesystemIdentity;
  pid: number;
  processStartedAt: string;
  createdAtMs: number;
}>;

export type BootstrapReferenceAuthorities = ReadonlyMap<string, ReadonlySet<string>>;

export type PendingPublication = Readonly<{
  path: string;
  value: PendingBootstrapReference;
  bytes: string;
  identity: FilesystemIdentity;
}>;

function filesystemIdentity(path: string): FilesystemIdentity {
  const details = lstatSync(path, { bigint: true });
  return {
    device: details.dev.toString(),
    inode: details.ino.toString(),
    birthtimeNanoseconds: details.birthtimeNs.toString(),
  };
}

function validIdentity(value: unknown): value is FilesystemIdentity {
  if (typeof value !== "object" || value === null) return false;
  const identity = value as Record<string, unknown>;
  return [identity.device, identity.inode, identity.birthtimeNanoseconds].every(
    (field) => typeof field === "string" && /^\d+$/.test(field),
  );
}

export function stableIdentityKey(identity: FilesystemIdentity): string {
  return canonicalJson({ device: identity.device, inode: identity.inode });
}

export function referenceMatches(
  references: BootstrapReferenceAuthorities | undefined,
  stateKey: string,
  identity: FilesystemIdentity,
): boolean {
  return references?.get(stateKey)?.has(stableIdentityKey(identity)) === true;
}

function safeOwnedPath(stateRoot: string, target: string): void {
  const suffix = relative(stateRoot, target);
  if (suffix === "" || suffix === ".." || suffix.startsWith(`..${sep}`)) {
    throw new Error("bootstrap reference path escapes owned state");
  }
  let cursor = stateRoot;
  for (const segment of suffix.split(sep)) {
    cursor = join(cursor, segment);
    if (existsSync(cursor) && lstatSync(cursor).isSymbolicLink()) {
      throw new Error("bootstrap reference path traverses a symbolic link");
    }
  }
}

function readCanonical(path: string): unknown {
  const bytes = readFileSync(path, "utf8");
  const value = JSON.parse(bytes) as unknown;
  if (bytes !== canonicalJson(value)) throw new Error("non-canonical reference");
  return value;
}

function validStateKey(value: unknown): value is string {
  return typeof value === "string" &&
    /^releases\/[^/]+\/[^/]+\/(darwin|linux)-[^/]+$/.test(value);
}

function validCommon(value: Record<string, unknown>): boolean {
  return value.owner === OWNER &&
    typeof value.transaction === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
      value.transaction,
    ) &&
    typeof value.consumer === "string" && value.consumer.length > 0 &&
    typeof value.consumerRoot === "string" && isAbsolute(value.consumerRoot);
}

function committedName(value: Pick<BootstrapReference, "consumer" | "consumerRoot">): string {
  return `${digest({ consumer: value.consumer, consumerRoot: value.consumerRoot }).slice("sha256:".length)}.json`;
}

function parseCommitted(name: string, value: unknown): BootstrapReference | undefined {
  if (typeof value !== "object" || value === null) return undefined;
  const record = value as Record<string, unknown>;
  if (
    record.schema !== COMMITTED_SCHEMA || record.phase !== "committed" ||
    !validCommon(record) || !Number.isSafeInteger(record.committedAtMs) ||
    !validStateKey(record.currentStateKey) || !validIdentity(record.currentStateIdentity)
  ) return undefined;
  const reference = record as BootstrapReference;
  if (name !== committedName(reference)) return undefined;
  if ((reference.predecessorStateKey === undefined) !==
      (reference.predecessorStateIdentity === undefined)) return undefined;
  if (reference.predecessorStateKey !== undefined &&
      (!validStateKey(reference.predecessorStateKey) ||
       !validIdentity(reference.predecessorStateIdentity))) return undefined;
  return reference;
}

function parsePending(name: string, value: unknown): PendingBootstrapReference | undefined {
  if (typeof value !== "object" || value === null) return undefined;
  const record = value as Record<string, unknown>;
  if (
    record.schema !== PENDING_SCHEMA || record.phase !== "pending" ||
    !validCommon(record) || name !== `${record.transaction}.json` ||
    !validStateKey(record.stateKey) || !validIdentity(record.stateIdentity) ||
    !Number.isSafeInteger(record.pid) || Number(record.pid) < 1 ||
    typeof record.processStartedAt !== "string" || record.processStartedAt.length === 0 ||
    !Number.isSafeInteger(record.createdAtMs)
  ) return undefined;
  return record as PendingBootstrapReference;
}

function bind(
  authorities: Map<string, Set<string>>,
  stateKey: string,
  identity: FilesystemIdentity,
): void {
  const values = authorities.get(stateKey) ?? new Set<string>();
  values.add(stableIdentityKey(identity));
  authorities.set(stateKey, values);
}

export function readBootstrapReferenceAuthorities(
  stateRoot: string,
): BootstrapReferenceAuthorities | undefined {
  const references = join(stateRoot, "references");
  try {
    safeOwnedPath(stateRoot, references);
    const details = lstatSync(references);
    if (!details.isDirectory() || details.isSymbolicLink()) return undefined;
    const authorities = new Map<string, Set<string>>();
    let observed = false;
    for (const name of readdirSync(references).sort()) {
      const path = join(references, name);
      if (name === "pending") {
        const pendingRoot = lstatSync(path);
        if (!pendingRoot.isDirectory() || pendingRoot.isSymbolicLink()) return undefined;
        for (const pendingName of readdirSync(path).sort()) {
          const pendingPath = join(path, pendingName);
          const pendingDetails = lstatSync(pendingPath);
          if (!pendingDetails.isFile() || pendingDetails.isSymbolicLink()) return undefined;
          const pending = parsePending(pendingName, readCanonical(pendingPath));
          if (pending === undefined) return undefined;
          observed = true;
          bind(authorities, pending.stateKey, pending.stateIdentity);
        }
        continue;
      }
      const file = lstatSync(path);
      if (!file.isFile() || file.isSymbolicLink()) return undefined;
      const committed = parseCommitted(name, readCanonical(path));
      if (committed === undefined) return undefined;
      observed = true;
      bind(authorities, committed.currentStateKey, committed.currentStateIdentity);
      if (committed.predecessorStateKey !== undefined) {
        bind(authorities, committed.predecessorStateKey, committed.predecessorStateIdentity!);
      }
    }
    return observed ? authorities : undefined;
  } catch {
    return undefined;
  }
}

function processIsOwner(value: PendingBootstrapReference): boolean {
  try {
    process.kill(value.pid, 0);
    // A live or reused PID is retained conservatively. Only ESRCH proves that
    // the transaction owner is gone; processStartedAt remains durable evidence.
    return true;
  } catch (error) {
    // EPERM proves that a process exists but is outside this caller's
    // authority. Retain it; only ESRCH is proof that the recorded PID is gone.
    return (error as NodeJS.ErrnoException).code !== "ESRCH";
  }
}

function referenceDirectories(stateRoot: string): Readonly<{ references: string; pending: string }> {
  const references = join(stateRoot, "references");
  const pending = join(references, "pending");
  safeOwnedPath(stateRoot, references);
  safeOwnedPath(stateRoot, pending);
  mkdirSync(references, { recursive: true, mode: 0o700 });
  mkdirSync(pending, { recursive: true, mode: 0o700 });
  return { references, pending };
}

export function writePendingBootstrapReference(
  stateRoot: string,
  consumer: string,
  consumerRoot: string,
  stateKey: string,
  stateIdentity: FilesystemIdentity,
): PendingPublication {
  const { pending } = referenceDirectories(stateRoot);
  const transaction = randomUUID();
  const value: PendingBootstrapReference = {
    schema: PENDING_SCHEMA,
    owner: OWNER,
    phase: "pending",
    transaction,
    consumer,
    consumerRoot,
    stateKey,
    stateIdentity,
    pid: process.pid,
    processStartedAt: `${Math.floor(Date.now() - process.uptime() * 1_000)}`,
    createdAtMs: Date.now(),
  };
  const path = join(pending, `${transaction}.json`);
  writeCanonicalEvidence(path, value);
  return { path, value, bytes: canonicalJson(value), identity: filesystemIdentity(path) };
}

function exactPending(publication: PendingPublication): boolean {
  try {
    return stableIdentityKey(filesystemIdentity(publication.path)) ===
      stableIdentityKey(publication.identity) &&
      readFileSync(publication.path, "utf8") === publication.bytes;
  } catch {
    return false;
  }
}

export function commitBootstrapReference(
  stateRoot: string,
  publication: PendingPublication,
): BootstrapReference {
  if (!exactPending(publication)) throw new Error("pending reference changed");
  const { references } = referenceDirectories(stateRoot);
  const path = join(references, committedName(publication.value));
  let previous: BootstrapReference | undefined;
  if (existsSync(path)) {
    previous = parseCommitted(committedName(publication.value), readCanonical(path));
    if (previous === undefined || previous.consumer !== publication.value.consumer ||
        previous.consumerRoot !== publication.value.consumerRoot) {
      throw new Error("committed reference is invalid");
    }
  }
  const predecessorStateKey = previous?.currentStateKey !== publication.value.stateKey
    ? previous?.currentStateKey
    : previous?.predecessorStateKey;
  const predecessorStateIdentity = previous?.currentStateKey !== publication.value.stateKey
    ? previous?.currentStateIdentity
    : previous?.predecessorStateIdentity;
  const value: BootstrapReference = {
    schema: COMMITTED_SCHEMA,
    owner: OWNER,
    phase: "committed",
    transaction: publication.value.transaction,
    committedAtMs: Date.now(),
    consumer: publication.value.consumer,
    consumerRoot: publication.value.consumerRoot,
    currentStateKey: publication.value.stateKey,
    currentStateIdentity: publication.value.stateIdentity,
    ...(predecessorStateKey === undefined || predecessorStateIdentity === undefined
      ? {} : { predecessorStateKey, predecessorStateIdentity }),
  };
  writeCanonicalEvidence(path, value);
  return value;
}

export function removePendingBootstrapReference(publication: PendingPublication): void {
  if (!exactPending(publication)) return;
  rmSync(publication.path);
}

export function cleanupExpiredDeadPending(stateRoot: string, cutoff: number): number {
  const pending = join(stateRoot, "references", "pending");
  let removed = 0;
  try {
    safeOwnedPath(stateRoot, pending);
    const details = lstatSync(pending);
    if (!details.isDirectory() || details.isSymbolicLink()) return 0;
    for (const name of readdirSync(pending).sort()) {
      const path = join(pending, name);
      const file = lstatSync(path);
      if (!file.isFile() || file.isSymbolicLink() || file.mtimeMs > cutoff) continue;
      const value = parsePending(name, readCanonical(path));
      if (value === undefined || processIsOwner(value)) continue;
      const bytes = canonicalJson(value);
      const identity = filesystemIdentity(path);
      if (stableIdentityKey(filesystemIdentity(path)) !== stableIdentityKey(identity) ||
          readFileSync(path, "utf8") !== bytes) continue;
      rmSync(path);
      removed += 1;
    }
  } catch {
    return removed;
  }
  return removed;
}
