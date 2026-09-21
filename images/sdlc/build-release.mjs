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
import { basename, dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { canonicalJson } from "../../packages/tc-sdlc/dist/index.js";

const repository = realpathSync(fileURLToPath(new URL("../..", import.meta.url)));

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

const { artifactsRoot, output } = artifactDestination(argument("artifact-output"));
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
      "docker",
      [
        "buildx", "build",
        "--platform", "linux/amd64,linux/arm64",
        "--file", join(repository, "images/sdlc/Dockerfile"),
        "--output", `type=oci,dest=${image}`,
        "--metadata-file", metadata,
        "--progress", "plain",
        repository,
      ],
      { cwd: repository, stdio: ["ignore", logDescriptor, logDescriptor] },
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
      retention: "caller-managed",
    }),
    { flag: "wx", mode: 0o600 },
  );
  renameSync(staging, output);
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
