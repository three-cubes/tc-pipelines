import { execFileSync } from "node:child_process";
import {
  chmodSync,
  cpSync,
  existsSync,
  mkdtempSync,
  mkdirSync,
  realpathSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  CANONICAL_SDLC_FITNESS,
  CANONICAL_SDLC_TOOLCHAINS,
  bootstrap,
  canonicalJson,
  generateReleaseCatalogue,
  resolveLock,
  validateDeclaration,
  writeLock,
} from "../../packages/tc-sdlc/dist/index.js";

const repository = fileURLToPath(new URL("../..", import.meta.url));
const fixture = join(repository, "packages/tc-sdlc/test/fixtures/bootstrap-consumer");

function argument(name) {
  const index = process.argv.indexOf(`--${name}`);
  if (index === -1 || process.argv[index + 1] === undefined) {
    throw new Error(`missing --${name}`);
  }
  return process.argv[index + 1];
}

const image = argument("image");
const imageDigest = argument("image-digest");
const workflowCommit = argument("workflow-commit");
const sharedTemporaryRoot =
  process.platform === "darwin" ? argument("shared-root") : tmpdir();
const temporary = realpathSync(
  mkdtempSync(join(sharedTemporaryRoot, "tc-sdlc-image-verification-")),
);
const root = join(temporary, "consumer");
const nativeState = join(temporary, "native-state");
const imageState = join(temporary, "image-state");
const evidence = join(temporary, "evidence");
for (const directory of [root, nativeState, imageState, evidence]) {
  mkdirSync(directory, { recursive: true, mode: 0o777 });
  chmodSync(directory, 0o777);
}
cpSync(fixture, root, { recursive: true });

const declaration = validateDeclaration({
  schema: "tc.sdlc/v1",
  project: "bootstrap-image-verification",
  toolchains: CANONICAL_SDLC_TOOLCHAINS,
  fitness: CANONICAL_SDLC_FITNESS,
  projects: [{ name: "consumer", root: "." }],
  targets: {
    check: {
      command: "node --version",
      mode: "evaluate",
      trustBoundary: "portable",
      inputs: ["package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock"],
    },
  },
});
const catalogue = generateReleaseCatalogue({
  releaseVersion: "3.0.0",
  workflowCommit,
  imageDigest,
});
const lock = resolveLock(declaration, catalogue);
writeFileSync(join(root, "sdlc.json"), canonicalJson(declaration));
writeFileSync(join(root, "catalogue.json"), canonicalJson(catalogue));
writeLock(join(root, "tc-sdlc.lock"), lock);

const nativeReceipt = await bootstrap({
  root,
  stateRoot: nativeState,
  declaration,
  catalogue,
  lock,
  receiptPath: join(evidence, "native.json"),
});
if (nativeReceipt.status !== "succeeded") {
  throw new Error(`native bootstrap failed: ${nativeReceipt.reason}`);
}
if (existsSync(join(root, "node_modules")) || existsSync(join(root, ".venv"))) {
  throw new Error("native bootstrap wrote dependency state into the checkout");
}

function runImage(receiptName, offline) {
  return JSON.parse(
    execFileSync(
      "docker",
      [
        "run",
        "--rm",
        ...(offline ? ["--network", "none"] : []),
        "--volume", `${root}:/workspace`,
        "--volume", `${imageState}:/state`,
        "--volume", `${evidence}:/evidence`,
        image,
        "tc-sdlc",
        "bootstrap",
        "--declaration", "/workspace/sdlc.json",
        "--catalogue", "/workspace/catalogue.json",
        "--lock", "/workspace/tc-sdlc.lock",
        "--root", "/workspace",
        "--state-root", "/state",
        "--receipt", `/evidence/${receiptName}`,
        "--offline", String(offline),
      ],
      { encoding: "utf8" },
    ),
  );
}

const imageResult = runImage("image.json", false);
if (imageResult.status !== "ok") throw new Error("canonical image bootstrap failed");
const imageReceipt = JSON.parse(readFileSync(join(evidence, "image.json"), "utf8"));
if (imageReceipt.status !== "succeeded") throw new Error(`image receipt failed: ${imageReceipt.reason}`);
if (existsSync(join(root, "node_modules")) || existsSync(join(root, ".venv"))) {
  throw new Error("canonical image bootstrap wrote dependency state into the checkout");
}
if (canonicalJson(imageReceipt.taskIdentities) !== canonicalJson(nativeReceipt.taskIdentities)) {
  throw new Error("native and canonical image task identities differ");
}
if (canonicalJson(imageReceipt.dependencies) !== canonicalJson(nativeReceipt.dependencies)) {
  throw new Error("native and canonical image dependency identities differ");
}
if (
  canonicalJson(imageReceipt.adapters.map(({ name, version }) => ({ name, version }))) !==
  canonicalJson(nativeReceipt.adapters.map(({ name, version }) => ({ name, version })))
) {
  throw new Error("native and canonical image toolchain versions differ");
}

const imageEnvironment = join(imageState, imageReceipt.stateKey, "dependencies");
execFileSync("docker", [
  "run", "--rm", "--network", "none",
  "--volume", `${imageEnvironment}:/dependencies:ro`,
  image,
  "/dependencies/python/bin/python", "-c", "import attrs; assert attrs.__version__ == '26.1.0'",
]);
execFileSync("docker", [
  "run", "--rm", "--network", "none",
  "--volume", `${imageEnvironment}:/dependencies:ro`,
  image,
  "node", "-e", "require('/dependencies/node/node_modules/yaml')",
]);

const warmResult = runImage("image-offline.json", true);
if (warmResult.status !== "ok") throw new Error("offline canonical image bootstrap failed");
const warmReceipt = JSON.parse(readFileSync(join(evidence, "image-offline.json"), "utf8"));
if (warmReceipt.status !== "succeeded" || warmReceipt.reused !== true) {
  throw new Error("offline canonical image did not reuse verified warm state");
}

process.stdout.write(
  `${JSON.stringify({
    schema: "tc.sdlc/image-verification/v1",
    status: "succeeded",
    release: imageReceipt.release,
    lockDigest: imageReceipt.lockDigest,
    taskIdentities: imageReceipt.taskIdentities,
    dependencyLocks: imageReceipt.dependencies,
    nativePlatform: nativeReceipt.platform,
    imagePlatform: imageReceipt.platform,
  })}\n`,
);
