import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(packageRoot, "../..");
const command = process.platform === "linux"
  ? [process.env.DOCKER ?? "docker", [
      "build",
      "--target", "component-tests",
      "--file", "images/sdlc/Dockerfile",
      ".",
    ], repositoryRoot]
  : [process.env.npm_execpath ?? "pnpm", [
      "--dir", packageRoot,
      "test:integration:components:direct",
    ], repositoryRoot];

const result = spawnSync(command[0], command[1], {
  cwd: command[2],
  env: process.env,
  stdio: "inherit",
});
if (result.error !== undefined) throw result.error;
process.exit(result.status ?? 1);
