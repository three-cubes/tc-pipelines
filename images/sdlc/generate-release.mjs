import { execFileSync } from "node:child_process";
import {
  closeSync,
  fsyncSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  canonicalJson,
  generateReleaseCatalogue,
  writeReleaseCatalogue,
} from "../../packages/tc-sdlc/dist/index.js";

const repository = fileURLToPath(new URL("../..", import.meta.url));

function argument(name) {
  const index = process.argv.indexOf(`--${name}`);
  if (index === -1 || process.argv[index + 1] === undefined) {
    throw new Error(`missing --${name}`);
  }
  return process.argv[index + 1];
}

function atomicWrite(path, value) {
  mkdirSync(dirname(path), { recursive: true });
  const temporary = `${path}.tmp-${process.pid}`;
  writeFileSync(temporary, canonicalJson(value), { flag: "wx", mode: 0o600 });
  const file = openSync(temporary, "r");
  fsyncSync(file);
  closeSync(file);
  renameSync(temporary, path);
  const directory = openSync(dirname(path), "r");
  fsyncSync(directory);
  closeSync(directory);
}

const workflowCommit = argument("workflow-commit");
const imageDigest = argument("image-digest");
if (!/^[a-f0-9]{40}$/.test(workflowCommit)) throw new Error("workflow commit must be a full SHA");
if (!/^sha256:[a-f0-9]{64}$/.test(imageDigest)) throw new Error("image digest must be immutable");
execFileSync("git", ["cat-file", "-e", `${workflowCommit}^{commit}`], { cwd: repository });
execFileSync("git", ["cat-file", "-e", `${workflowCommit}:images/sdlc/Dockerfile`], {
  cwd: repository,
});

const packageMetadata = JSON.parse(
  readFileSync(join(repository, "packages/tc-sdlc/package.json"), "utf8"),
);
const version = readFileSync(join(repository, "VERSION"), "utf8").trim();
if (packageMetadata.version !== version || version === "2.2.0") {
  throw new Error("VERSION and package version must name the new coordinated release");
}
const fitnessVersion = execFileSync(
  "python3",
  [join(repository, "images/sdlc/read-locked-fitness-version.py"), join(repository, "uv.lock")],
  { encoding: "utf8" },
).trim();
if (!/^[0-9]+\.[0-9]+\.[0-9]+$/.test(fitnessVersion)) {
  throw new Error("uv.lock must resolve three-cubes-fitness to a SemVer version");
}

const catalogue = generateReleaseCatalogue({
  releaseVersion: version,
  fitnessVersion,
  workflowCommit,
  imageDigest,
});
mkdirSync(join(repository, "release"), { recursive: true });
writeReleaseCatalogue(join(repository, "release", "catalogue.json"), catalogue);
atomicWrite(join(repository, ".devcontainer", "devcontainer.json"), {
  name: `Three Cubes SDLC ${version}`,
  image: `ghcr.io/three-cubes/tc-sdlc@${imageDigest}`,
  remoteUser: "sdlc",
  workspaceFolder: "/workspace",
  workspaceMount:
    "source=${localWorkspaceFolder},target=/workspace,type=bind,consistency=cached",
  mounts: ["source=tc-sdlc-state,target=/state,type=volume"],
  containerEnv: {
    TC_SDLC_IMAGE_DIGEST: imageDigest,
    TC_SDLC_RELEASE: version,
  },
});

process.stdout.write(`${canonicalJson({ release: version, workflowCommit, imageDigest })}`);
