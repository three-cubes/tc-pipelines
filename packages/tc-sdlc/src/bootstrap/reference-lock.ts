import { randomUUID } from "node:crypto";
import {
  closeSync,
  existsSync,
  fsyncSync,
  linkSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  readdirSync,
  unlinkSync,
} from "node:fs";
import { dirname, isAbsolute, join, relative, sep } from "node:path";

import { canonicalJson, digest } from "../canonical.js";
import { writeCanonicalEvidence } from "../evidence/index.js";
import type { FilesystemIdentity } from "../maintenance/types.js";
import { processOwnerState, processStartIdentity } from "./process-identity.js";
import type { PendingPublication } from "./references.js";

const OWNER = "@three-cubes/tc-sdlc";
const LOCK_SCHEMA = "tc.sdlc/bootstrap-reference-commit-lock/v1";
const LOCK_WAIT_MILLISECONDS = 5_000;
const LOCK_RETRY_MILLISECONDS = 25;

type BootstrapReferenceCommitLockMarker = Readonly<{
  schema: typeof LOCK_SCHEMA;
  owner: typeof OWNER;
  phase: "held";
  token: string;
  transaction: string;
  consumer: string;
  consumerRoot: string;
  pid: number;
  processStartIdentity: string;
  createdAtMs: number;
}>;

export type BootstrapReferenceCommitLock = Readonly<{
  path: string;
  markerPath: string;
  value: BootstrapReferenceCommitLockMarker;
  bytes: string;
  identity: FilesystemIdentity;
}>;

export class BootstrapReferenceCommitError extends Error {
  readonly kind: "busy" | "invalid";

  constructor(kind: "busy" | "invalid", message: string) {
    super(message);
    this.kind = kind;
  }
}

function filesystemIdentity(path: string): FilesystemIdentity {
  const details = lstatSync(path, { bigint: true });
  return {
    device: details.dev.toString(),
    inode: details.ino.toString(),
    birthtimeNanoseconds: details.birthtimeNs.toString(),
  };
}

function exactIdentity(left: FilesystemIdentity, right: FilesystemIdentity): boolean {
  return canonicalJson(left) === canonicalJson(right);
}

function safeOwnedPath(stateRoot: string, target: string): void {
  const suffix = relative(stateRoot, target);
  if (suffix === "" || suffix === ".." || suffix.startsWith(`..${sep}`)) {
    throw new Error("bootstrap reference lock path escapes owned state");
  }
  let cursor = stateRoot;
  for (const segment of suffix.split(sep)) {
    cursor = join(cursor, segment);
    if (existsSync(cursor) && lstatSync(cursor).isSymbolicLink()) {
      throw new Error("bootstrap reference lock path traverses a symbolic link");
    }
  }
}

function lockDirectories(stateRoot: string): Readonly<{ references: string; locks: string }> {
  const references = join(stateRoot, "references");
  const locks = join(references, "locks");
  safeOwnedPath(stateRoot, references);
  safeOwnedPath(stateRoot, locks);
  mkdirSync(references, { recursive: true, mode: 0o700 });
  mkdirSync(locks, { recursive: true, mode: 0o700 });
  return { references, locks };
}

function fsyncDirectory(path: string): void {
  if (process.platform === "win32") return;
  const descriptor = openSync(path, "r");
  try {
    fsyncSync(descriptor);
  } finally {
    closeSync(descriptor);
  }
}

function validUuid(value: unknown): value is string {
  return typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value);
}

function validLockMarker(value: unknown): value is BootstrapReferenceCommitLockMarker {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return record.schema === LOCK_SCHEMA && record.owner === OWNER && record.phase === "held" &&
    validUuid(record.token) && validUuid(record.transaction) &&
    typeof record.consumer === "string" && record.consumer.length > 0 &&
    typeof record.consumerRoot === "string" && isAbsolute(record.consumerRoot) &&
    Number.isSafeInteger(record.pid) && Number(record.pid) > 0 &&
    typeof record.processStartIdentity === "string" && record.processStartIdentity.length > 0 &&
    Number.isSafeInteger(record.createdAtMs);
}

