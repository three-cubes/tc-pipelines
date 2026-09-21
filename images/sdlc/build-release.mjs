import { spawnSync, execFileSync } from "node:child_process";
import {
  closeSync,
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  openSync,
  readFileSync,
  realpathSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

import { canonicalJson } from "../../packages/tc-sdlc/dist/index.js";

const repository = realpathSync(fileURLToPath(new URL("../..", import.meta.url)));
const OWNER = { schema: "tc.sdlc/state-owner/v1", owner: "@three-cubes/tc-sdlc" };

function argument(name) {
  const index = process.argv.indexOf(`--${name}`);
  if (index === -1 || process.argv[index + 1] === undefined) {
    throw new Error(`missing --${name}`);
  }
  return process.argv[index + 1];
}

function artifactDestination(value) {
  if (!isAbsolute(value)) throw new Error("artifact output must be absolute");
  const artifactsRoot = join(repository, "artifacts");
  mkdirSync(artifactsRoot, { recursive: true, mode: 0o700 });
  if (lstatSync(artifactsRoot).isSymbolicLink()) {
    throw new Error("repository artifacts directory may not be a symbolic link");
  }
  const output = resolve(value);
  if (dirname(output) !== realpathSync(artifactsRoot) || !/^[a-zA-Z0-9._-]+$/.test(basename(output))) {
    throw new Error("artifact output must be a direct child of the repository artifacts directory");
  }
  if (existsSync(output)) throw new Error("artifact output already exists");
  return { artifactsRoot, output };
}

function ownedStateRoot(value) {
  if (!isAbsolute(value)) throw new Error("state root must be absolute");
  const root = resolve(value);
  const relation = relative(repository, root);
  if (relation === "" || (relation !== ".." && !relation.startsWith(`..${sep}`))) {
    throw new Error("state root must remain outside the checkout");
  }
  try {
    if (!lstatSync(root).isDirectory() || lstatSync(root).isSymbolicLink()) {
      throw new Error("invalid state directory");
    }
    const marker = join(root, ".tc-sdlc-owner.json");
    if (
      lstatSync(marker).isSymbolicLink() ||
      readFileSync(marker, "utf8") !== canonicalJson(OWNER)
    ) throw new Error("owner mismatch");
  } catch {
    throw new Error("state root is not owned by tc-sdlc");
  }
  return root;
}

function executable(value) {
  if (!isAbsolute(value)) throw new Error("buildx executable must be absolute");
  const path = realpathSync(value);
  const details = lstatSync(path);
  if (!details.isFile() || (details.mode & 0o111) === 0) {
    throw new Error("buildx executable must be an executable regular file");
  }
  return path;
}

function ownedDirectory(stateRoot, ...segments) {
  let cursor = stateRoot;
  for (const segment of segments) {
    cursor = join(cursor, segment);
    if (existsSync(cursor)) {
      const details = lstatSync(cursor);
      if (details.isSymbolicLink()) {
        throw new Error("managed state path may not traverse symbolic links");
      }
      if (!details.isDirectory()) throw new Error("managed state path must be a directory");
    } else {
      mkdirSync(cursor, { mode: 0o700 });
    }
  }
  return cursor;
}

function dockerEnvironment(stateRoot) {
  const environment = {
    ...process.env,
    DOCKER_CONFIG: ownedDirectory(stateRoot, "cache", "docker"),
  };
  for (const name of [
    "BUILDX_CONFIG",
    "BUILDER_NODE",
    "BUILDKIT_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_HOST",
    "DOCKER_CERT_PATH",
    "DOCKER_TLS_VERIFY",
  ]) delete environment[name];
  return environment;
}

function inspectedEndpoints(result) {
  return result.stdout
    .split("\n")
    .map((line) => /^Endpoint:\s+(.+?)\s*$/.exec(line)?.[1])
    .filter((value) => value !== undefined);
}

function ensureBuilder(buildx, builder, dockerEndpoint, environment) {
  let inspected = spawnSync(buildx, ["inspect", "--builder", builder], {
    encoding: "utf8",
    env: environment,
  });
  if (inspected.error !== undefined) throw inspected.error;
  if (inspected.status !== 0) {
    const created = spawnSync(
      buildx,
      ["create", "--name", builder, "--driver", "docker-container", dockerEndpoint],
      { encoding: "utf8", env: environment },
    );
    if (created.error !== undefined) throw created.error;
    if (created.status !== 0) {
      throw new Error(`managed BuildKit builder creation failed with exit ${created.status}`);
    }
    inspected = spawnSync(buildx, ["inspect", "--builder", builder], {
      encoding: "utf8",
      env: environment,
    });
  }
  if (inspected.error !== undefined) throw inspected.error;
  if (inspected.status !== 0) {
    throw new Error(`managed BuildKit builder inspection failed with exit ${inspected.status}`);
  }
  const endpoints = inspectedEndpoints(inspected);
  if (endpoints.length === 0 || endpoints.some((endpoint) => endpoint !== dockerEndpoint)) {
    throw new Error("managed BuildKit builder endpoint mismatch");
  }
}

function writeAtomic(path, value) {
  const temporary = `${path}.tmp-${process.pid}`;
  writeFileSync(temporary, canonicalJson(value), { flag: "wx", mode: 0o600 });
  renameSync(temporary, path);
}

const { artifactsRoot, output } = artifactDestination(argument("artifact-output"));
const stateRoot = ownedStateRoot(argument("state-root"));
const buildx = executable(argument("buildx-executable"));
const dockerEndpoint = argument("docker-endpoint");
if (!/^(unix|ssh):\/\/.+/.test(dockerEndpoint)) {
  throw new Error("docker endpoint must be an explicit local unix or authenticated ssh endpoint");
}
const builder = "tc-sdlc-release";
const environment = dockerEnvironment(stateRoot);
const builders = ownedDirectory(stateRoot, "builders");
ensureBuilder(buildx, builder, dockerEndpoint, environment);
const status = execFileSync("git", ["status", "--porcelain=v1", "--untracked-files=all"], {
  cwd: repository,
  encoding: "utf8",
}).trim();
if (status !== "") throw new Error("release image must be built from a clean source tree");
const sourceCommit = execFileSync("git", ["rev-parse", "HEAD"], {
  cwd: repository,
  encoding: "utf8",
}).trim();
if (!/^[0-9a-f]{40}$/.test(sourceCommit)) throw new Error("source commit is not immutable");

const staging = mkdtempSync(join(artifactsRoot, `.${basename(output)}-`));
try {
  const image = join(staging, "image.oci.tar");
  const metadata = join(staging, "metadata.json");
  const log = join(staging, "build.log");
  const logDescriptor = openSync(log, "wx", 0o600);
  let built;
  try {
    built = spawnSync(
      buildx,
      [
        "build",
        "--builder", builder,
        "--platform", "linux/amd64,linux/arm64",
        "--file", join(repository, "images/sdlc/Dockerfile"),
        "--output", `type=oci,dest=${image}`,
        "--metadata-file", metadata,
        "--progress", "plain",
        repository,
      ],
      {
        cwd: repository,
        stdio: ["ignore", logDescriptor, logDescriptor],
        env: environment,
      },
    );
  } finally {
    closeSync(logDescriptor);
  }
  if (built.error !== undefined) throw built.error;
  if (built.status !== 0) throw new Error(`multi-platform image build failed with exit ${built.status}`);
  const buildMetadata = JSON.parse(readFileSync(metadata, "utf8"));
  const imageDigest = buildMetadata["containerimage.digest"];
  if (!/^sha256:[0-9a-f]{64}$/.test(imageDigest)) {
    throw new Error("image build did not emit an immutable OCI index digest");
  }
  writeFileSync(
    join(staging, "build-receipt.json"),
    canonicalJson({
      schema: "tc.sdlc/image-build-artifact/v1",
      sourceCommit,
      imageDigest,
      platforms: ["linux/amd64", "linux/arm64"],
      files: {
        image: "image.oci.tar",
        metadata: "metadata.json",
        log: "build.log",
      },
      lifecycle: {
        class: "release-artifact-evidence",
        owner: "@three-cubes/tc-sdlc",
        retain: "catalogue-current-predecessor-or-incident-reference",
      },
      builder: {
        name: builder,
        dockerConfig: join(stateRoot, "cache", "docker"),
        endpoint: dockerEndpoint,
      },
    }),
    { flag: "wx", mode: 0o600 },
  );
  renameSync(staging, output);
  writeAtomic(join(builders, `${builder}.json`), {
    schema: "tc.sdlc/buildkit-owner/v1",
    owner: "@three-cubes/tc-sdlc",
    builder,
    endpoint: dockerEndpoint,
    sourceCommit,
    artifactOutput: output,
  });
  process.stdout.write(
    `${canonicalJson({
      schema: "tc.sdlc/image-build-result/v1",
      status: "succeeded",
      sourceCommit,
      imageDigest,
      artifactOutput: output,
      evidence: join(output, "build-receipt.json"),
    })}`,
  );
} catch (error) {
  rmSync(staging, { recursive: true, force: true });
  throw error;
}
