import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  accessSync,
  closeSync,
  constants,
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  openSync,
  readFileSync,
  realpathSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";

import { canonicalJson, digest } from "../canonical.js";
import {
  acquireBootstrapKernelBoundary,
  releaseBootstrapKernelBoundary,
  type BootstrapKernelBoundary,
} from "../bootstrap/kernel-boundary.js";
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
const BUILD_TIMEOUT_MS = 300_000;
const PLATFORMS = ["linux/amd64", "linux/arm64"] as const;

type JsonObject = Record<string, unknown>;

type PublishedImage = Readonly<{
  imageDigest: string;
  image: string;
  index: JsonObject;
  platforms: typeof PLATFORMS;
}>;

export type ImageReleaseReceipt = Readonly<{
  schema: "tc.sdlc/image-release/v1";
  status: "succeeded" | "failed";
  reason: string | null;
  sourceCommit: string | null;
  sourceTree: string | null;
  sourceInputDigest: string | null;
  registryCandidate: string | null;
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
  gitExecutable: string;
  stateRoot: string;
  outputDirectory: string;
  receiptPath: string;
}>;

type ImageFailureIdentity = Readonly<{
  sourceCommit?: string;
  sourceTree?: string | null;
  sourceInputDigest?: string | null;
  registryCandidate?: string;
}>;

