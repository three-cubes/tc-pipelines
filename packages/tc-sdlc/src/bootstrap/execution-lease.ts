import { randomUUID } from "node:crypto";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  unlinkSync,
} from "node:fs";
import { join, relative, resolve, sep } from "node:path";

import { canonicalJson } from "../canonical.js";
import { SdlcError } from "../errors.js";
import { writeCanonicalEvidence } from "../evidence/index.js";
import { processOwnerState, processStartIdentity } from "./process-identity.js";

const OWNER = "@three-cubes/tc-sdlc";
const OWNER_MARKER = {
  schema: "tc.sdlc/state-owner/v1",
  owner: OWNER,
} as const;
const LEASE_SCHEMA = "tc.sdlc/bootstrap-execution-lease/v1";

export type BootstrapStateIdentity = Readonly<{
  device: string;
  inode: string;
  birthtimeNanoseconds: string;
}>;

export type BootstrapExecutionLeaseMarker = Readonly<{
  schema: typeof LEASE_SCHEMA;
  owner: typeof OWNER;
  leaseId: string;
  stateKey: string;
  stateIdentity: BootstrapStateIdentity;
  pid: number;
  processStartIdentity: string;
  createdAtMs: number;
}>;

export type BootstrapExecutionLease = Readonly<{
  marker: BootstrapExecutionLeaseMarker;
  path: string;
  assertCurrent: () => void;
  release: () => void;
}>;

function identity(path: string): BootstrapStateIdentity {
  const details = lstatSync(path, { bigint: true });
  return {
    device: details.dev.toString(),
    inode: details.ino.toString(),
    birthtimeNanoseconds: details.birthtimeNs.toString(),
  };
}

function sameIdentity(left: BootstrapStateIdentity, right: BootstrapStateIdentity): boolean {
  return left.device === right.device &&
    left.inode === right.inode &&
    left.birthtimeNanoseconds === right.birthtimeNanoseconds;
}

function rejectLinkedPath(root: string, target: string): void {
  const suffix = relative(root, target);
  if (suffix === "" || suffix === ".." || suffix.startsWith(`..${sep}`)) {
    throw new Error("bootstrap execution lease path escapes its owned state root");
  }
  let cursor = root;
  for (const segment of suffix.split(sep)) {
    cursor = join(cursor, segment);
    if (!existsSync(cursor)) continue;
    const details = lstatSync(cursor);
    if (details.isSymbolicLink()) {
      throw new Error("bootstrap execution lease path traverses a symbolic link");
    }
  }
}

/** Publish a live lease before validating and using any executable in bootstrap state. */
export function acquireBootstrapExecutionLease(
  stateRootValue: string,
  stateKey: string,
): BootstrapExecutionLease {
  let leasePath: string | undefined;
  let leaseBytes: string | undefined;
  let leaseFileIdentity: BootstrapStateIdentity | undefined;
  try {
    if (
      stateKey.length === 0 ||
      stateKey.startsWith("/") ||
      stateKey.split("/").some((part) => part === "" || part === "." || part === "..")
    ) {
      throw new Error("bootstrap state key is unsafe");
    }
    const stateRoot = resolve(stateRootValue);
    const canonicalRoot = realpathSync(stateRoot);
    const rootDetails = lstatSync(canonicalRoot);
    if (!rootDetails.isDirectory() || rootDetails.isSymbolicLink()) {
      throw new Error("bootstrap state root is not a real directory");
    }
    const ownerBytes = readFileSync(join(canonicalRoot, ".tc-sdlc-owner.json"), "utf8");
    const owner = JSON.parse(ownerBytes) as unknown;
    if (ownerBytes !== canonicalJson(owner) || canonicalJson(owner) !== canonicalJson(OWNER_MARKER)) {
      throw new Error("bootstrap state root is not owned by tc-sdlc");
    }

    const stateDirectory = resolve(canonicalRoot, stateKey);
    rejectLinkedPath(canonicalRoot, stateDirectory);
    const stateDetails = lstatSync(stateDirectory);
    if (!stateDetails.isDirectory() || stateDetails.isSymbolicLink()) {
      throw new Error("bootstrap release state is not a real directory");
    }
    const stateIdentity = identity(stateDirectory);
    const processIdentity = processStartIdentity(process.pid);
    if (processIdentity === undefined) {
      throw new Error("current process start identity could not be established");
    }

    const references = join(canonicalRoot, "references");
    const leases = join(references, "leases");
    if (existsSync(references)) {
      const referencesDetails = lstatSync(references);
      if (!referencesDetails.isDirectory() || referencesDetails.isSymbolicLink()) {
        throw new Error("bootstrap reference authority path is not a real directory");
      }
    }
    mkdirSync(leases, { recursive: true, mode: 0o700 });
    rejectLinkedPath(canonicalRoot, leases);
    if (!lstatSync(leases).isDirectory()) throw new Error("bootstrap execution lease path is invalid");

    const leaseId = randomUUID();
    const marker: BootstrapExecutionLeaseMarker = {
      schema: LEASE_SCHEMA,
      owner: OWNER,
      leaseId,
      stateKey,
      stateIdentity,
      pid: process.pid,
      processStartIdentity: processIdentity,
      createdAtMs: Date.now(),
    };
    leasePath = join(leases, `${leaseId}.json`);
    leaseBytes = canonicalJson(marker);
    writeCanonicalEvidence(leasePath, marker);
    leaseFileIdentity = identity(leasePath);

    const assertCurrent = (): void => {
      try {
        if (realpathSync(resolve(stateRootValue)) !== canonicalRoot) {
          throw new Error("bootstrap state root path was replaced");
        }
        if (processOwnerState(marker.pid, marker.processStartIdentity) !== "live") {
          throw new Error("bootstrap lease process identity is no longer live");
        }
        rejectLinkedPath(canonicalRoot, stateDirectory);
        if (!sameIdentity(identity(stateDirectory), stateIdentity)) {
          throw new Error("bootstrap release state directory was replaced");
        }
        rejectLinkedPath(canonicalRoot, leasePath!);
        if (!sameIdentity(identity(leasePath!), leaseFileIdentity!) ||
            readFileSync(leasePath!, "utf8") !== leaseBytes) {
          throw new Error("bootstrap execution lease was replaced");
        }
      } catch (error) {
        throw new SdlcError(
          "BOOTSTRAP_LEASE_INVALID",
          `bootstrap execution lease is no longer valid: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
    };

    const release = (): void => {
      if (leasePath === undefined) return;
      try {
        if (leaseFileIdentity !== undefined && leaseBytes !== undefined &&
            sameIdentity(identity(leasePath), leaseFileIdentity) &&
            readFileSync(leasePath, "utf8") === leaseBytes) {
          unlinkSync(leasePath);
        }
      } catch {
        // A missing or replaced lease is never authority to remove a foreign path.
      }
    };
    assertCurrent();
    return { marker, path: leasePath, assertCurrent, release };
  } catch (error) {
    if (leasePath !== undefined && leaseFileIdentity !== undefined && leaseBytes !== undefined) {
      try {
        if (sameIdentity(identity(leasePath), leaseFileIdentity) &&
            readFileSync(leasePath, "utf8") === leaseBytes) {
          unlinkSync(leasePath);
        }
      } catch {
        // The lease did not become ours or the file has already disappeared.
      }
    }
    if (error instanceof SdlcError) throw error;
    throw new SdlcError(
      "BOOTSTRAP_LEASE_INVALID",
      `could not acquire bootstrap execution lease: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}
