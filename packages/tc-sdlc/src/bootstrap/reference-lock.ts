import { randomUUID } from "node:crypto";
import { createServer, type Server } from "node:net";
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
const RECOVERY_SCHEMA = "tc.sdlc/bootstrap-reference-recovery-boundary/v1";
const RECOVERY_PORT_BASE = 10_000;
const RECOVERY_PORT_COUNT = 20_000;

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

type BootstrapReferenceRecoveryMarker = Readonly<{
  schema: typeof RECOVERY_SCHEMA;
  owner: typeof OWNER;
  phase: "held";
  token: string;
  consumer: string;
  consumerRoot: string;
  pid: number;
  processStartIdentity: string;
  port: number;
  createdAtMs: number;
}>;

type BootstrapReferenceRecoveryBoundary = Readonly<{
  server: Server;
  markerPath: string;
  value: BootstrapReferenceRecoveryMarker;
  bytes: string;
  identity: FilesystemIdentity;
}>;

type ReferenceConsumer = Readonly<{ consumer: string; consumerRoot: string }>;

export type BootstrapReferenceCommitLock = Readonly<{
  path: string;
  markerPath: string;
  value: BootstrapReferenceCommitLockMarker;
  bytes: string;
  identity: FilesystemIdentity;
  recovery: BootstrapReferenceRecoveryBoundary;
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

function validRecoveryMarker(value: unknown): value is BootstrapReferenceRecoveryMarker {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return record.schema === RECOVERY_SCHEMA && record.owner === OWNER &&
    record.phase === "held" && validUuid(record.token) &&
    typeof record.consumer === "string" && record.consumer.length > 0 &&
    typeof record.consumerRoot === "string" && isAbsolute(record.consumerRoot) &&
    Number.isSafeInteger(record.pid) && Number(record.pid) > 0 &&
    typeof record.processStartIdentity === "string" && record.processStartIdentity.length > 0 &&
    Number.isSafeInteger(record.port) && Number(record.port) >= RECOVERY_PORT_BASE &&
    Number(record.port) < RECOVERY_PORT_BASE + RECOVERY_PORT_COUNT &&
    Number.isSafeInteger(record.createdAtMs);
}

function lockStem(value: Pick<BootstrapReferenceCommitLockMarker, "consumer" | "consumerRoot">): string {
  return digest({ consumer: value.consumer, consumerRoot: value.consumerRoot }).slice("sha256:".length);
}

function markerName(value: BootstrapReferenceCommitLockMarker): string {
  return `${lockStem(value)}.${value.token}.marker`;
}

function recoveryMarkerName(value: BootstrapReferenceRecoveryMarker): string {
  return `${lockStem(value)}.${value.token}.recovery`;
}

function recoveryPort(
  stateRoot: string,
  value: Pick<BootstrapReferenceCommitLockMarker, "consumer" | "consumerRoot">,
): number {
  const hexadecimal = digest({
    boundary: "bootstrap-reference-recovery",
    stateRoot,
    consumer: value.consumer,
    consumerRoot: value.consumerRoot,
  }).slice("sha256:".length, "sha256:".length + 8);
  return RECOVERY_PORT_BASE + Number.parseInt(hexadecimal, 16) % RECOVERY_PORT_COUNT;
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

async function bindRecoveryServer(port: number): Promise<Server> {
  const server = createServer();
  return await new Promise<Server>((resolve, reject) => {
    const failed = (error: Error): void => {
      server.removeListener("listening", listening);
      reject(error);
    };
    const listening = (): void => {
      server.removeListener("error", failed);
      resolve(server);
    };
    server.once("error", failed);
    server.once("listening", listening);
    server.listen({ host: "127.0.0.1", port, exclusive: true });
  });
}

async function acquireRecoveryBoundary(
  stateRoot: string,
  locks: string,
  publication: Readonly<{ value: ReferenceConsumer }>,
): Promise<BootstrapReferenceRecoveryBoundary> {
  const port = recoveryPort(stateRoot, publication.value);
  const deadline = Date.now() + LOCK_WAIT_MILLISECONDS;
  let server: Server | undefined;
  while (server === undefined) {
    try {
      server = await bindRecoveryServer(port);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EADDRINUSE") {
        throw new BootstrapReferenceCommitError(
          "invalid",
          "bootstrap reference recovery boundary could not be acquired",
        );
      }
      if (Date.now() >= deadline) {
        throw new BootstrapReferenceCommitError(
          "busy",
          "another live or ambiguous process owns the reference recovery boundary",
        );
      }
      await new Promise((resolve) => setTimeout(resolve, LOCK_RETRY_MILLISECONDS));
    }
  }
  const startIdentity = processStartIdentity(process.pid);
  if (startIdentity === undefined) {
    server.close();
    throw new BootstrapReferenceCommitError(
      "invalid",
      "current process start identity could not be established",
    );
  }
  const value: BootstrapReferenceRecoveryMarker = {
    schema: RECOVERY_SCHEMA,
    owner: OWNER,
    phase: "held",
    token: randomUUID(),
    consumer: publication.value.consumer,
    consumerRoot: publication.value.consumerRoot,
    pid: process.pid,
    processStartIdentity: startIdentity,
    port,
    createdAtMs: Date.now(),
  };
  const markerPath = join(locks, recoveryMarkerName(value));
  try {
    writeCanonicalEvidence(markerPath, value);
    return {
      server,
      markerPath,
      value,
      bytes: canonicalJson(value),
      identity: filesystemIdentity(markerPath),
    };
  } catch (error) {
    server.close();
    throw error;
  }
}

function assertRecoveryBoundary(boundary: BootstrapReferenceRecoveryBoundary): void {
  if (!boundary.server.listening ||
      !exactRegularFile(boundary.markerPath, boundary.identity, boundary.bytes)) {
    throw new BootstrapReferenceCommitError(
      "invalid",
      "bootstrap reference recovery boundary changed while held",
    );
  }
}

function releaseRecoveryBoundary(boundary: BootstrapReferenceRecoveryBoundary): void {
  let failure: unknown;
  try {
    if (!exactRegularFile(boundary.markerPath, boundary.identity, boundary.bytes)) {
      throw new BootstrapReferenceCommitError(
        "invalid",
        "bootstrap reference recovery marker changed during release",
      );
    }
    unlinkSync(boundary.markerPath);
    fsyncDirectory(dirname(boundary.markerPath));
  } catch (error) {
    failure = error;
  }
  try {
    boundary.server.close();
  } catch (error) {
    failure ??= error;
  }
  if (failure !== undefined) throw failure;
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
  const recovery = await acquireRecoveryBoundary(stateRoot, locks, publication);
  const startIdentity = processStartIdentity(process.pid);
  if (startIdentity === undefined) {
    releaseRecoveryBoundary(recovery);
    throw new BootstrapReferenceCommitError(
      "invalid",
      "current process start identity could not be established",
    );
  }
  const value: BootstrapReferenceCommitLockMarker = {
    schema: LOCK_SCHEMA,
    owner: OWNER,
    phase: "held",
    token: randomUUID(),
    transaction: publication.value.transaction,
    consumer: publication.value.consumer,
    consumerRoot: publication.value.consumerRoot,
    pid: process.pid,
    processStartIdentity: startIdentity,
    createdAtMs: Date.now(),
  };
  const markerPath = join(locks, markerName(value));
  let lock: BootstrapReferenceCommitLock | undefined;
  let acquired = false;
  try {
    writeCanonicalEvidence(markerPath, value);
    lock = {
      path,
      markerPath,
      value,
      bytes: canonicalJson(value),
      identity: filesystemIdentity(markerPath),
      recovery,
    };
    const deadline = Date.now() + LOCK_WAIT_MILLISECONDS;
    while (true) {
      try {
        linkSync(markerPath, path);
        fsyncDirectory(locks);
        assertBootstrapReferenceCommitLock(lock);
        acquired = true;
        return lock;
      } catch (error) {
        if (error instanceof BootstrapReferenceCommitError) throw error;
        if ((error as NodeJS.ErrnoException).code !== "EEXIST") {
          throw new BootstrapReferenceCommitError(
            "invalid",
            "bootstrap reference commit lock could not be acquired",
          );
        }
        const existing = inspectExistingLock(path, locks, publication);
        const ownerState = processOwnerState(
          existing.value.pid,
          existing.value.processStartIdentity,
        );
        if (ownerState === "dead") {
          recoverDeadLock(path, locks, existing);
          continue;
        }
        if (Date.now() >= deadline) {
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
  } finally {
    if (!acquired) {
      if (lock !== undefined) discardOwnMarker(lock);
      releaseRecoveryBoundary(recovery);
    }
  }
}

export function assertBootstrapReferenceCommitLock(
  lock: BootstrapReferenceCommitLock,
): void {
  assertRecoveryBoundary(lock.recovery);
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
  let failure: unknown;
  try {
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
  } catch (error) {
    failure = error;
  }
  try {
    releaseRecoveryBoundary(lock.recovery);
  } catch (error) {
    failure ??= error;
  }
  if (failure !== undefined) throw failure;
}

type ExpiredMarker = Readonly<{
  bytes: string;
  identity: FilesystemIdentity;
  links: number;
}>;

function expiredMarker(path: string, cutoff: number): ExpiredMarker | undefined {
  const details = lstatSync(path);
  if (!details.isFile() || details.isSymbolicLink() || details.mtimeMs > cutoff) return undefined;
  return {
    bytes: readFileSync(path, "utf8"),
    identity: filesystemIdentity(path),
    links: details.nlink,
  };
}

async function cleanupRecoveryMarker(
  stateRoot: string,
  locks: string,
  name: string,
  cutoff: number,
): Promise<boolean> {
  const path = join(locks, name);
  const marker = expiredMarker(path, cutoff);
  if (marker === undefined) return false;
  const value = JSON.parse(marker.bytes) as unknown;
  if (marker.bytes !== canonicalJson(value) || !validRecoveryMarker(value) ||
      name !== recoveryMarkerName(value) ||
      processOwnerState(value.pid, value.processStartIdentity) !== "dead") return false;
  const boundary = await acquireRecoveryBoundary(stateRoot, locks, { value });
  try {
    return removeExactFile(path, marker.identity, marker.bytes);
  } finally {
    releaseRecoveryBoundary(boundary);
  }
}

async function cleanupCommitMarker(
  stateRoot: string,
  locks: string,
  name: string,
  cutoff: number,
): Promise<boolean> {
  const path = join(locks, name);
  const marker = expiredMarker(path, cutoff);
  if (marker === undefined || marker.links > 2) return false;
  const value = JSON.parse(marker.bytes) as unknown;
  if (marker.bytes !== canonicalJson(value) || !validLockMarker(value) ||
      name !== markerName(value) ||
      processOwnerState(value.pid, value.processStartIdentity) !== "dead") return false;
  const boundary = await acquireRecoveryBoundary(stateRoot, locks, { value });
  try {
    const refreshed = expiredMarker(path, cutoff);
    if (refreshed === undefined || refreshed.links > 2 ||
        !exactIdentity(refreshed.identity, marker.identity) ||
        refreshed.bytes !== marker.bytes ||
        processOwnerState(value.pid, value.processStartIdentity) !== "dead") return false;
    if (refreshed.links === 2) {
      const lockPath = join(locks, `${lockStem(value)}.lock`);
      if (!exactRegularFile(lockPath, marker.identity, marker.bytes)) return false;
      unlinkSync(lockPath);
      fsyncDirectory(locks);
    }
    return removeExactFile(path, marker.identity, marker.bytes);
  } finally {
    releaseRecoveryBoundary(boundary);
  }
}

export async function cleanupExpiredDeadReferenceLockMarkers(
  stateRoot: string,
  cutoff: number,
): Promise<number> {
  const locks = join(stateRoot, "references", "locks");
  let removed = 0;
  try {
    safeOwnedPath(stateRoot, locks);
    const root = lstatSync(locks);
    if (!root.isDirectory() || root.isSymbolicLink()) return 0;
    for (const name of readdirSync(locks).sort()) {
      try {
        const didRemove = name.endsWith(".recovery")
          ? await cleanupRecoveryMarker(stateRoot, locks, name, cutoff)
          : name.endsWith(".marker")
            ? await cleanupCommitMarker(stateRoot, locks, name, cutoff)
            : false;
        if (didRemove) removed += 1;
      } catch {
        // Live, ambiguous, changed or contended evidence is retained.
      }
    }
    if (removed > 0) fsyncDirectory(locks);
  } catch {
    return removed;
  }
  return removed;
}
