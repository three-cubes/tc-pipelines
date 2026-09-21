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

export const CANONICAL_SDLC_TOOLCHAINS = {
  node: "24",
  packageManager: "pnpm@11.22.0",
  python: "3.13",
  uv: "0.12.5",
} as const;

export const CANONICAL_SDLC_BOOTSTRAP = {
  uv: {
    package: "uv",
    version: "0.12.5",
    wheels: {
      "darwin-arm64": {
        url: "https://files.pythonhosted.org/packages/6d/bc/81ab953b7261ae6be40874b1f283a10873871e02eb353d354614dd8da96b/uv-0.12.5-py3-none-macosx_11_0_arm64.whl",
        sha256: "d87156bc174d94fae890bb7a261e2867140abb9fe1e9de81a5295e582fb9d0f5",
      },
      "darwin-x64": {
        url: "https://files.pythonhosted.org/packages/bd/ec/d76387b388fa21620088b89b9c67f2596a707add585104e0cb5e8abf55f2/uv-0.12.5-py3-none-macosx_10_12_x86_64.whl",
        sha256: "1a06c8bc4d43b5f6c1e3f2ae3d0f6455b07515f762516f95e52e6c0cbccedf15",
      },
      "linux-arm64": {
        url: "https://files.pythonhosted.org/packages/7d/13/07585043c10e648820bf826474dac46864ce6691da5dc52fee43c5c7523a/uv-0.12.5-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.musllinux_1_1_aarch64.whl",
        sha256: "2d65b7b3bc3fd28678f62aa7fb5d90f106ad9782c1354af60b6cecdf9ea9ecd9",
      },
      "linux-x64": {
        url: "https://files.pythonhosted.org/packages/93/22/dacc9a0bc8604187a1ba954a3aef8329e4104eb0af772d2c3c634893bd9b/uv-0.12.5-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
        sha256: "3e195ccf1ed60c8bb24a6447ce306441a4181d54b602407e09bc56e963911c15",
      },
    },
  },
} as const;

export type ReleaseCatalogueGeneration = Readonly<{
  releaseVersion: string;
  fitnessVersion: string;
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
    fitness: { package: "three-cubes-fitness", version: input.fitnessVersion },
    toolchains: CANONICAL_SDLC_TOOLCHAINS,
    bootstrap: CANONICAL_SDLC_BOOTSTRAP,
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
