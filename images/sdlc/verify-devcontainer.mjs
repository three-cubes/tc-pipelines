import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

function argument(name) {
  const index = process.argv.indexOf(`--${name}`);
  if (index === -1 || process.argv[index + 1] === undefined) {
    throw new Error(`missing --${name}`);
  }
  return process.argv[index + 1];
}

const image = argument("image");
const config = JSON.parse(
  readFileSync(new URL("../../.devcontainer/devcontainer.json", import.meta.url), "utf8"),
);
const workspaceMount = config.workspaceMount;
if (typeof workspaceMount !== "string") {
  throw new Error("devcontainer must declare workspaceMount");
}
const fields = Object.fromEntries(
  workspaceMount.split(",").map((field) => {
    const separator = field.indexOf("=");
    if (separator === -1) throw new Error(`invalid workspaceMount field: ${field}`);
    return [field.slice(0, separator), field.slice(separator + 1)];
  }),
);
if (
  fields.source !== "${localWorkspaceFolder}" ||
  fields.target !== config.workspaceFolder ||
  fields.type !== "bind"
) {
  throw new Error("devcontainer workspaceMount does not bind the opened source tree");
}

const sharedRoot = process.platform === "darwin" ? argument("shared-root") : tmpdir();
const openedTree = realpathSync(mkdtempSync(join(sharedRoot, "tc-sdlc-devcontainer-")));
writeFileSync(join(openedTree, "opened-tree-marker"), "exact opened source tree\n");
try {
  execFileSync("docker", [
    "run",
    "--rm",
    "--volume",
    `${openedTree}:${config.workspaceFolder}:ro`,
    "--workdir",
    config.workspaceFolder,
    image,
    "/bin/sh",
    "-ec",
    'test "$(cat opened-tree-marker)" = "exact opened source tree"; test "$(pwd -P)" = /workspace',
  ]);
} finally {
  rmSync(openedTree, { recursive: true, force: true });
}

process.stdout.write(
  `${JSON.stringify({ schema: "tc.sdlc/devcontainer-verification/v1", status: "succeeded" })}\n`,
);
