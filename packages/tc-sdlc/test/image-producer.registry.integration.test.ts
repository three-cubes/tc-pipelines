import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { beforeAll, describe, expect, test } from "vitest";

const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const TIMEOUT_MS = 120_000;
const REGISTRY_IMAGE = "registry:2@sha256:a3d8aaa63ed8681a604f1dea0aa03f100d5895b6a58ace528858a7b332415373";

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

function sha256(bytes: Buffer | string): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

function executable(name: string): string {
  return execFileSync("which", [name], { encoding: "utf8", timeout: TIMEOUT_MS }).trim();
}

function dockerRuntime(docker: string): Readonly<{ buildx: string; endpoint: string }> {
  const plugins = JSON.parse(execFileSync(
    docker,
    ["info", "--format", "{{json .ClientInfo.Plugins}}"],
    { encoding: "utf8", timeout: TIMEOUT_MS },
  )) as Array<{ Name?: string; Path?: string }>;
  const buildx = process.env.TC_SDLC_TEST_BUILDX
    ?? [
      plugins.find((plugin) => plugin.Name === "buildx")?.Path,
      "/usr/libexec/docker/cli-plugins/docker-buildx",
      "/usr/lib/docker/cli-plugins/docker-buildx",
      "/usr/local/lib/docker/cli-plugins/docker-buildx",
      "/opt/homebrew/lib/docker/cli-plugins/docker-buildx",
    ].find((path) => path !== undefined && existsSync(path));
  if (buildx === undefined || !existsSync(buildx)) throw new Error("Docker Buildx plugin executable is unavailable");
  const endpoint = process.env.TC_SDLC_TEST_DOCKER_ENDPOINT ?? JSON.parse(execFileSync(
    docker,
    ["context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"],
    { encoding: "utf8", timeout: TIMEOUT_MS },
  )) as string;
  return { buildx, endpoint };
}

async function registryManifest(candidate: string, reference: string): Promise<{ bytes: Buffer; value: any }> {
  const [host, ...segments] = candidate.split("/");
  const repository = segments.join("/").replace(/:[^:]+$/, "");
  const response = await fetch(`http://${host}/v2/${repository}/manifests/${reference}`, {
    headers: { Accept: "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json" },
    signal: AbortSignal.timeout(30_000),
  });
  expect(response.status).toBe(200);
  const bytes = Buffer.from(await response.arrayBuffer());
  return { bytes, value: JSON.parse(bytes.toString("utf8")) };
}

async function waitForRegistry(host: string): Promise<void> {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://${host}/v2/`, { signal: AbortSignal.timeout(1_000) });
      if (response.ok) return;
    } catch {}
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 50));
  }
  throw new Error("registry did not become ready");
}