function lockStem(value: Pick<BootstrapReferenceCommitLockMarker, "consumer" | "consumerRoot">): string {
  return digest({ consumer: value.consumer, consumerRoot: value.consumerRoot }).slice("sha256:".length);
}

function markerName(value: BootstrapReferenceCommitLockMarker): string {
  return `${lockStem(value)}.${value.token}.marker`;
}

function exactRegularFile(path: string, identity: FilesystemIdentity, bytes: string): boolean {
  try {
    const details = lstatSync(path);
    return details.isFile() && !details.isSymbolicLink() &&
      exactIdentity(filesystemIdentity(path), identity) && readFileSync(path, "utf8") === bytes;
  } catch {
    return false;
  }
}

function inspectExistingLock(
  path: string,
  locks: string,
  publication: PendingPublication,
): Readonly<{
  value: BootstrapReferenceCommitLockMarker;
  bytes: string;
  identity: FilesystemIdentity;
  markerPath: string;
}> {
  try {
    const details = lstatSync(path);
    if (!details.isFile() || details.isSymbolicLink()) throw new Error("not a regular file");
    const bytes = readFileSync(path, "utf8");
    const parsed = JSON.parse(bytes) as unknown;
    if (bytes !== canonicalJson(parsed) || !validLockMarker(parsed)) {
      throw new Error("not a canonical lock marker");
    }
    if (parsed.consumer !== publication.value.consumer ||
        parsed.consumerRoot !== publication.value.consumerRoot) {
      throw new Error("lock belongs to another consumer");
    }
    const markerPath = join(locks, markerName(parsed));
    safeOwnedPath(locks, markerPath);
    const identity = filesystemIdentity(path);
    if (!exactRegularFile(markerPath, identity, bytes)) {
      throw new Error("lock is not bound to its durable marker");
    }
    return { value: parsed, bytes, identity, markerPath };
  } catch (error) {
    throw new BootstrapReferenceCommitError(
      "invalid",
      `bootstrap reference commit lock is invalid: ${
        error instanceof Error ? error.message : "unrecognised lock"
      }`,
    );
  }
}

function removeExactFile(path: string, identity: FilesystemIdentity, bytes: string): boolean {
  if (!exactRegularFile(path, identity, bytes)) return false;
  unlinkSync(path);
  return true;
}

function recoverDeadLock(
  path: string,
  locks: string,
  existing: ReturnType<typeof inspectExistingLock>,
): boolean {
  if (processOwnerState(existing.value.pid, existing.value.processStartIdentity) !== "dead") {
    return false;
  }
  try {
    if (!exactRegularFile(existing.markerPath, existing.identity, existing.bytes) ||
        !exactRegularFile(path, existing.identity, existing.bytes)) return false;
    unlinkSync(path);
    fsyncDirectory(locks);
    removeExactFile(existing.markerPath, existing.identity, existing.bytes);
    fsyncDirectory(locks);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return false;
    throw error;
  }
}

function discardOwnMarker(lock: BootstrapReferenceCommitLock): void {
  if (removeExactFile(lock.markerPath, lock.identity, lock.bytes)) {
    fsyncDirectory(dirname(lock.markerPath));
  }
}