function failedReceipt(options: ImageFailureIdentity, reason: string): ImageReleaseReceipt {
  const sourceCommit = options.sourceCommit;
  const registryCandidate = options.registryCandidate;
  return {
    schema: "tc.sdlc/image-release/v1",
    status: "failed",
    reason,
    sourceCommit: sourceCommit !== undefined && /^[0-9a-f]{40}$/.test(sourceCommit) ? sourceCommit : null,
    sourceTree: options.sourceTree ?? null,
    sourceInputDigest: options.sourceInputDigest ?? null,
    registryCandidate: registryCandidate === undefined || registryCandidate.length === 0
      ? null
      : registryCandidate,
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

function assertRealDirectory(path: string, name: string): void {
  if (!isAbsolute(path)) throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", `${name} must be an absolute directory`);
  const metadata = lstatSync(path);
  if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
    throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", `${name} must be a real directory`);
  }
  realpathSync(path);
}

function reserveReceipt(path: string, receipt: ImageReleaseReceipt): void {
  writeFileSync(path, canonicalJson(receipt), { flag: "wx", mode: 0o600 });
}

function initialiseEvidence(options: Pick<ProduceImageOptions, "outputDirectory" | "receiptPath"> & ImageFailureIdentity, reason: string): boolean {
  if (!isAbsolute(options.outputDirectory) || !isAbsolute(options.receiptPath)) {
    throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", "output and receipt must be absolute paths");
  }
  const output = resolve(options.outputDirectory);
  const receipt = resolve(options.receiptPath);
  if (existsSync(output)) {
    const relation = relative(output, receipt);
    if (relation === "" || (!relation.startsWith("..") && !isAbsolute(relation))) {
      throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", "output already exists and owns the requested receipt");
    }
    assertRealDirectory(dirname(receipt), "independent receipt parent");
    reserveReceipt(receipt, failedReceipt(options, reason));
    return false;
  }
  if (dirname(receipt) !== output) {
    throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", "receipt must be a direct child of new output");
  }
  assertRealDirectory(dirname(output), "output parent");
  mkdirSync(output, { recursive: false, mode: 0o700 });
  assertRealDirectory(output, "output");
  writeFileSync(resolve(output, ".tc-sdlc-owner.json"), canonicalJson(OWNER), { flag: "wx", mode: 0o600 });
  reserveReceipt(receipt, failedReceipt(options, reason));
  return true;
}

function requestedOption(args: readonly string[], name: string): string | undefined {
  const index = args.indexOf(`--${name}`);
  const value = index === -1 ? undefined : args[index + 1];
  return value === undefined || value.startsWith("--") ? undefined : value;
}

export function retainImageUsageFailure(args: readonly string[]): void {
  const outputDirectory = requestedOption(args, "output");
  const receiptPath = requestedOption(args, "receipt");
  if (outputDirectory === undefined || receiptPath === undefined || !isAbsolute(outputDirectory) || !isAbsolute(receiptPath)) {
    return;
  }
  try {
    initialiseEvidence({
      outputDirectory,
      receiptPath,
      sourceCommit: requestedOption(args, "source-commit"),
      registryCandidate: requestedOption(args, "registry-candidate"),
    }, "image_production_usage_invalid");
  } catch {
    // No safe terminal destination was available for this malformed invocation.
  }
}

function git(gitExecutable: string, sourceRoot: string, args: readonly string[]): string {
  const result = spawnSync(gitExecutable, args, {
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

function materialiseTrackedSource(
  gitExecutable: string,
  sourceRoot: string,
  stateRoot: string,
): Readonly<{ scratch: string; context: string }> {
  const scratch = mkdtempSync(resolve(stateRoot, ".image-production-"));
  writeFileSync(resolve(scratch, ".tc-sdlc-owner.json"), canonicalJson(STATE_OWNER), { flag: "wx", mode: 0o600 });
  const context = resolve(scratch, "context");
  mkdirSync(context, { mode: 0o700 });
  const result = spawnSync(
    gitExecutable,
    [`--work-tree=${context}`, "checkout-index", "--all", "--force"],
    {
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
    },
  );
  if (result.error !== undefined || result.status !== 0) {
    rmSync(scratch, { recursive: true, force: true });
    throw new SdlcError("IMAGE_PRODUCTION_FAILED", "tracked image build context could not be materialised");
  }
  return { scratch, context };
}

function sourceInputDigest(gitExecutable: string, sourceRoot: string): string {
  const paths = git(gitExecutable, sourceRoot, ["ls-files", "-z"]).split("\0").filter(Boolean).sort();
  const inputs = Object.fromEntries(paths.map((path) => [
    path,
    `sha256:${createHash("sha256").update(readFileSync(join(sourceRoot, path))).digest("hex")}`,
  ]));
  return digest(inputs);
}

function bytesDigest(bytes: Buffer | string): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

function runBuildx(
  executable: string,
  args: readonly string[],
  environment: NodeJS.ProcessEnv,
  options: Readonly<{ cwd?: string; timeout?: number }> = {},
): string {
  const result = spawnSync(executable, args, {
    cwd: options.cwd,
    encoding: "utf8",
    env: environment,
    timeout: options.timeout ?? PROCESS_TIMEOUT_MS,
    maxBuffer: 32 * 1024 * 1024,
  });
  if (result.error !== undefined || result.status !== 0) {
    throw new SdlcError(
      "IMAGE_PRODUCTION_FAILED",
      `buildx ${args[0] ?? "command"} failed${result.status === null ? "" : ` with exit ${result.status}`}: ${result.stderr.trim()}`,
    );
  }
  return result.stdout;
}

function imageRepository(candidate: string): string {
  return candidate.replace(/:[^/:]+$/, "");
}

function inspectPublished(
  buildxExecutable: string,
  candidate: string,
  expectedDigest: string,
  environment: NodeJS.ProcessEnv,
): PublishedImage {
  const descriptor = JSON.parse(runBuildx(
    buildxExecutable,
    ["imagetools", "inspect", candidate, "--format", "{{json .Manifest}}"],
    environment,
  )) as JsonObject;
  if (descriptor.digest !== expectedDigest) {
    throw new SdlcError("IMAGE_PRODUCTION_FAILED", "remote image digest mismatch");
  }
  const image = `${imageRepository(candidate)}@${expectedDigest}`;
  const raw = runBuildx(buildxExecutable, ["imagetools", "inspect", image, "--raw"], environment);
  const rawBytes = [Buffer.from(raw), Buffer.from(raw.replace(/\n$/, ""))];
  if (!rawBytes.some((bytes) => bytesDigest(bytes) === expectedDigest)) {
    throw new SdlcError("IMAGE_PRODUCTION_FAILED", "registry index payload digest mismatch");
  }
  const index = JSON.parse(raw) as JsonObject;
  const manifests = Array.isArray(index.manifests) ? index.manifests as JsonObject[] : [];
  const platforms = manifests
    .filter((manifest) => {
      const platform = manifest.platform as JsonObject | undefined;
      return platform?.os === "linux" && (platform.architecture === "amd64" || platform.architecture === "arm64");
    })
    .map((manifest) => {
      const platform = manifest.platform as JsonObject;
      return `${platform.os as string}/${platform.architecture as string}`;
    })
    .sort();
  if (JSON.stringify(platforms) !== JSON.stringify(PLATFORMS)) {
    throw new SdlcError("IMAGE_PRODUCTION_FAILED", "remote image platforms must be exactly linux/amd64 and linux/arm64");
  }
  return { imageDigest: expectedDigest, image, index, platforms: PLATFORMS };
}

async function collectAttestations(
  published: PublishedImage,
  buildxExecutable: string,
  environment: NodeJS.ProcessEnv,
): Promise<readonly JsonObject[]> {
  const [host, ...repositoryParts] = published.image.split("@")[0]!.split("/");
  if (host === undefined || repositoryParts.length === 0) {
    throw new SdlcError("IMAGE_PRODUCTION_FAILED", "registry image reference is invalid");
  }
  const repository = repositoryParts.join("/");
  const local = /^(localhost|127\.0\.0\.1)(:[0-9]+)?$/.test(host);
  const origin = `${local ? "http" : "https"}://${host}`;
  let bearer: string | undefined;

  const blob = async (expectedDigest: string): Promise<JsonObject> => {
    const url = `${origin}/v2/${repository}/blobs/${expectedDigest}`;
    let response = await fetch(url, {
      headers: bearer === undefined ? {} : { Authorization: `Bearer ${bearer}` },
      signal: AbortSignal.timeout(PROCESS_TIMEOUT_MS),
    });
    if (response.status === 401 && bearer === undefined) {
      const challenge = response.headers.get("www-authenticate") ?? "";
      const fields = Object.fromEntries(
        [...challenge.matchAll(/(realm|service|scope)="([^"]+)"/g)].map((match) => [match[1]!, match[2]!]),
      );
      if (!challenge.startsWith("Bearer ") || fields.realm === undefined) {
        throw new SdlcError("IMAGE_PRODUCTION_FAILED", "unsupported registry authentication challenge");
      }
      const realm = new URL(fields.realm);
      if (realm.origin !== origin) {
        throw new SdlcError("IMAGE_PRODUCTION_FAILED", "registry authentication changed origin");
      }
      if (fields.service !== undefined) realm.searchParams.set("service", fields.service);
      if (fields.scope !== undefined) realm.searchParams.set("scope", fields.scope);
      const headers: Record<string, string> = {};
      if (environment.TC_SDLC_REGISTRY_TOKEN !== undefined && environment.TC_SDLC_REGISTRY_USER !== undefined) {
        headers.Authorization = `Basic ${Buffer.from(`${environment.TC_SDLC_REGISTRY_USER}:${environment.TC_SDLC_REGISTRY_TOKEN}`).toString("base64")}`;
      }
      const authentication = await fetch(realm, { headers, redirect: "error", signal: AbortSignal.timeout(PROCESS_TIMEOUT_MS) });
      if (!authentication.ok) throw new SdlcError("IMAGE_PRODUCTION_FAILED", "registry authentication failed");
      const body = await authentication.json() as JsonObject;
      const token = body.token ?? body.access_token;
      if (typeof token !== "string") throw new SdlcError("IMAGE_PRODUCTION_FAILED", "registry token is missing");
      bearer = token;
      response = await fetch(url, {
        headers: { Authorization: `Bearer ${bearer}` },
        signal: AbortSignal.timeout(PROCESS_TIMEOUT_MS),
      });
    }
    if (!response.ok) throw new SdlcError("IMAGE_PRODUCTION_FAILED", `attestation blob fetch failed with ${response.status}`);
    const bytes = Buffer.from(await response.arrayBuffer());
    if (bytesDigest(bytes) !== expectedDigest) throw new SdlcError("IMAGE_PRODUCTION_FAILED", "attestation blob digest mismatch");
    return JSON.parse(bytes.toString("utf8")) as JsonObject;
  };

  const manifests = published.index.manifests as JsonObject[];
  const results: JsonObject[] = [];
  for (const platformName of PLATFORMS) {
    const target = manifests.find((manifest) => {
      const platform = manifest.platform as JsonObject | undefined;
      return `${platform?.os as string}/${platform?.architecture as string}` === platformName;
    });
    const targetDigest = target?.digest;
    const attestation = manifests.find((manifest) => {
      const annotations = manifest.annotations as JsonObject | undefined;
      return annotations?.["vnd.docker.reference.type"] === "attestation-manifest"
        && annotations?.["vnd.docker.reference.digest"] === targetDigest;
    });
    if (typeof targetDigest !== "string" || typeof attestation?.digest !== "string") {
      throw new SdlcError("IMAGE_PRODUCTION_FAILED", `missing attestation descriptor for ${platformName}`);
    }
    const raw = runBuildx(
      buildxExecutable,
      ["imagetools", "inspect", `${published.image.split("@")[0]}@${attestation.digest}`, "--raw"],
      environment,
    );
    const manifestBytes = [Buffer.from(raw), Buffer.from(raw.replace(/\n$/, ""))];
    if (!manifestBytes.some((bytes) => bytesDigest(bytes) === attestation.digest)) {
      throw new SdlcError("IMAGE_PRODUCTION_FAILED", `attestation manifest digest mismatch for ${platformName}`);
    }
    const manifest = JSON.parse(raw) as JsonObject;
    const layers = Array.isArray(manifest.layers) ? manifest.layers as JsonObject[] : [];
    const statements: JsonObject[] = [];
    for (const layer of layers) {
      if (typeof layer.digest !== "string") continue;
      const statement = await blob(layer.digest);
      const subjects = Array.isArray(statement.subject) ? statement.subject as JsonObject[] : [];
      if (!subjects.some((subject) => (subject.digest as JsonObject | undefined)?.sha256 === targetDigest.replace(/^sha256:/, ""))) {
        throw new SdlcError("IMAGE_PRODUCTION_FAILED", `attestation subject mismatch for ${platformName}`);
      }
      statements.push(statement);
    }
    if (!statements.some((statement) => typeof statement.predicateType === "string" && statement.predicateType.startsWith("https://slsa.dev/provenance/"))
      || !statements.some((statement) => statement.predicateType === "https://spdx.dev/Document")) {
      throw new SdlcError("IMAGE_PRODUCTION_FAILED", `missing provenance or SBOM for ${platformName}`);
    }
    results.push({ platform: platformName, subjectDigest: targetDigest, statements });
  }
  return results;
}

function assertAttestationIdentity(
  attestations: readonly JsonObject[],
  sourceIdentity: Readonly<{ sourceCommit: string; sourceInputDigest: string }>,
  version: string,
): void {
  for (const entry of attestations) {
    const statements = entry.statements as JsonObject[];
    const provenance = statements.find((statement) =>
      typeof statement.predicateType === "string" && statement.predicateType.startsWith("https://slsa.dev/provenance/"));
    const predicate = provenance?.predicate as JsonObject | undefined;
    const buildDefinition = predicate?.buildDefinition as JsonObject | undefined;
    const externalParameters = buildDefinition?.externalParameters as JsonObject | undefined;
    const request = externalParameters?.request as JsonObject | undefined;
    const args = request?.args as JsonObject | undefined;
    if (args?.["build-arg:SOURCE_COMMIT"] !== sourceIdentity.sourceCommit
      || args?.["build-arg:SOURCE_INPUT_DIGEST"] !== sourceIdentity.sourceInputDigest
      || args?.["build-arg:SDLC_VERSION"] !== version) {
      throw new SdlcError("IMAGE_PRODUCTION_FAILED", `registry candidate source identity mismatch for ${String(entry.platform)}`);
    }
  }
}

function dockerEnvironment(stateRoot: string, dockerEndpoint: string, registryCandidate: string): Readonly<{ environment: NodeJS.ProcessEnv; dockerConfig: string }> {
  if (process.env.TC_SDLC_REGISTRY_TOKEN !== undefined) {
    if (process.env.TC_SDLC_REGISTRY_USER === undefined) {
      throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", "registry user is required with registry credentials");
    }
    const host = process.env.TC_SDLC_REGISTRY_HOST;
    if (host === undefined || host.length === 0) {
      throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", "registry host is required with registry credentials");
    }
    if (registryCandidate.split("/")[0] !== host) {
      throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", "registry credentials do not match the candidate host");
    }
  }
  const dockerConfig = mkdtempSync(resolve(stateRoot, ".docker-config-"));
  writeFileSync(resolve(dockerConfig, ".tc-sdlc-owner.json"), canonicalJson(STATE_OWNER), { flag: "wx", mode: 0o600 });
  if (process.env.TC_SDLC_REGISTRY_TOKEN !== undefined) {
    const host = process.env.TC_SDLC_REGISTRY_HOST!;
    writeFileSync(resolve(dockerConfig, "config.json"), canonicalJson({
      auths: {
        [host]: {
          auth: Buffer.from(`${process.env.TC_SDLC_REGISTRY_USER}:${process.env.TC_SDLC_REGISTRY_TOKEN}`).toString("base64"),
        },
      },
    }), { flag: "wx", mode: 0o600 });
  }
  const environment: NodeJS.ProcessEnv = { ...process.env, DOCKER_CONFIG: dockerConfig, DOCKER_HOST: dockerEndpoint };
  for (const name of ["BUILDX_CONFIG", "BUILDER_NODE", "BUILDKIT_HOST", "DOCKER_CONTEXT", "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY"]) {
    delete environment[name];
  }
  return { environment, dockerConfig };
}

function ensureBuilder(
  buildxExecutable: string,
  dockerEndpoint: string,
  environment: NodeJS.ProcessEnv,
  runIdentity: string,
): Readonly<{ name: string; created: boolean }> {
  const suffix = createHash("sha256").update(`${dockerEndpoint}\0${runIdentity}`).digest("hex").slice(0, 12);
  const name = `tc-sdlc-release-${suffix}`;
  const inspected = spawnSync(buildxExecutable, ["inspect", "--builder", name], { encoding: "utf8", env: environment, timeout: PROCESS_TIMEOUT_MS });
  if (inspected.status === 0) return { name, created: false };
  runBuildx(
    buildxExecutable,
    ["create", "--name", name, "--driver", "docker-container", "--driver-opt", "network=host", dockerEndpoint],
    environment,
  );
  return { name, created: true };
}

function validateInputs(options: ProduceImageOptions): Readonly<{ sourceCommit: string; sourceTree: string; sourceInputDigest: string }> {
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
  const gitExecutable = realpathSync(options.gitExecutable);
  if (!statSync(gitExecutable).isFile()) {
    throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", "Git executable must be a regular file");
  }
  accessSync(gitExecutable, constants.X_OK);
  if (!options.dockerEndpoint.startsWith("unix://") && !options.dockerEndpoint.startsWith("ssh://")) {
    throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", "Docker endpoint must use unix or ssh transport");
  }
  if (git(gitExecutable, source, ["rev-parse", "HEAD"]) !== options.sourceCommit) {
    throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", "source commit does not match checkout HEAD");
  }
  if (git(gitExecutable, source, ["status", "--porcelain=v1", "--untracked-files=all"]) !== "") {
    throw new SdlcError("IMAGE_SOURCE_TREE_DIRTY", "source checkout must be clean before image production");
  }
  const sourceTree = git(gitExecutable, source, ["rev-parse", `${options.sourceCommit}^{tree}`]);
  if (!/^[0-9a-f]{40}$/.test(sourceTree)) {
    throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", "source tree identity is unavailable");
  }
  return { sourceCommit: options.sourceCommit, sourceTree, sourceInputDigest: sourceInputDigest(gitExecutable, source) };
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
  let ownsOutput: boolean;
  try {
    ownsOutput = initialiseEvidence(options, "image_production_output_collision");
  } catch (error) {
    throw error;
  }
  if (!ownsOutput) return failedReceipt(options, "image_production_output_collision");
  let sourceIdentity: Readonly<{ sourceCommit: string; sourceTree: string; sourceInputDigest: string }> | undefined;
  let dockerConfig: string | undefined;
  let buildScratch: string | undefined;
  let buildContext: string | undefined;
  let builder: Readonly<{ name: string; created: boolean }> | undefined;
  let productionBoundary: BootstrapKernelBoundary | undefined;
  let environment: NodeJS.ProcessEnv | undefined;
  try {
    sourceIdentity = validateInputs(options);
    const packageMetadata = JSON.parse(readFileSync(resolve(options.sourceRoot, "packages/tc-sdlc/package.json"), "utf8")) as JsonObject;
    if (typeof packageMetadata.version !== "string" || packageMetadata.version.length === 0) {
      throw new SdlcError("IMAGE_PRODUCTION_INPUT_INVALID", "tc-sdlc package version is unavailable");
    }
    productionBoundary = await acquireBootstrapKernelBoundary(
      options.stateRoot,
      "image-production",
      { registryCandidate: options.registryCandidate },
    );
    ({ environment, dockerConfig } = dockerEnvironment(options.stateRoot, options.dockerEndpoint, options.registryCandidate));

    const existing = spawnSync(
      options.buildxExecutable,
      ["imagetools", "inspect", options.registryCandidate, "--format", "{{json .Manifest.Digest}}"],
      { encoding: "utf8", env: environment, timeout: PROCESS_TIMEOUT_MS },
    );
    let reused = existing.status === 0;
    let imageDigest: string;
    const metadataPath = resolve(options.outputDirectory, "metadata.json");
    const buildLogPath = resolve(options.outputDirectory, "build.log");
    if (reused) {
      imageDigest = JSON.parse(existing.stdout) as string;
      writeFileSync(metadataPath, canonicalJson({ "containerimage.digest": imageDigest, source: "remote-existing-candidate" }), { mode: 0o600 });
      writeFileSync(buildLogPath, "Existing registry candidate reused; no image build executed.\n", { mode: 0o600 });
    } else {
      if (existing.error !== undefined || !/not found|manifest unknown|404/i.test(existing.stderr)) {
        throw new SdlcError("IMAGE_PRODUCTION_FAILED", `candidate lookup failed: ${existing.error?.message ?? existing.stderr.trim()}`);
      }
      ({ scratch: buildScratch, context: buildContext } = materialiseTrackedSource(
        options.gitExecutable,
        options.sourceRoot,
        options.stateRoot,
      ));
      const dockerfile = resolve(buildContext, relative(options.sourceRoot, options.dockerfile));
      if (!existsSync(dockerfile)) {
        throw new SdlcError("IMAGE_PRODUCTION_FAILED", "tracked Dockerfile is absent from the materialised build context");
      }
      builder = ensureBuilder(options.buildxExecutable, options.dockerEndpoint, environment, options.outputDirectory);
      const logDescriptor = openSync(buildLogPath, "wx", 0o600);
      let built: ReturnType<typeof spawnSync>;
      try {
        built = spawnSync(
          options.buildxExecutable,
          [
            "build",
            "--builder", builder.name,
            "--platform", PLATFORMS.join(","),
            "--file", dockerfile,
            "--tag", options.registryCandidate,
            "--push",
            "--provenance", "mode=max",
            "--sbom", "true",
            "--build-arg", `SDLC_VERSION=${packageMetadata.version}`,
            "--build-arg", `SOURCE_COMMIT=${sourceIdentity.sourceCommit}`,
            "--build-arg", `SOURCE_INPUT_DIGEST=${sourceIdentity.sourceInputDigest}`,
            "--metadata-file", metadataPath,
            "--progress", "plain",
            buildContext,
          ],
          {
            cwd: buildContext,
            env: environment,
            stdio: ["ignore", logDescriptor, logDescriptor],
            timeout: BUILD_TIMEOUT_MS,
          },
        );
      } finally {
        closeSync(logDescriptor);
      }
      if (built.error !== undefined || built.status !== 0) {
        throw new SdlcError(
          "IMAGE_PRODUCTION_FAILED",
          `multi-platform image build failed${built.status === null ? "" : ` with exit ${built.status}`}: ${built.error?.message ?? "see build.log"}`,
        );
      }
      const metadata = JSON.parse(readFileSync(metadataPath, "utf8")) as JsonObject;
      if (typeof metadata["containerimage.digest"] !== "string") {
        throw new SdlcError("IMAGE_PRODUCTION_FAILED", "image build did not emit an immutable digest");
      }
      imageDigest = metadata["containerimage.digest"];
    }
    if (!/^sha256:[0-9a-f]{64}$/.test(imageDigest)) {
      throw new SdlcError("IMAGE_PRODUCTION_FAILED", "registry candidate digest is invalid");
    }

    const published = inspectPublished(options.buildxExecutable, options.registryCandidate, imageDigest, environment);
    const attestations = await collectAttestations(published, options.buildxExecutable, environment);
    assertAttestationIdentity(attestations, sourceIdentity, packageMetadata.version);
    const remoteIndexPath = resolve(options.outputDirectory, "remote-index.json");
    const attestationsPath = resolve(options.outputDirectory, "attestations.json");
    writeFileSync(remoteIndexPath, canonicalJson(published), { mode: 0o600 });
    writeFileSync(attestationsPath, canonicalJson(attestations), { mode: 0o600 });
    const artifactNames = ["metadata.json", "build.log", "remote-index.json", "attestations.json"];
    const artifacts = Object.fromEntries(artifactNames.map((name) => [name, bytesDigest(readFileSync(resolve(options.outputDirectory, name)))]));
    const receipt: ImageReleaseReceipt = {
      schema: "tc.sdlc/image-release/v1",
      status: "succeeded",
      reason: null,
      ...sourceIdentity,
      registryCandidate: options.registryCandidate,
      imageDigest,
      image: published.image,
      platforms: PLATFORMS,
      reused,
      artifacts,
      lifecycle: LIFECYCLE,
    };
    validateImageReleaseReceipt(receipt);
    writeCanonicalEvidence(options.receiptPath, receipt);
    return receipt;
  } catch (error) {
    const reason = error instanceof SdlcError && error.code === "IMAGE_SOURCE_TREE_DIRTY"
      ? "source_tree_dirty"
      : error instanceof SdlcError && error.message.includes("source commit does not match")
      ? "source_commit_mismatch"
      : error instanceof SdlcError && error.code === "IMAGE_PRODUCTION_FAILED"
        ? "image_production_failed"
        : "image_production_input_invalid";
    const receipt = failedReceipt({ ...options, ...sourceIdentity }, reason);
    if (reason === "image_production_failed") {
      const failureLog = resolve(options.outputDirectory, "failure.log");
      const detail = error instanceof Error ? error.message : String(error);
      writeFileSync(failureLog, `${detail}\n`, { mode: 0o600 });
      Object.assign(receipt.artifacts, { "failure.log": bytesDigest(readFileSync(failureLog)) });
    }
    writeCanonicalEvidence(options.receiptPath, receipt);
    return receipt;
  } finally {
    if (builder?.created === true && environment !== undefined) {
      spawnSync(options.buildxExecutable, ["rm", "--force", builder.name], {
        encoding: "utf8",
        env: environment,
        timeout: PROCESS_TIMEOUT_MS,
      });
    }
    if (buildScratch !== undefined) rmSync(buildScratch, { recursive: true, force: true });
    if (dockerConfig !== undefined) rmSync(dockerConfig, { recursive: true, force: true });
    if (productionBoundary !== undefined) releaseBootstrapKernelBoundary(productionBoundary);
  }
}