function productionSourceFixture(payload = "portable image payload\n") {
  const root = mkdtempSync(join(tmpdir(), "tc-sdlc-image-production-source-"));
  mkdirSync(join(root, "images", "sdlc"), { recursive: true });
  mkdirSync(join(root, "packages", "tc-sdlc"), { recursive: true });
  writeFileSync(join(root, "packages", "tc-sdlc", "package.json"), canonical({ name: "@three-cubes/tc-sdlc", version: "3.0.0" }));
  writeFileSync(join(root, "payload.txt"), payload);
  writeFileSync(join(root, "images", "sdlc", "Dockerfile"), [
    "FROM scratch",
    "ARG SOURCE_COMMIT",
    "ARG SOURCE_INPUT_DIGEST",
    "ARG SDLC_VERSION",
    "LABEL org.opencontainers.image.revision=$SOURCE_COMMIT",
    "LABEL io.three-cubes.sdlc.inputs=$SOURCE_INPUT_DIGEST",
    "LABEL org.opencontainers.image.version=$SDLC_VERSION",
    "COPY payload.txt /payload.txt",
    "",
  ].join("\n"));
  execFileSync("git", ["init", "-q"], { cwd: root, timeout: TIMEOUT_MS });
  execFileSync("git", ["add", "."], { cwd: root, timeout: TIMEOUT_MS });
  execFileSync("git", ["-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], { cwd: root, timeout: TIMEOUT_MS });
  return { root, commit: execFileSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8", timeout: TIMEOUT_MS }).trim() };
}

describe("tc-sdlc produce-image registry publication", () => {
  let cli: string;

  beforeAll(() => { cli = installPackedCli(); }, 30_000);

  test("publishes and safely reuses an immutable multi-platform candidate without running it", async () => {
    const docker = executable("docker");
    const gitExecutable = executable("git");
    const { buildx, endpoint } = dockerRuntime(docker);
    const source = productionSourceFixture();
    const runRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-image-registry-run-"));
    const state = join(runRoot, "state");
    const invocationLog = join(runRoot, "buildx-invocations.log");
    const wrapper = join(runRoot, "buildx");
    const registryName = `tc-sdlc-producer-${process.pid}`;
    mkdirSync(state);
    writeFileSync(join(state, ".tc-sdlc-owner.json"), canonical({ schema: "tc.sdlc/state-owner/v1", owner: "@three-cubes/tc-sdlc" }));
    writeFileSync(wrapper, `#!/bin/sh\nprintf '%s\\n' "$*" >> '${invocationLog}'\nexec '${buildx}' "$@"\n`);
    chmodSync(wrapper, 0o755);
    let candidate = "";
    try {
      execFileSync(docker, ["run", "--detach", "--name", registryName, "--publish", "127.0.0.1::5000", REGISTRY_IMAGE], { timeout: TIMEOUT_MS });
      const port = execFileSync(docker, ["port", registryName, "5000/tcp"], { encoding: "utf8", timeout: TIMEOUT_MS }).trim().split(":").at(-1)!;
      candidate = `localhost:${port}/sdlc:candidate`;
      await waitForRegistry(`localhost:${port}`);

      const invoke = (suffix: string, selectedSource = source) => {
        const output = join(runRoot, `evidence-${suffix}`);
        const receipt = join(output, "image-release.json");
        const result = spawnSync(cli, [
          "produce-image",
          "--source-root", selectedSource.root,
          "--source-commit", selectedSource.commit,
          "--dockerfile", join(selectedSource.root, "images", "sdlc", "Dockerfile"),
          "--registry-candidate", candidate,
          "--docker-endpoint", endpoint,
          "--buildx-executable", wrapper,
          "--git-executable", gitExecutable,
          "--state-root", state,
          "--output", output,
          "--receipt", receipt,
        ], { encoding: "utf8", timeout: 300_000 });
        return { output, result, receipt: JSON.parse(readFileSync(receipt, "utf8")) };
      };

      const first = invoke("first");
      expect(first.result.status, first.result.stderr).toBe(0);
      expect(first.receipt).toMatchObject({
        schema: "tc.sdlc/image-release/v1",
        status: "succeeded",
        reason: null,
        sourceCommit: source.commit,
        registryCandidate: candidate,
        platforms: ["linux/amd64", "linux/arm64"],
        reused: false,
      });
      expect(first.receipt.image).toBe(`${candidate.replace(/:[^/:]+$/, "")}@${first.receipt.imageDigest}`);

      const remote = await registryManifest(candidate, first.receipt.imageDigest);
      expect(sha256(remote.bytes)).toBe(first.receipt.imageDigest);
      const platformDescriptors = remote.value.manifests.filter((descriptor: any) => descriptor.platform?.os === "linux" && ["amd64", "arm64"].includes(descriptor.platform?.architecture));
      expect(platformDescriptors.map((descriptor: any) => `${descriptor.platform.os}/${descriptor.platform.architecture}`).sort()).toEqual(["linux/amd64", "linux/arm64"]);
      const attestations = JSON.parse(readFileSync(join(first.output, "attestations.json"), "utf8"));
      expect(attestations.map((entry: any) => entry.platform).sort()).toEqual(["linux/amd64", "linux/arm64"]);
      for (const entry of attestations) {
        expect(entry.subjectDigest).toMatch(/^sha256:[0-9a-f]{64}$/);
        expect(entry.statements.some((statement: any) => statement.predicateType?.startsWith("https://slsa.dev/provenance/"))).toBe(true);
        expect(entry.statements.some((statement: any) => statement.predicateType === "https://spdx.dev/Document")).toBe(true);
      }
      for (const [name, digest] of Object.entries(first.receipt.artifacts as Record<string, string>)) {
        expect(sha256(readFileSync(join(first.output, name)))).toBe(digest);
      }

      const second = invoke("reuse");
      expect(second.result.status, second.result.stderr).toBe(0);
      expect(second.receipt).toMatchObject({ status: "succeeded", reused: true, imageDigest: first.receipt.imageDigest, image: first.receipt.image });

      const divergentSource = productionSourceFixture("different source identity\n");
      try {
        const collision = invoke("collision", divergentSource);
        expect(collision.result.status).toBe(1);
        expect(collision.receipt).toMatchObject({
          status: "failed",
          reason: "image_production_failed",
          sourceCommit: divergentSource.commit,
        });
      } finally {
        rmSync(divergentSource.root, { recursive: true, force: true });
      }
      const invocations = readFileSync(invocationLog, "utf8");
      expect(invocations.match(/^build\s/gm)?.length).toBe(1);
      expect(invocations).not.toMatch(/(^|\s)(run|probe)(\s|$)/m);
      expect(execFileSync("git", ["status", "--porcelain=v1", "--untracked-files=all"], { cwd: source.root, encoding: "utf8", timeout: TIMEOUT_MS })).toBe("");
      expect(readdirSync(state).sort()).toEqual([".tc-sdlc-owner.json"]);
    } finally {
      spawnSync(docker, ["rm", "--force", registryName], { encoding: "utf8", timeout: TIMEOUT_MS });
      rmSync(source.root, { recursive: true, force: true });
      rmSync(runRoot, { recursive: true, force: true });
      expect(existsSync(source.root)).toBe(false);
      expect(existsSync(runRoot)).toBe(false);
    }
  }, 360_000);
});
