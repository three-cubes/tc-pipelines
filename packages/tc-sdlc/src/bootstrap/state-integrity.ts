import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  readlinkSync,
  unlinkSync,
} from "node:fs";
import { join, posix } from "node:path";

import { canonicalJson, digest } from "../canonical.js";
import { writeCanonicalEvidence } from "../evidence/index.js";

type StateMetadataEntry = Readonly<Record<string, string | number>>;

export type BootstrapStateMetadata = Readonly<{
  directoryIdentity: string;
  inventoryDigest: string;
  entries: readonly StateMetadataEntry[];
}>;

function metadataEntry(path: string, relativePath: string): StateMetadataEntry {
  const stat = lstatSync(path, { bigint: true });
  const common = {
    path: relativePath,
    mode: Number(stat.mode & 0o7777n),
    device: stat.dev.toString(),
    inode: stat.ino.toString(),
    size: stat.size.toString(),
    modified: stat.mtimeNs.toString(),
    changed: stat.ctimeNs.toString(),
    created: stat.birthtimeNs.toString(),
  };
  if (stat.isSymbolicLink()) {
    return { ...common, type: "symlink", target: readlinkSync(path) };
  }
  if (stat.isDirectory()) return { ...common, type: "directory" };
  if (stat.isFile()) return { ...common, type: "file" };
  throw new Error(`bootstrap state contains an unsupported filesystem entry: ${relativePath}`);
}

export function fileMetadataIdentity(path: string): string {
  return digest(metadataEntry(path, path));
}

export function stableDirectoryIdentity(path: string): string {
  const entry = metadataEntry(path, ".");
  if (entry.type !== "directory") throw new Error("bootstrap state generation is not a directory");
  return digest({
    type: entry.type,
    device: entry.device,
    inode: entry.inode,
  });
}

export function captureBootstrapStateMetadata(root: string): BootstrapStateMetadata {
  const rootEntry = metadataEntry(root, ".");
  if (rootEntry.type !== "directory") {
    throw new Error("bootstrap release state is not a real directory");
  }
  const entries: StateMetadataEntry[] = [rootEntry];
  const visit = (directory: string, prefix: string): void => {
    for (const name of readdirSync(directory).sort()) {
      const relativePath = prefix === "" ? name : posix.join(prefix, name);
      const path = join(directory, name);
      const entry = metadataEntry(path, relativePath);
      entries.push(entry);
      if (entry.type === "directory") visit(path, relativePath);
    }
  };
  visit(root, "");
  return {
    directoryIdentity: digest({
      type: rootEntry.type,
      device: rootEntry.device,
      inode: rootEntry.inode,
    }),
    inventoryDigest: digest(entries),
    entries,
  };
}

export function sameBootstrapStateMetadata(
  expected: BootstrapStateMetadata,
  observed: BootstrapStateMetadata,
): boolean {
  return canonicalJson(expected.entries) === canonicalJson(observed.entries);
}

function invalidationDirectory(stateRoot: string): string {
  return join(stateRoot, "invalidated");
}

function invalidationPath(stateRoot: string, stateKey: string): string {
  return join(invalidationDirectory(stateRoot), `${digest(stateKey).slice("sha256:".length)}.`);
}

function generationPath(stateRoot: string, stateKey: string, generationIdentity: string): string {
  return `${invalidationPath(stateRoot, stateKey)}${digest(generationIdentity).slice("sha256:".length)}.json`;
}

type InvalidationRecord = Readonly<{
  schema: "tc.sdlc/bootstrap-state-invalidation/v2";
  stateKey: string;
  poisonedDirectoryIdentity: string;
  expectedMetadata: string;
  observedMetadata: string;
}>;

