import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { beforeEach, describe, expect, test } from "vitest";

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
  writeFileSync(join(root, ".gitignore"), "ignored.txt\n");
  execFileSync("git", ["init", "-q"], { cwd: root });
  execFileSync("git", ["add", "."], { cwd: root });
  execFileSync("git", ["-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], { cwd: root });
  return { root, commit: execFileSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8" }).trim() };
}

function sha256(bytes: Buffer | string): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

function sourceInputDigest(root: string, gitExecutable: string): string {
  const paths = execFileSync(gitExecutable, ["ls-files", "-z"], {
    cwd: root,
    encoding: "utf8",
    timeout: TIMEOUT_MS,
  }).split("\0").filter(Boolean).sort();
  return sha256(canonical(Object.fromEntries(paths.map((path) => [path, sha256(readFileSync(join(root, path)))]))));
}

describe("tc-sdlc produce-image", () => {
  let cli: string;

  beforeEach(() => { cli = installPackedCli(); }, 30_000);

  test("retains terminal producer evidence when preflight rejects the source identity", () => {
    const source = sourceFixture();
    const runRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-image-run-"));
    const state = join(runRoot, "state");
    const output = join(runRoot, "evidence");
    const receipt = join(output, "image-release.json");
    const buildx = join(runRoot, "buildx");
    const gitExecutable = execFileSync("which", ["git"], { encoding: "utf8", timeout: TIMEOUT_MS }).trim();
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
      "--git-executable", gitExecutable,
      "--state-root", state,
      "--output", output,
      "--receipt", receipt,
    ], { encoding: "utf8", timeout: TIMEOUT_MS });

    expect(result.error).toBeUndefined();
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

  test("retains a schema-valid receipt when the supplied source id is malformed", () => {
    const source = sourceFixture();
    const runRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-image-malformed-source-"));
    const state = join(runRoot, "state");
    const output = join(runRoot, "evidence");
    const receipt = join(output, "image-release.json");
    const buildx = join(runRoot, "buildx");
    const gitExecutable = execFileSync("which", ["git"], { encoding: "utf8", timeout: TIMEOUT_MS }).trim();
    mkdirSync(state);
    writeFileSync(join(state, ".tc-sdlc-owner.json"), canonical({ schema: "tc.sdlc/state-owner/v1", owner: "@three-cubes/tc-sdlc" }));
    writeFileSync(buildx, "#!/bin/sh\nexit 99\n");
    chmodSync(buildx, 0o755);

    const result = spawnSync(cli, [
      "produce-image",
      "--source-root", source.root,
      "--source-commit", "not-a-git-object",
      "--dockerfile", join(source.root, "images", "sdlc", "Dockerfile"),
      "--registry-candidate", "localhost:1/sdlc:candidate",
      "--docker-endpoint", "unix:///missing.sock",
      "--buildx-executable", buildx,
      "--git-executable", gitExecutable,
      "--state-root", state,
      "--output", output,
      "--receipt", receipt,
    ], { encoding: "utf8", timeout: TIMEOUT_MS });

    expect(result.error).toBeUndefined();
    expect(result.status).toBe(1);
    expect(JSON.parse(result.stderr)).toMatchObject({
      command: "produce-image",
      error: { code: "IMAGE_PRODUCTION_FAILED" },
    });
    expect(JSON.parse(readFileSync(receipt, "utf8"))).toEqual({
      schema: "tc.sdlc/image-release/v1",
      status: "failed",
      reason: "image_production_input_invalid",
      sourceCommit: null,
      sourceTree: null,
      sourceInputDigest: null,
      registryCandidate: "localhost:1/sdlc:candidate",
      imageDigest: null,
      image: null,
      platforms: [],
      reused: false,
      artifacts: {},
      lifecycle: {
        class: "release-artifact-evidence",
        owner: "@three-cubes/tc-sdlc",
        retain: "catalogue-current-predecessor-or-incident-reference",
      },
    });
  });

  test("retains terminal evidence when CLI parsing fails after safe output coordinates", () => {
    const source = sourceFixture();
    const runRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-image-usage-"));
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
      "--source-commit", source.commit,
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
      command: "produce-image",
      error: { code: "USAGE" },
    });
    expect(JSON.parse(readFileSync(receipt, "utf8"))).toMatchObject({
      schema: "tc.sdlc/image-release/v1",
      status: "failed",
      reason: "image_production_usage_invalid",
      sourceCommit: source.commit,
      sourceTree: null,
    });
  });

  test("preserves a colliding foreign output and uses an independent terminal receipt", () => {
    const source = sourceFixture();
    const runRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-image-output-collision-"));
    const state = join(runRoot, "state");
    const output = join(runRoot, "foreign-output");
    const receipt = join(runRoot, "terminal-image-release.json");
    const buildx = join(runRoot, "buildx");
    mkdirSync(state);
    mkdirSync(output);
    writeFileSync(join(output, "foreign.txt"), "must remain untouched\n");
    writeFileSync(join(state, ".tc-sdlc-owner.json"), canonical({ schema: "tc.sdlc/state-owner/v1", owner: "@three-cubes/tc-sdlc" }));
    writeFileSync(buildx, "#!/bin/sh\nexit 99\n");
    chmodSync(buildx, 0o755);

    const result = spawnSync(cli, [
      "produce-image",
      "--source-root", source.root,
      "--source-commit", source.commit,
      "--dockerfile", join(source.root, "images", "sdlc", "Dockerfile"),
      "--registry-candidate", "localhost:1/sdlc:candidate",
      "--docker-endpoint", "unix:///missing.sock",
      "--buildx-executable", buildx,
      "--state-root", state,
      "--output", output,
      "--receipt", receipt,
    ], { encoding: "utf8", timeout: TIMEOUT_MS });

    expect(result.status).toBe(1);
    expect(readFileSync(join(output, "foreign.txt"), "utf8")).toBe("must remain untouched\n");
    expect(JSON.parse(readFileSync(receipt, "utf8"))).toMatchObject({
      schema: "tc.sdlc/image-release/v1",
      status: "failed",
      reason: "image_production_usage_invalid",
      sourceCommit: source.commit,
      sourceTree: null,
      sourceInputDigest: null,
    });
  });

  test("rejects a dirty checkout before image production while retaining its committed identity", () => {
    const source = sourceFixture();
    const runRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-image-dirty-source-"));
    const state = join(runRoot, "state");
    const output = join(runRoot, "evidence");
    const receipt = join(output, "image-release.json");
    const buildx = join(runRoot, "buildx");
    const gitExecutable = execFileSync("which", ["git"], { encoding: "utf8", timeout: TIMEOUT_MS }).trim();
    mkdirSync(state);
    writeFileSync(join(state, ".tc-sdlc-owner.json"), canonical({ schema: "tc.sdlc/state-owner/v1", owner: "@three-cubes/tc-sdlc" }));
    writeFileSync(buildx, "#!/bin/sh\nexit 99\n");
    chmodSync(buildx, 0o755);
    writeFileSync(join(source.root, "uncommitted.txt"), "must not be a build input\n");

    const result = spawnSync(cli, [
      "produce-image",
      "--source-root", source.root,
      "--source-commit", source.commit,
      "--dockerfile", join(source.root, "images", "sdlc", "Dockerfile"),
      "--registry-candidate", "localhost:1/sdlc:candidate",
      "--docker-endpoint", "unix:///missing.sock",
      "--buildx-executable", buildx,
      "--git-executable", gitExecutable,
      "--state-root", state,
      "--output", output,
      "--receipt", receipt,
    ], { encoding: "utf8", timeout: TIMEOUT_MS });

    expect(result.status).toBe(1);
    expect(JSON.parse(readFileSync(receipt, "utf8"))).toMatchObject({
      schema: "tc.sdlc/image-release/v1",
      status: "failed",
      reason: "source_tree_dirty",
      sourceCommit: source.commit,
      sourceTree: null,
    });
  });

  test("binds the clean committed source tree before later image work", () => {
    const source = sourceFixture();
    const runRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-image-clean-source-"));
    const state = join(runRoot, "state");
    const output = join(runRoot, "evidence");
    const receipt = join(output, "image-release.json");
    const buildx = join(runRoot, "buildx");
    const gitExecutable = execFileSync("which", ["git"], { encoding: "utf8", timeout: TIMEOUT_MS }).trim();
    const sourceTree = execFileSync(gitExecutable, ["rev-parse", `${source.commit}^{tree}`], { cwd: source.root, encoding: "utf8", timeout: TIMEOUT_MS }).trim();
    const inputs = sourceInputDigest(source.root, gitExecutable);
    mkdirSync(state);
    writeFileSync(join(state, ".tc-sdlc-owner.json"), canonical({ schema: "tc.sdlc/state-owner/v1", owner: "@three-cubes/tc-sdlc" }));
    writeFileSync(buildx, "#!/bin/sh\nexit 99\n");
    chmodSync(buildx, 0o755);

    const result = spawnSync(cli, [
      "produce-image",
      "--source-root", source.root,
      "--source-commit", source.commit,
      "--dockerfile", join(source.root, "images", "sdlc", "Dockerfile"),
      "--registry-candidate", "localhost:1/sdlc:candidate",
      "--docker-endpoint", "unix:///missing.sock",
      "--buildx-executable", buildx,
      "--git-executable", gitExecutable,
      "--state-root", state,
      "--output", output,
      "--receipt", receipt,
    ], { encoding: "utf8", timeout: TIMEOUT_MS });

    expect(result.status).toBe(1);
    expect(JSON.parse(readFileSync(receipt, "utf8"))).toMatchObject({
      schema: "tc.sdlc/image-release/v1",
      status: "failed",
      reason: "image_production_failed",
      sourceCommit: source.commit,
      sourceTree,
      sourceInputDigest: inputs,
    });
  });

  test("uses the required Git executable instead of a hostile PATH shadow", () => {
    const source = sourceFixture();
    const runRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-image-git-shadow-"));
    const state = join(runRoot, "state");
    const output = join(runRoot, "evidence");
    const receipt = join(output, "image-release.json");
    const buildx = join(runRoot, "buildx");
    const shadow = join(runRoot, "shadow");
    const shadowUsed = join(runRoot, "shadow-used");
    const gitExecutable = execFileSync("which", ["git"], { encoding: "utf8", timeout: TIMEOUT_MS }).trim();
    mkdirSync(state);
    mkdirSync(shadow);
    writeFileSync(join(state, ".tc-sdlc-owner.json"), canonical({ schema: "tc.sdlc/state-owner/v1", owner: "@three-cubes/tc-sdlc" }));
    writeFileSync(buildx, "#!/bin/sh\nexit 99\n");
    writeFileSync(join(shadow, "git"), `#!/bin/sh\nprintf shadow > '${shadowUsed}'\nprintf '%s\\n' '${source.commit}'\n`);
    chmodSync(buildx, 0o755);
    chmodSync(join(shadow, "git"), 0o755);

    const result = spawnSync(cli, [
      "produce-image",
      "--source-root", source.root,
      "--source-commit", source.commit,
      "--dockerfile", join(source.root, "images", "sdlc", "Dockerfile"),
      "--registry-candidate", "localhost:1/sdlc:candidate",
      "--docker-endpoint", "unix:///missing.sock",
      "--buildx-executable", buildx,
      "--git-executable", gitExecutable,
      "--state-root", state,
      "--output", output,
      "--receipt", receipt,
    ], {
      encoding: "utf8",
      timeout: TIMEOUT_MS,
      env: { ...process.env, PATH: `${shadow}:${process.env.PATH ?? "/usr/bin:/bin"}` },
    });

    expect(result.status).toBe(1);
    expect(existsSync(shadowUsed)).toBe(false);
    expect(JSON.parse(readFileSync(receipt, "utf8"))).toMatchObject({
      status: "failed",
      reason: "image_production_failed",
      sourceCommit: source.commit,
    });
  });

  test("materialises a tracked-only build context so ignored files cannot influence the image", () => {
    const source = sourceFixture();
    const runRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-image-tracked-context-"));
    const state = join(runRoot, "state");
    const output = join(runRoot, "evidence");
    const receipt = join(output, "image-release.json");
    const buildx = join(runRoot, "buildx");
    const contamination = join(runRoot, "ignored-file-reached-build-context");
    const gitExecutable = execFileSync("which", ["git"], { encoding: "utf8", timeout: TIMEOUT_MS }).trim();
    mkdirSync(state);
    writeFileSync(join(state, ".tc-sdlc-owner.json"), canonical({ schema: "tc.sdlc/state-owner/v1", owner: "@three-cubes/tc-sdlc" }));
    writeFileSync(join(source.root, "ignored.txt"), "must not enter the image context\n");
    writeFileSync(buildx, [
      "#!/bin/sh",
      "case \"$1\" in",
      "  imagetools) echo 'manifest unknown' >&2; exit 1 ;;",
      "  inspect) exit 1 ;;",
      "  create) exit 0 ;;",
      `  build) for argument in \"$@\"; do context=\"$argument\"; done; test ! -e \"$context/ignored.txt\" || printf contaminated > '${contamination}'; exit 99 ;;`,
      "  rm) exit 0 ;;",
      "esac",
      "exit 99",
      "",
    ].join("\n"));
    chmodSync(buildx, 0o755);

    const result = spawnSync(cli, [
      "produce-image",
      "--source-root", source.root,
      "--source-commit", source.commit,
      "--dockerfile", join(source.root, "images", "sdlc", "Dockerfile"),
      "--registry-candidate", "localhost:1/sdlc:candidate",
      "--docker-endpoint", "unix:///missing.sock",
      "--buildx-executable", buildx,
      "--git-executable", gitExecutable,
      "--state-root", state,
      "--output", output,
      "--receipt", receipt,
    ], { encoding: "utf8", timeout: TIMEOUT_MS });

    expect(result.status).toBe(1);
    expect(existsSync(contamination)).toBe(false);
    expect(readFileSync(join(source.root, "ignored.txt"), "utf8")).toBe("must not enter the image context\n");
    expect(JSON.parse(readFileSync(receipt, "utf8"))).toMatchObject({
      status: "failed",
      reason: "image_production_failed",
      sourceCommit: source.commit,
    });
    expect(readdirSync(state).sort()).toEqual([".tc-sdlc-owner.json"]);
  });

});
