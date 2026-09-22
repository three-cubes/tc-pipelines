import { spawnSync } from "node:child_process";
import {
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  utimesSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, test } from "vitest";

import { canonicalJson } from "../../src/canonical.js";
import {
  acquireBootstrapReferenceCommitLock,
  releaseBootstrapReferenceCommitLock,
} from "../../src/bootstrap/reference-lock.js";
import {
  commitBootstrapReference,
  writePendingBootstrapReference,
} from "../../src/bootstrap/references.js";
import {
  processOwnerState,
  processStartIdentity,
} from "../../src/bootstrap/process-identity.js";
import {
  cleanupExpiredDeadPending,
  leaseMatches,
  readBootstrapReferenceAuthorities,
} from "../../src/bootstrap/references.js";
import { inspectBootstrapStates } from "../../src/maintenance/bootstrap-state.js";

const roots: string[] = [];

function filesystemIdentity(path: string) {
  const details = lstatSync(path, { bigint: true });
  return {
    device: details.dev.toString(),
    inode: details.ino.toString(),
    birthtimeNanoseconds: details.birthtimeNs.toString(),
  };
}

function expiredState(root: string, stateKey: string): string {
  const directory = join(root, stateKey);
  mkdirSync(directory, { recursive: true });
  writeFileSync(join(directory, "state.json"), canonicalJson({
    schema: "tc.sdlc/bootstrap-state/v6",
    release: "3.0.0",
    lockDigest: `sha256:${"a".repeat(64)}`,
    dependencyDigest: `sha256:${"b".repeat(64)}`,
    platform: "darwin",
    architecture: "arm64",
    adapters: [],
    dependencies: [],
  }));
  const old = new Date(Date.now() - 49 * 60 * 60 * 1_000);
  utimesSync(directory, old, old);
  return directory;
}

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

describe("bootstrap execution lease retention", () => {
  test("maintenance retains an expired state while a live execution lease names it", async () => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-leased-bootstrap-"));
    roots.push(root);
    writeFileSync(join(root, ".tc-sdlc-owner.json"), canonicalJson({
      schema: "tc.sdlc/state-owner/v1",
      owner: "@three-cubes/tc-sdlc",
    }));
    const leasedKey = "releases/3.0.0/leased/darwin-arm64";
    const referencedKey = "releases/3.0.0/referenced/darwin-arm64";
    const unleasedKey = "releases/3.0.0/unleased/darwin-arm64";
    const leased = expiredState(root, leasedKey);
    const referenced = expiredState(root, referencedKey);
    expiredState(root, unleasedKey);
    const consumer = "fixture-consumer";
    const consumerRoot = root;
    const publication = writePendingBootstrapReference(
      root,
      consumer,
      consumerRoot,
      referencedKey,
      filesystemIdentity(referenced),
    );
    const commitLock = await acquireBootstrapReferenceCommitLock(root, publication);
    commitBootstrapReference(root, publication, commitLock);
    releaseBootstrapReferenceCommitLock(commitLock);

    const leaseId = "6c58bdb7-1a70-4a2e-b4c1-660a5d8c4db6";
    const leaseDirectory = join(root, "references", "leases");
    mkdirSync(leaseDirectory, { recursive: true });
    writeFileSync(join(leaseDirectory, `${leaseId}.json`), canonicalJson({
      schema: "tc.sdlc/bootstrap-execution-lease/v1",
      owner: "@three-cubes/tc-sdlc",
      leaseId,
      stateKey: leasedKey,
      stateIdentity: filesystemIdentity(leased),
      pid: process.pid,
      processStartIdentity: processStartIdentity(process.pid),
      createdAtMs: Date.now(),
    }));

    const inspection = inspectBootstrapStates(root, Date.now() - 48 * 60 * 60 * 1_000);

    expect(inspection.candidates.some((entry) => entry.path === leasedKey)).toBe(false);
    expect(inspection.candidates.some((entry) => entry.path === unleasedKey)).toBe(true);
    expect(inspection.retained).toContainEqual({ path: leasedKey, reason: "leased" });
  });

  test("a SIGKILL after lease publication leaves complete recoverable evidence", async () => {
    const root = mkdtempSync(join(tmpdir(), "tc-sdlc-killed-lease-"));
    roots.push(root);
    writeFileSync(join(root, ".tc-sdlc-owner.json"), canonicalJson({
      schema: "tc.sdlc/state-owner/v1",
      owner: "@three-cubes/tc-sdlc",
    }));
    const stateKey = "releases/3.0.0/killed/darwin-arm64";
    const stateDirectory = expiredState(root, stateKey);
    const moduleUrl = new URL("../../dist/bootstrap/execution-lease.js", import.meta.url).href;
    const script = `import { acquireBootstrapExecutionLease } from ${JSON.stringify(moduleUrl)};\n` +
      `acquireBootstrapExecutionLease(process.argv[1], process.argv[2]);\n` +
      `process.kill(process.pid, "SIGKILL");\n`;
    const child = spawnSync(process.execPath, ["--input-type=module", "-e", script, root, stateKey], {
      encoding: "utf8",
      timeout: 5_000,
    });
    expect(child.signal).toBe("SIGKILL");

    const leases = join(root, "references", "leases");
    const [name] = readdirSync(leases);
    expect(name).toMatch(/^[0-9a-f-]+\.json$/);
    const markerPath = join(leases, name!);
    const bytes = readFileSync(markerPath, "utf8");
    const marker = JSON.parse(bytes);
    expect(bytes).toBe(canonicalJson(marker));
    expect(processOwnerState(marker.pid, marker.processStartIdentity)).toBe("dead");
    const authorities = readBootstrapReferenceAuthorities(root);
    expect(leaseMatches(authorities, stateKey, filesystemIdentity(stateDirectory))).toBe(true);

    const old = Date.now() - 49 * 60 * 60 * 1_000;
    writeFileSync(markerPath, canonicalJson({ ...marker, createdAtMs: old }));
    utimesSync(markerPath, new Date(old), new Date(old));
    expect(await cleanupExpiredDeadPending(root, Date.now() - 48 * 60 * 60 * 1_000)).toBe(1);
    expect(readdirSync(leases)).toEqual([]);
  });
});