function readInvalidationRecord(path: string, stateKey: string): Readonly<{
  record: InvalidationRecord;
  bytes: string;
}> {
  const stat = lstatSync(path);
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new Error("bootstrap state invalidation record is not a regular file");
  }
  const bytes = readFileSync(path, "utf8");
  const record = JSON.parse(bytes) as unknown;
  if (
    bytes !== canonicalJson(record) ||
    typeof record !== "object" || record === null ||
    (record as Record<string, unknown>).schema !== "tc.sdlc/bootstrap-state-invalidation/v2" ||
    (record as Record<string, unknown>).stateKey !== stateKey ||
    typeof (record as Record<string, unknown>).poisonedDirectoryIdentity !== "string" ||
    typeof (record as Record<string, unknown>).expectedMetadata !== "string" ||
    typeof (record as Record<string, unknown>).observedMetadata !== "string" ||
    path !== generationPath(
      posix.dirname(posix.dirname(path)),
      stateKey,
      (record as Record<string, unknown>).poisonedDirectoryIdentity as string,
    )
  ) {
    throw new Error("bootstrap state invalidation record is malformed");
  }
  return { record: record as InvalidationRecord, bytes };
}

export function bootstrapStateGenerationInvalidated(
  stateRoot: string,
  stateKey: string,
  stateDirectory: string,
): boolean {
  const directory = invalidationDirectory(stateRoot);
  if (!existsSync(directory)) return false;
  const directoryStat = lstatSync(directory);
  if (!directoryStat.isDirectory() || directoryStat.isSymbolicLink()) {
    throw new Error("bootstrap state invalidation registry is not a real directory");
  }
  const path = invalidationPath(stateRoot, stateKey);
  if (!existsSync(directory)) return false;
  const prefix = path.slice(directory.length + 1);
  const currentDirectoryIdentity = stableDirectoryIdentity(stateDirectory);
  for (const name of readdirSync(directory).sort()) {
    if (!name.startsWith(prefix) || !name.endsWith(".json")) continue;
    const { record } = readInvalidationRecord(join(directory, name), stateKey);
    if (currentDirectoryIdentity === record.poisonedDirectoryIdentity) return true;
  }
  return false;
}

export function assertBootstrapStateAdmitted(
  stateRoot: string,
  stateKey: string,
  stateDirectory: string,
): void {
  if (bootstrapStateGenerationInvalidated(stateRoot, stateKey, stateDirectory)) {
    throw new Error("bootstrap release state was invalidated by a previous execution");
  }
}

export function invalidateBootstrapState(
  stateRoot: string,
  stateKey: string,
  admittedDirectoryIdentity: string,
  expectedMetadata: string,
  observedMetadata: string,
  observedDirectoryIdentity?: string,
): void {
  const directory = invalidationDirectory(stateRoot);
  if (existsSync(directory)) {
    const stat = lstatSync(directory);
    if (!stat.isDirectory() || stat.isSymbolicLink()) {
      throw new Error("bootstrap state invalidation registry is not a real directory");
    }
  } else {
    mkdirSync(directory, { mode: 0o700 });
  }
  const poisonedIdentities = new Set([
    admittedDirectoryIdentity,
    ...(observedDirectoryIdentity === undefined ? [] : [observedDirectoryIdentity]),
  ]);
  for (const poisonedDirectoryIdentity of poisonedIdentities) {
    const path = generationPath(stateRoot, stateKey, poisonedDirectoryIdentity);
    writeCanonicalEvidence(path, {
      schema: "tc.sdlc/bootstrap-state-invalidation/v2",
      stateKey,
      poisonedDirectoryIdentity,
      expectedMetadata,
      observedMetadata,
    });
  }
}

/** Remove only the tombstone for a generation maintenance has just deleted exactly. */
export function retireBootstrapStateTombstone(
  stateRoot: string,
  stateKey: string,
  generationIdentity: string,
): boolean {
  const path = generationPath(stateRoot, stateKey, generationIdentity);
  if (!existsSync(path)) return false;
  const before = lstatSync(path, { bigint: true });
  const { record, bytes } = readInvalidationRecord(path, stateKey);
  if (record.poisonedDirectoryIdentity !== generationIdentity) return false;
  const current = lstatSync(path, { bigint: true });
  if (
    current.isSymbolicLink() || !current.isFile() ||
    current.dev !== before.dev || current.ino !== before.ino ||
    current.birthtimeNs !== before.birthtimeNs ||
    readFileSync(path, "utf8") !== bytes
  ) return false;
  unlinkSync(path);
  return true;
}
