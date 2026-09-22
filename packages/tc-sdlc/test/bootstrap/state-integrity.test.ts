import {
  mkdtempSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  utimesSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, test } from "vitest";

import {
  assertBootstrapStateAdmitted,
  bootstrapStateGenerationInvalidated,
  captureBootstrapStateMetadata,
  fileMetadataIdentity,
  invalidateBootstrapState,
  retireBootstrapStateTombstone,
  sameBootstrapStateMetadata,
  stableDirectoryIdentity,
} from "../../src/bootstrap/state-integrity.js";

describe("bootstrap state integrity snapshots", () => {
  test("detects ordinary same-size content edits and poisons later admissions", () => {
    const stateRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-state-integrity-"));
    const stateDirectory = join(stateRoot, "releases", "fixture");
    mkdirSync(stateDirectory, { recursive: true });
    const dependency = join(stateDirectory, "dependencies", "uv", "bin", "tool");
    mkdirSync(join(stateDirectory, "dependencies", "uv", "bin"), { recursive: true });
    writeFileSync(dependency, "before\n");
    const before = captureBootstrapStateMetadata(stateDirectory);

    writeFileSync(dependency, "after!\n");
    const after = captureBootstrapStateMetadata(stateDirectory);
    expect(readFileSync(dependency, "utf8")).toBe("after!\n");
    expect(sameBootstrapStateMetadata(before, after)).toBe(false);
    invalidateBootstrapState(
      stateRoot,
      "releases/fixture",
      before.directoryIdentity,
      before.inventoryDigest,
      after.inventoryDigest,
    );

    expect(() => assertBootstrapStateAdmitted(stateRoot, "releases/fixture", stateDirectory)).toThrow(
      "bootstrap release state was invalidated by a previous execution",
    );
  });

  test("keeps a generation tombstone through rename metadata changes and retires only its deleted payload", () => {
    const stateRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-state-rebuild-"));
    const stateKey = "releases/fixture";
    const stateDirectory = join(stateRoot, stateKey);
    mkdirSync(stateDirectory, { recursive: true });
    writeFileSync(join(stateDirectory, "state.json"), "poisoned\n");
    const poisoned = captureBootstrapStateMetadata(stateDirectory);
    invalidateBootstrapState(
      stateRoot,
      stateKey,
      poisoned.directoryIdentity,
      poisoned.inventoryDigest,
      "sha256:observed-poisoned-state",
    );
    expect(() => assertBootstrapStateAdmitted(stateRoot, stateKey, stateDirectory)).toThrow(
      "bootstrap release state was invalidated by a previous execution",
    );

    const oldDirectory = join(stateRoot, "quarantine");
    mkdirSync(oldDirectory);
    const oldState = join(oldDirectory, "state");
    renameSync(stateDirectory, oldState);
    const stableAfterRename = stableDirectoryIdentity(oldState);
    const fullMetadataBefore = fileMetadataIdentity(oldState);
    const changed = new Date(Date.now() - 60_000);
    utimesSync(oldState, changed, changed);
    expect(stableAfterRename).toBe(poisoned.directoryIdentity);
    expect(stableDirectoryIdentity(oldState)).toBe(poisoned.directoryIdentity);
    expect(fileMetadataIdentity(oldState)).not.toBe(fullMetadataBefore);
    expect(bootstrapStateGenerationInvalidated(stateRoot, stateKey, oldState)).toBe(true);

    mkdirSync(stateDirectory);
    writeFileSync(join(stateDirectory, "state.json"), "poisoned\n");
    expect(readFileSync(join(stateDirectory, "state.json"), "utf8")).toBe("poisoned\n");
    expect(captureBootstrapStateMetadata(stateDirectory).directoryIdentity).not.toBe(poisoned.directoryIdentity);
    expect(() => assertBootstrapStateAdmitted(stateRoot, stateKey, stateDirectory)).not.toThrow();
    expect(readdirSync(join(stateRoot, "invalidated"))).toHaveLength(1);
    rmSync(oldDirectory, { recursive: true, force: true });
    expect(retireBootstrapStateTombstone(
      stateRoot,
      stateKey,
      poisoned.directoryIdentity,
    )).toBe(true);
    expect(readdirSync(join(stateRoot, "invalidated"))).toEqual([]);
  });

  test("tombstones both admitted and byte-identical replacement generations", () => {
    const stateRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-state-replacement-"));
    const stateKey = "releases/replaced";
    const stateDirectory = join(stateRoot, stateKey);
    mkdirSync(stateDirectory, { recursive: true });
    writeFileSync(join(stateDirectory, "state.json"), "same bytes\n");
    const admitted = captureBootstrapStateMetadata(stateDirectory);
    const replacement = join(stateRoot, "replacement");
    mkdirSync(replacement);
    writeFileSync(join(replacement, "state.json"), "same bytes\n");
    const observed = captureBootstrapStateMetadata(replacement);
    expect(readFileSync(join(replacement, "state.json"), "utf8")).toBe(
      readFileSync(join(stateDirectory, "state.json"), "utf8"),
    );
    expect(observed.directoryIdentity).not.toBe(admitted.directoryIdentity);

    invalidateBootstrapState(
      stateRoot,
      stateKey,
      admitted.directoryIdentity,
      admitted.inventoryDigest,
      observed.inventoryDigest,
      observed.directoryIdentity,
    );

    expect(bootstrapStateGenerationInvalidated(stateRoot, stateKey, stateDirectory)).toBe(true);
    expect(bootstrapStateGenerationInvalidated(stateRoot, stateKey, replacement)).toBe(true);
    expect(readdirSync(join(stateRoot, "invalidated"))).toHaveLength(2);
  });

  test("detects new and replaced entries without re-reading dependency bytes", () => {
    const stateRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-state-integrity-"));
    const stateDirectory = join(stateRoot, "releases", "fixture");
    mkdirSync(stateDirectory, { recursive: true });
    const dependency = join(stateDirectory, "dependency");
    writeFileSync(dependency, "first\n");
    const before = captureBootstrapStateMetadata(stateDirectory);
    writeFileSync(join(stateDirectory, "new-file"), "added\n");
    expect(sameBootstrapStateMetadata(before, captureBootstrapStateMetadata(stateDirectory))).toBe(false);
  });
});
