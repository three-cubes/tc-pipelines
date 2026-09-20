import { readFileSync, writeFileSync } from "node:fs";

import { canonicalJson, digest } from "../canonical.js";
import { validateCatalogue } from "../catalogue/index.js";
import { SdlcError } from "../errors.js";
import { validateDeclaration } from "../schema/declaration.js";
import type { ReleaseCatalogue, SdlcDeclaration, SdlcLock } from "../schema/types.js";
import { assertSchema } from "../schema/validation.js";

function sameRecord(
  left: Readonly<Record<string, string>>,
  right: Readonly<Record<string, string>>,
): boolean {
  return canonicalJson(left) === canonicalJson(right);
}

function assertCoordinated(
  declaration: SdlcDeclaration,
  catalogue: ReleaseCatalogue,
): void {
  const release = catalogue.release;
  if (declaration.schema !== release.declarationSchema) {
    throw new SdlcError(
      "COORDINATED_UPGRADE_REQUIRED",
      "declaration and release catalogue schema versions do not match",
    );
  }
  if (!sameRecord(declaration.toolchains, release.toolchains)) {
    throw new SdlcError(
      "COORDINATED_UPGRADE_REQUIRED",
      "declaration and release catalogue toolchains must be upgraded together",
    );
  }
  if (!sameRecord(declaration.fitness, release.fitness)) {
    throw new SdlcError(
      "COORDINATED_UPGRADE_REQUIRED",
      "declaration and release catalogue fitness versions must be upgraded together",
    );
  }
}

export function resolveLock(
  declarationValue: SdlcDeclaration,
  catalogueValue: ReleaseCatalogue,
): SdlcLock {
  const declaration = validateDeclaration(declarationValue);
  const catalogue = validateCatalogue(catalogueValue);
  assertCoordinated(declaration, catalogue);
  const release = catalogue.release;
  return {
    schema: release.lockSchema,
    declarationDigest: digest(declaration),
    catalogueDigest: digest(catalogue),
    release: release.version,
    package: release.package,
    workflowCommit: release.workflowCommit,
    imageDigest: release.imageDigest,
    declarationSchema: release.declarationSchema,
    fitness: release.fitness,
    toolchains: release.toolchains,
  };
}

export function writeLock(path: string, lock: SdlcLock): void {
  assertSchema<SdlcLock>("tc-sdlc-lock-v1.schema.json", lock, "lock");
  writeFileSync(path, canonicalJson(lock));
}

export function loadLock(path: string): Readonly<{ lock: SdlcLock; bytes: string }> {
  let bytes: string;
  let parsed: unknown;
  try {
    bytes = readFileSync(path, "utf8");
    parsed = JSON.parse(bytes) as unknown;
  } catch (error) {
    throw new SdlcError(
      "LOCK_READ_FAILED",
      `could not read lock ${path}: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
  assertSchema<SdlcLock>("tc-sdlc-lock-v1.schema.json", parsed, "lock");
  if (bytes !== canonicalJson(parsed)) {
    throw new SdlcError("LOCK_NON_CANONICAL", "lock bytes are not canonical");
  }
  return { lock: parsed, bytes };
}

export function assertCurrentLock(
  actual: SdlcLock,
  declaration: SdlcDeclaration,
  catalogue: ReleaseCatalogue,
): void {
  const expected = resolveLock(declaration, catalogue);
  if (canonicalJson(actual) !== canonicalJson(expected)) {
    throw new SdlcError(
      "LOCK_STALE",
      "lock does not match the current declaration and release catalogue",
    );
  }
}
