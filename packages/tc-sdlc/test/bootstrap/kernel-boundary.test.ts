import { spawn } from "node:child_process";
import { createServer } from "node:net";
import {
  existsSync,
  mkdtempSync,
  mkdirSync,
  rmSync,
  symlinkSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, test } from "vitest";

import {
  acquireBootstrapKernelBoundary,
  bootstrapKernelBoundaryPort,
  BootstrapKernelBoundaryError,
  releaseBootstrapKernelBoundary,
} from "../../src/bootstrap/kernel-boundary.js";

const roots: string[] = [];

function tempRoot(): string {
  const path = mkdtempSync(join(tmpdir(), "tc-sdlc-kernel-boundary-"));
  roots.push(path);
  return path;
}

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

describe("bootstrap kernel boundary", () => {
  test("serializes the same authority key and releases for the next owner", async () => {
    const root = tempRoot();
    const first = await acquireBootstrapKernelBoundary(
      root,
      "bootstrap-state-materialization",
      { stateKey: "releases/a" },
    );
    await expect(acquireBootstrapKernelBoundary(
      root,
      "bootstrap-state-materialization",
      { stateKey: "releases/a" },
      60,
    )).rejects.toMatchObject({ kind: "busy" });
    releaseBootstrapKernelBoundary(first);
    const second = await acquireBootstrapKernelBoundary(
      root,
      "bootstrap-state-materialization",
      { stateKey: "releases/a" },
    );
    releaseBootstrapKernelBoundary(second);
  });

  test("canonicalises root aliases and keeps boundary domains separate", async () => {
    const root = tempRoot();
    const alias = join(root, "alias");
    mkdirSync(join(root, "state"));
    symlinkSync(join(root, "state"), alias);
    const identity = { stateKey: "releases/a" };
    const rootBoundary = await acquireBootstrapKernelBoundary(
      join(root, "state"),
      "bootstrap-state-materialization",
      identity,
    );
    expect(bootstrapKernelBoundaryPort(
      alias,
      "bootstrap-state-materialization",
      identity,
    )).toBe(rootBoundary.port);
    await expect(acquireBootstrapKernelBoundary(
      alias,
      "bootstrap-state-materialization",
      identity,
      60,
    )).rejects.toMatchObject({ kind: "busy" });
    const referenceBoundary = await acquireBootstrapKernelBoundary(
      join(root, "state"),
      "bootstrap-reference-recovery",
      identity,
    );
    expect(referenceBoundary.port).not.toBe(rootBoundary.port);
    releaseBootstrapKernelBoundary(referenceBoundary);
    releaseBootstrapKernelBoundary(rootBoundary);
  });

  test("identity fields named like authority fields cannot override the root or domain", () => {
    const root = tempRoot();
    const port = bootstrapKernelBoundaryPort(
      root,
      "bootstrap-state-materialization",
      {
        stateKey: "releases/a",
        boundary: "bootstrap-reference-recovery",
        stateRoot: "/tmp/foreign-state-root",
      },
    );
    const forgedAuthorityPort = bootstrapKernelBoundaryPort(
      tmpdir(),
      "bootstrap-reference-recovery",
      { stateKey: "releases/a" },
    );
    expect(port).not.toBe(forgedAuthorityPort);
  });

  test("an unrelated listener on the deterministic port fails closed", async () => {
    const root = tempRoot();
    const domain = "bootstrap-state-materialization";
    const identity = { stateKey: "releases/occupied" };
    const port = bootstrapKernelBoundaryPort(root, domain, identity);
    const listener = createServer();
    await new Promise<void>((resolve, reject) => {
      listener.once("error", reject);
      listener.listen({ host: "127.0.0.1", port, exclusive: true }, () => resolve());
    });
    try {
      await expect(acquireBootstrapKernelBoundary(root, domain, identity, 60))
        .rejects.toBeInstanceOf(BootstrapKernelBoundaryError);
      await expect(acquireBootstrapKernelBoundary(root, domain, identity, 60))
        .rejects.toMatchObject({ kind: "busy" });
    } finally {
      await new Promise<void>((resolve, reject) => {
        listener.close((error) => error === undefined ? resolve() : reject(error));
      });
    }
  });

  test("the kernel releases ownership when the process holding it is killed", async () => {
    const root = tempRoot();
    const modulePath = fileURLToPath(new URL("../../dist/bootstrap/kernel-boundary.js", import.meta.url));
    expect(existsSync(modulePath)).toBe(true);
    const source = [
      `import { acquireBootstrapKernelBoundary } from ${JSON.stringify(new URL(`file://${modulePath}`).href)};`,
      `await acquireBootstrapKernelBoundary(${JSON.stringify(root)}, "bootstrap-state-materialization", { stateKey: "releases/crash" });`,
      `process.stdout.write("BOUNDARY_HELD\\n");`,
      `setInterval(() => {}, 1000);`,
    ].join("\n");
    const child = spawn(process.execPath, ["--input-type=module", "-e", source], {
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    await new Promise<void>((resolve, reject) => {
      child.stdout.on("data", (chunk: Buffer) => {
        stdout += chunk.toString("utf8");
        if (stdout.includes("BOUNDARY_HELD\n")) resolve();
      });
      child.once("error", reject);
      child.once("exit", (code) => reject(new Error(`boundary child exited before ready: ${code}`)));
    });
    child.kill("SIGKILL");
    await new Promise<void>((resolve, reject) => {
      child.once("exit", (code, signal) => {
        if (signal === "SIGKILL" || code !== null) resolve();
        else reject(new Error(`unexpected child termination: ${signal}`));
      });
    });
    const acquired = await acquireBootstrapKernelBoundary(
      root,
      "bootstrap-state-materialization",
      { stateKey: "releases/crash" },
    );
    releaseBootstrapKernelBoundary(acquired);
  });
});
