import { readFileSync } from "node:fs";

import { parse } from "yaml";

import { SdlcError } from "../errors.js";
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
