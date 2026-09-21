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
  "prunes only an explicitly named builder in tc-sdlc-owned Docker state",
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
    try {
      const bootstrapped = spawnSync(buildx!, ["inspect", "--builder", builder, "--bootstrap"], {
        encoding: "utf8",
        env: environment,
        timeout: 120_000,
      });
      expect(bootstrapped.status, bootstrapped.stderr).toBe(0);
      const receipt = await sdlc.maintain({
        stateRoot,
        temporaryRoot,
        receiptPath: join(evidence, "receipt.json"),
        mode: "apply",
        retentionHours: 48,
        buildxExecutable: buildx!,
        dockerBuilder: builder,
      });
      expect(receipt).toMatchObject({
        status: "succeeded",
        tools: { buildkit: { status: "pruned", reclaimedBytes: expect.any(Number) } },
      });
    } finally {
      spawnSync(buildx!, ["rm", "--force", builder], {
        stdio: "ignore",
        env: environment,
      });
    }
  },
  30_000,
);
