import { readFileSync } from "node:fs";

import { parse } from "yaml";

import { SdlcError } from "../errors.js";
import { writeCanonicalEvidence } from "../evidence/index.js";
import type { ReleaseCatalogue, ReleaseEntry } from "../schema/types.js";
import { assertSchema } from "../schema/validation.js";

function assertCoherent(catalogue: ReleaseCatalogue): void {
  if (catalogue.release.package.version !== catalogue.release.version) {
    throw new SdlcError(
      "CATALOGUE_INCOHERENT",
      "release and package versions must be upgraded together",
    );
  }
}

export const CANONICAL_SDLC_FITNESS = {
  package: "three-cubes-fitness",
  version: "0.17.0",
} as const;

export const CANONICAL_SDLC_TOOLCHAINS = {
  node: "24",
  packageManager: "pnpm@11.22.0",
  python: "3.13",
  uv: "0.12.5",
} as const;

export type ReleaseCatalogueGeneration = Readonly<{
  releaseVersion: string;
  workflowCommit: string;
  imageDigest: string;
}>;

export function validateCatalogue(value: unknown): ReleaseCatalogue {
  assertSchema<ReleaseCatalogue>(
    "release-catalogue-v1.schema.json",
    value,
    "release catalogue",
  );
  assertCoherent(value);
  return value;
}

export function createReleaseCatalogue(release: ReleaseEntry): ReleaseCatalogue {
  return validateCatalogue({ schema: "tc.sdlc/release-catalogue/v1", release });
}

export function generateReleaseCatalogue(
  input: ReleaseCatalogueGeneration,
): ReleaseCatalogue {
  return createReleaseCatalogue({
    version: input.releaseVersion,
    package: {
      name: "@three-cubes/tc-sdlc",
      version: input.releaseVersion,
    },
    workflowCommit: input.workflowCommit,
    imageDigest: input.imageDigest,
    declarationSchema: "tc.sdlc/v1",
    lockSchema: "tc.sdlc/lock/v1",
    fitness: CANONICAL_SDLC_FITNESS,
    toolchains: CANONICAL_SDLC_TOOLCHAINS,
  });
}

export function writeReleaseCatalogue(
  path: string,
  catalogue: ReleaseCatalogue,
): void {
  writeCanonicalEvidence(path, validateCatalogue(catalogue));
}

export function loadCatalogue(path: string): ReleaseCatalogue {
  let parsed: unknown;
  try {
    parsed = parse(readFileSync(path, "utf8"), { uniqueKeys: true });
  } catch (error) {
    throw new SdlcError(
      "CATALOGUE_READ_FAILED",
      `could not read release catalogue ${path}: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
  return validateCatalogue(parsed);
}
