import { execFileSync, spawnSync } from "node:child_process";
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { beforeAll, describe, expect, test } from "vitest";

const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const TIMEOUT_MS = 120_000;

function canonical(value: unknown): string {
  const keys = new Set<string>();
  JSON.stringify(value, (key, child: unknown) => { keys.add(key); return child; });
  return `${JSON.stringify(value, [...keys].sort(), 2)}\n`;
}

function installPackedCli(): string {
  const packages = mkdtempSync(join(tmpdir(), "tc-sdlc-image-package-"));
  execFileSync("pnpm", ["pack", "--pack-destination", packages], {
    cwd: packageRoot,
    encoding: "utf8",
    timeout: TIMEOUT_MS,
  });
  const archive = readdirSync(packages).find((name) => name.endsWith(".tgz"));
  if (archive === undefined) throw new Error("pnpm pack did not produce an archive");
  const installation = mkdtempSync(join(tmpdir(), "tc-sdlc-image-installation-"));
  execFileSync("pnpm", ["add", "--ignore-scripts", "--lockfile=false", join(packages, archive)], {
    cwd: installation,
    encoding: "utf8",
    timeout: TIMEOUT_MS,
  });
  return join(installation, "node_modules", ".bin", "tc-sdlc");
}

function sourceFixture() {
  const root = mkdtempSync(join(tmpdir(), "tc-sdlc-image-source-"));
  mkdirSync(join(root, "packages", "tc-sdlc"), { recursive: true });
  mkdirSync(join(root, "images", "sdlc"), { recursive: true });
  writeFileSync(join(root, "packages", "tc-sdlc", "package.json"), JSON.stringify({ name: "@three-cubes/tc-sdlc", version: "3.0.0" }));
  writeFileSync(join(root, "images", "sdlc", "Dockerfile"), "FROM scratch\n");
  execFileSync("git", ["init", "-q"], { cwd: root });
  execFileSync("git", ["add", "."], { cwd: root });
  execFileSync("git", ["-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], { cwd: root });
  return { root, commit: execFileSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8" }).trim() };
}

describe("tc-sdlc produce-image", () => {
  let cli: string;

  beforeAll(() => { cli = installPackedCli(); }, 30_000);

  test("retains terminal producer evidence when preflight rejects the source identity", () => {
    const source = sourceFixture();
    const runRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-image-run-"));
    const state = join(runRoot, "state");
    const output = join(runRoot, "evidence");
    const receipt = join(output, "image-release.json");
    const buildx = join(runRoot, "buildx");
    mkdirSync(state);
    writeFileSync(join(state, ".tc-sdlc-owner.json"), canonical({ schema: "tc.sdlc/state-owner/v1", owner: "@three-cubes/tc-sdlc" }));
    writeFileSync(buildx, "#!/bin/sh\nexit 99\n");
    chmodSync(buildx, 0o755);

    const result = spawnSync(cli, [
      "produce-image",
      "--source-root", source.root,
      "--source-commit", "0".repeat(40),
      "--dockerfile", join(source.root, "images", "sdlc", "Dockerfile"),
      "--registry-candidate", "localhost:1/sdlc:candidate",
      "--docker-endpoint", "unix:///missing.sock",
      "--buildx-executable", buildx,
      "--state-root", state,
      "--output", output,
      "--receipt", receipt,
    ], { encoding: "utf8", timeout: TIMEOUT_MS });

    expect(result.status).toBe(1);
    expect(JSON.parse(result.stderr)).toMatchObject({
      schema: "tc.sdlc/command-error/v1",
      command: "produce-image",
      status: "error",
      error: { code: "IMAGE_PRODUCTION_FAILED" },
    });
    expect(JSON.parse(readFileSync(receipt, "utf8"))).toMatchObject({
      schema: "tc.sdlc/image-release/v1",
      status: "failed",
      sourceCommit: "0".repeat(40),
      reason: "source_commit_mismatch",
    });
    expect(JSON.parse(readFileSync(join(output, ".tc-sdlc-owner.json"), "utf8"))).toEqual({
      schema: "tc.sdlc/evidence-owner/v1",
      owner: "@three-cubes/tc-sdlc",
    });
  });
});
