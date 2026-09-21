import { spawnSync } from "node:child_process";
import {
  accessSync,
  constants,
  existsSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, relative, resolve } from "node:path";

import { canonicalJson } from "../canonical.js";
import { SdlcError } from "../errors.js";
import { writeCanonicalEvidence } from "../evidence/index.js";
import { assertSchema } from "../schema/validation.js";

const OWNER = { schema: "tc.sdlc/evidence-owner/v1", owner: "@three-cubes/tc-sdlc" } as const;
const STATE_OWNER = { schema: "tc.sdlc/state-owner/v1", owner: "@three-cubes/tc-sdlc" } as const;
const LIFECYCLE = {
  class: "release-artifact-evidence",
  owner: "@three-cubes/tc-sdlc",
  retain: "catalogue-current-predecessor-or-incident-reference",
} as const;
const PROCESS_TIMEOUT_MS = 30_000;

export type ImageReleaseReceipt = Readonly<{
  schema: "tc.sdlc/image-release/v1";
  status: "succeeded" | "failed";
  reason: string | null;
  sourceCommit: string;
  registryCandidate: string;
  imageDigest: string | null;
  image: string | null;
  platforms: readonly ("linux/amd64" | "linux/arm64")[];
  reused: boolean;
  artifacts: Readonly<Record<string, string>>;
  lifecycle: typeof LIFECYCLE;
}>;

export type ProduceImageOptions = Readonly<{
  sourceRoot: string;
  sourceCommit: string;
  dockerfile: string;
  registryCandidate: string;
  dockerEndpoint: string;
  buildxExecutable: string;
  stateRoot: string;
  outputDirectory: string;
  receiptPath: string;
}>;

function failedReceipt(options: ProduceImageOptions, reason: string): ImageReleaseReceipt {
  return {
    schema: "tc.sdlc/image-release/v1",
    status: "failed",
    reason,
    sourceCommit: options.sourceCommit,
    registryCandidate: options.registryCandidate,
    imageDigest: null,
    image: null,
    platforms: [],
    reused: false,
    artifacts: {},
    lifecycle: LIFECYCLE,
  };
}

function assertInside(parent: string, child: string, name: string): void {
  const path = relative(parent, child);
  if (path === "" || path.startsWith("..") || isAbsolute(path)) {
    throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", `${name} must be inside its owned root`);
  }
}

function initialiseEvidence(options: ProduceImageOptions): void {
  const output = resolve(options.outputDirectory);
  const receipt = resolve(options.receiptPath);
  assertInside(output, receipt, "receipt");
  if (existsSync(output)) {
    throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", "output already exists");
  }
  mkdirSync(output, { recursive: false, mode: 0o700 });
  writeFileSync(resolve(output, ".tc-sdlc-owner.json"), canonicalJson(OWNER), { mode: 0o600 });
  writeCanonicalEvidence(receipt, failedReceipt(options, "production_incomplete"));
}

function git(sourceRoot: string, args: readonly string[]): string {
  const result = spawnSync("git", args, {
    cwd: sourceRoot,
    encoding: "utf8",
    timeout: PROCESS_TIMEOUT_MS,
    env: {
      PATH: process.env.PATH ?? "/usr/bin:/bin",
      HOME: "/nonexistent",
      GIT_CONFIG_NOSYSTEM: "1",
      GIT_CONFIG_GLOBAL: "/dev/null",
      GIT_OPTIONAL_LOCKS: "0",
    },
  });
  if (result.error !== undefined || result.status !== 0) {
    throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", "source Git identity is unavailable");
  }
  return result.stdout.trim();
}

function validateInputs(options: ProduceImageOptions): void {
  if (!/^[0-9a-f]{40}$/.test(options.sourceCommit)) {
    throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", "source commit must be a full lowercase Git object id");
  }
  const source = realpathSync(options.sourceRoot);
  const state = realpathSync(options.stateRoot);
  const dockerfile = realpathSync(options.dockerfile);
  assertInside(source, dockerfile, "Dockerfile");
  if (relative(source, state) === "" || !relative(source, state).startsWith("..")) {
    throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", "state root must be outside the source checkout");
  }
  if (readFileSync(resolve(state, ".tc-sdlc-owner.json"), "utf8") !== canonicalJson(STATE_OWNER)) {
    throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", "state root ownership is invalid");
  }
  const executable = realpathSync(options.buildxExecutable);
  if (!statSync(executable).isFile()) {
    throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", "buildx executable must be a regular file");
  }
  accessSync(executable, constants.X_OK);
  if (!options.dockerEndpoint.startsWith("unix://") && !options.dockerEndpoint.startsWith("ssh://")) {
    throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", "Docker endpoint must use unix or ssh transport");
  }
  if (git(source, ["rev-parse", "HEAD"]) !== options.sourceCommit) {
    throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", "source commit does not match checkout HEAD");
  }
}

export function validateImageReleaseReceipt(value: unknown): asserts value is ImageReleaseReceipt {
  assertSchema<ImageReleaseReceipt>("image-release-v1.schema.json", value, "image release receipt");
  if (value.status === "succeeded") {
    if (value.reason !== null || value.imageDigest === null || value.image === null || value.platforms.length !== 2) {
      throw new SdlcError("IMAGE_RELEASE_INVALID", "succeeded image release receipt is incomplete");
    }
  } else if (value.reason === null || value.imageDigest !== null || value.image !== null || value.platforms.length !== 0) {
    throw new SdlcError("IMAGE_RELEASE_INVALID", "failed image release receipt is inconsistent");
  }
}

export function parseImageReleaseReceipt(bytes: string): ImageReleaseReceipt {
  let value: unknown;
  try {
    value = JSON.parse(bytes);
  } catch {
    throw new SdlcError("IMAGE_RELEASE_INVALID", "image release receipt is not JSON");
  }
  validateImageReleaseReceipt(value);
  return value;
}

export async function produceImage(options: ProduceImageOptions): Promise<ImageReleaseReceipt> {
  initialiseEvidence(options);
  try {
    validateInputs(options);
    throw new SdlcError("IMAGE_PRODUCTION_NOT_IMPLEMENTED", "registry image production is not implemented");
  } catch (error) {
    const reason = error instanceof SdlcError && error.message.includes("source commit does not match")
      ? "source_commit_mismatch"
      : error instanceof SdlcError && error.code === "IMAGE_PRODUCTION_NOT_IMPLEMENTED"
        ? "production_not_implemented"
        : "image_production_input_invalid";
    const receipt = failedReceipt(options, reason);
    writeCanonicalEvidence(options.receiptPath, receipt);
    return receipt;
  }
}