export async function acquireBootstrapReferenceCommitLock(
  stateRoot: string,
  publication: PendingPublication,
): Promise<BootstrapReferenceCommitLock> {
  const { locks } = lockDirectories(stateRoot);
  const stem = lockStem(publication.value);
  const path = join(locks, `${stem}.lock`);
  const token = randomUUID();
  const startIdentity = processStartIdentity(process.pid);
  if (startIdentity === undefined) {
    throw new BootstrapReferenceCommitError(
      "invalid",
      "current process start identity could not be established",
    );
  }
  const value: BootstrapReferenceCommitLockMarker = {
    schema: LOCK_SCHEMA,
    owner: OWNER,
    phase: "held",
    token,
    transaction: publication.value.transaction,
    consumer: publication.value.consumer,
    consumerRoot: publication.value.consumerRoot,
    pid: process.pid,
    processStartIdentity: startIdentity,
    createdAtMs: Date.now(),
  };
  const markerPath = join(locks, markerName(value));
  writeCanonicalEvidence(markerPath, value);
  const lock: BootstrapReferenceCommitLock = {
    path,
    markerPath,
    value,
    bytes: canonicalJson(value),
    identity: filesystemIdentity(markerPath),
  };
  const deadline = Date.now() + LOCK_WAIT_MILLISECONDS;
  while (true) {
    try {
      linkSync(markerPath, path);
      fsyncDirectory(locks);
      if (!exactRegularFile(path, lock.identity, lock.bytes)) {
        throw new BootstrapReferenceCommitError(
          "invalid",
          "bootstrap reference commit lock changed during acquisition",
        );
      }
      return lock;
    } catch (error) {
      if (error instanceof BootstrapReferenceCommitError) {
        discardOwnMarker(lock);
        throw error;
      }
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") {
        discardOwnMarker(lock);
        throw new BootstrapReferenceCommitError(
          "invalid",
          "bootstrap reference commit lock could not be acquired",
        );
      }
      let existing: ReturnType<typeof inspectExistingLock>;
      try {
        existing = inspectExistingLock(path, locks, publication);
      } catch (inspectionError) {
        discardOwnMarker(lock);
        throw inspectionError;
      }
      const ownerState = processOwnerState(
        existing.value.pid,
        existing.value.processStartIdentity,
      );
      if (ownerState === "dead") {
        recoverDeadLock(path, locks, existing);
        continue;
      }
      if (Date.now() >= deadline) {
        discardOwnMarker(lock);
        throw new BootstrapReferenceCommitError(
          "busy",
          ownerState === "live"
            ? "another live bootstrap owns the consumer reference commit lock"
            : "the consumer reference commit lock owner could not be proven dead",
        );
      }
      await new Promise((resolve) => setTimeout(resolve, LOCK_RETRY_MILLISECONDS));
    }
  }
}

export function assertBootstrapReferenceCommitLock(
  lock: BootstrapReferenceCommitLock,
): void {
  if (!exactRegularFile(lock.markerPath, lock.identity, lock.bytes) ||
      !exactRegularFile(lock.path, lock.identity, lock.bytes)) {
    throw new BootstrapReferenceCommitError(
      "invalid",
      "bootstrap reference commit lock changed while held",
    );
  }
}

export function releaseBootstrapReferenceCommitLock(
  lock: BootstrapReferenceCommitLock,
): void {
  assertBootstrapReferenceCommitLock(lock);
  unlinkSync(lock.path);
  fsyncDirectory(dirname(lock.path));
  if (!removeExactFile(lock.markerPath, lock.identity, lock.bytes)) {
    throw new BootstrapReferenceCommitError(
      "invalid",
      "bootstrap reference commit marker changed during release",
    );
  }
  fsyncDirectory(dirname(lock.path));
}

export function cleanupExpiredDeadReferenceLockMarkers(
  stateRoot: string,
  cutoff: number,
): number {
  const locks = join(stateRoot, "references", "locks");
  let removed = 0;
  try {
    safeOwnedPath(stateRoot, locks);
    const root = lstatSync(locks);
    if (!root.isDirectory() || root.isSymbolicLink()) return 0;
    for (const name of readdirSync(locks).sort()) {
      if (!name.endsWith(".marker")) continue;
      const path = join(locks, name);
      try {
        const details = lstatSync(path);
        if (!details.isFile() || details.isSymbolicLink() || details.nlink > 2 ||
            details.mtimeMs > cutoff) continue;
        const bytes = readFileSync(path, "utf8");
        const value = JSON.parse(bytes) as unknown;
        if (bytes !== canonicalJson(value) || !validLockMarker(value) ||
            name !== markerName(value) ||
            processOwnerState(value.pid, value.processStartIdentity) !== "dead") continue;
        const identity = filesystemIdentity(path);
        if (details.nlink === 2) {
          const lockPath = join(locks, `${lockStem(value)}.lock`);
          if (!exactRegularFile(lockPath, identity, bytes) ||
              !exactRegularFile(path, identity, bytes)) continue;
          unlinkSync(lockPath);
          fsyncDirectory(locks);
        }
        if (removeExactFile(path, identity, bytes)) removed += 1;
      } catch {
        // A concurrent bootstrap or maintenance pass won. Reinspect next time.
      }
    }
    if (removed > 0) fsyncDirectory(locks);
  } catch {
    return removed;
  }
  return removed;
}
