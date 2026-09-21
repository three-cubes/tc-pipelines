import * as sdlc from "../dist/index.js";
import { spawnSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, expect, test } from "vitest";

const dockerLink = ["/opt/homebrew/bin/docker", "/usr/local/bin/docker", "/usr/bin/docker"]
  .find(existsSync);
const docker = dockerLink === undefined ? undefined : realpathSync(dockerLink);
const buildxLink = [
  "/opt/homebrew/bin/docker-buildx",
  "/usr/local/bin/docker-buildx",
  "/usr/bin/docker-buildx",
].find(existsSync);
const buildx = buildxLink === undefined ? undefined : realpathSync(buildxLink);
const endpointResult =
  docker === undefined
    ? undefined
    : spawnSync(docker, ["context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], {
        encoding: "utf8",
      });
const endpoint = endpointResult?.status === 0 ? endpointResult.stdout.trim() : undefined;
const dockerAvailable =
  docker !== undefined &&
  buildx !== undefined &&
  endpoint !== undefined &&
  endpoint.length > 0 &&
  spawnSync(docker, ["info"], { stdio: "ignore" }).status === 0;
const roots: string[] = [];

function temporary(prefix: string): string {
  const value = mkdtempSync(join(tmpdir(), prefix));
  roots.push(value);
  return value;
}

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

test.runIf(dockerAvailable)(
  "retains recent cache then reclaims it only from an explicitly owned builder",
  async () => {
    const stateRoot = temporary("tc-sdlc-maintenance-docker-state-");
    const temporaryRoot = temporary("tc-sdlc-maintenance-docker-temp-");
    const evidence = temporary("tc-sdlc-maintenance-docker-evidence-");
    writeFileSync(
      join(stateRoot, ".tc-sdlc-owner.json"),
      sdlc.canonicalJson({
        schema: "tc.sdlc/state-owner/v1",
        owner: "@three-cubes/tc-sdlc",
      }),
    );
    const dockerConfig = join(stateRoot, "cache", "docker");
    mkdirSync(dockerConfig, { recursive: true });
    const builder = `tc-sdlc-maintenance-${process.pid}`;
    const environment = { ...process.env, DOCKER_CONFIG: dockerConfig };
    const created = spawnSync(
      buildx!,
      ["create", "--name", builder, "--driver", "docker-container", endpoint!],
      { encoding: "utf8", env: environment },
    );
    expect(created.status, created.stderr).toBe(0);
    const previous = {
      DOCKER_HOST: process.env.DOCKER_HOST,
      DOCKER_CONTEXT: process.env.DOCKER_CONTEXT,
      BUILDX_CONFIG: process.env.BUILDX_CONFIG,
      BUILDKIT_HOST: process.env.BUILDKIT_HOST,
    };
    try {
      const bootstrapped = spawnSync(buildx!, ["inspect", "--builder", builder, "--bootstrap"], {
        encoding: "utf8",
        env: environment,
        timeout: 120_000,
      });
      expect(bootstrapped.status, bootstrapped.stderr).toBe(0);
      const context = temporary("tc-sdlc-maintenance-docker-context-");
      writeFileSync(join(context, "Dockerfile"), "FROM scratch\nCOPY payload /payload\n");
      writeFileSync(join(context, "payload"), Buffer.alloc(2 * 1024 * 1024, "x"));
      const built = spawnSync(
        buildx!,
        [
          "build",
          "--builder", builder,
          "--output", "type=cacheonly",
          context,
        ],
        { encoding: "utf8", env: environment, timeout: 120_000 },
      );
      expect(built.status, built.stderr).toBe(0);

      process.env.DOCKER_HOST = "unix:///foreign-denied.sock";
      process.env.DOCKER_CONTEXT = "foreign-context";
      process.env.BUILDX_CONFIG = join(temporaryRoot, "foreign-buildx");
      process.env.BUILDKIT_HOST = "tcp://127.0.0.1:1";
      const retained = await sdlc.maintain({
        stateRoot,
        temporaryRoot,
        receiptPath: join(evidence, "retained.json"),
        mode: "apply",
        retentionHours: 48,
        buildxExecutable: buildx!,
        dockerBuilder: builder,
      });
      expect(retained).toMatchObject({
        status: "succeeded",
        tools: { buildkit: { status: "pruned", reclaimedBytes: 0 } },
      });
      const expired = await sdlc.maintain({
        stateRoot,
        temporaryRoot,
        receiptPath: join(evidence, "expired.json"),
        mode: "apply",
        retentionHours: 0,
        buildxExecutable: buildx!,
        dockerBuilder: builder,
      });
      expect(expired).toMatchObject({
        status: "succeeded",
        tools: { buildkit: { status: "pruned" } },
      });
      expect(expired.tools.buildkit.reclaimedBytes).toBeGreaterThan(0);
    } finally {
      for (const [name, value] of Object.entries(previous)) {
        if (value === undefined) delete process.env[name];
        else process.env[name] = value;
      }
      spawnSync(buildx!, ["rm", "--force", builder], {
        stdio: "ignore",
        env: environment,
      });
    }
  },
  180_000,
);
