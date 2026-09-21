import * as sdlc from "../dist/index.js";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

import { describe, expect, test } from "vitest";

const CLI = fileURLToPath(new URL("../dist/cli.js", import.meta.url));
const BUILD_RELEASE = fileURLToPath(
  new URL("../../../images/sdlc/build-release.mjs", import.meta.url),
);
const VERIFY_IMAGE = fileURLToPath(
  new URL("../../../images/sdlc/verify.mjs", import.meta.url),
);
const repository = fileURLToPath(new URL("../../..", import.meta.url));
const workflowCommit = "1234567890abcdef1234567890abcdef12345678";
const imageDigest =
  "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

describe("tc-sdlc release catalogue generation", () => {
  test("generates and atomically writes one complete catalogue from immutable release inputs", () => {
    const catalogue = (sdlc as Record<string, any>).generateReleaseCatalogue({
      releaseVersion: "3.0.0",
      workflowCommit,
      imageDigest,
    });

    expect(catalogue).toEqual({
      schema: "tc.sdlc/release-catalogue/v1",
      release: {
        version: "3.0.0",
        package: { name: "@three-cubes/tc-sdlc", version: "3.0.0" },
        workflowCommit,
        imageDigest,
        declarationSchema: "tc.sdlc/v1",
        lockSchema: "tc.sdlc/lock/v1",
        fitness: { package: "three-cubes-fitness", version: "0.17.0" },
        toolchains: {
          node: "24",
          packageManager: "pnpm@11.22.0",
          python: "3.13",
          uv: "0.12.5",
        },
        bootstrap: sdlc.CANONICAL_SDLC_BOOTSTRAP,
      },
    });

    const directory = mkdtempSync(join(tmpdir(), "tc-sdlc-catalogue-"));
    const output = join(directory, "catalogue.json");
    (sdlc as Record<string, any>).writeReleaseCatalogue(output, catalogue);
    expect(readFileSync(output, "utf8")).toBe(sdlc.canonicalJson(catalogue));
  });

  test.each([
    { workflowCommit: "main", imageDigest, label: "moving workflow ref" },
    {
      workflowCommit,
      imageDigest: "ghcr.io/three-cubes/sdlc:latest",
      label: "moving image ref",
    },
    { workflowCommit: "unresolved", imageDigest: "unresolved", label: "unresolved refs" },
  ])("rejects $label before writing a catalogue", (input) => {
    const output = join(
      mkdtempSync(join(tmpdir(), "tc-sdlc-catalogue-reject-")),
      "catalogue.json",
    );
    let failure: unknown;
    try {
      (sdlc as Record<string, any>).writeReleaseCatalogue(
        output,
        (sdlc as Record<string, any>).generateReleaseCatalogue({
          releaseVersion: "3.0.0",
          workflowCommit: input.workflowCommit,
          imageDigest: input.imageDigest,
        }),
      );
    } catch (error) {
      failure = error;
    }
    expect(failure).toMatchObject({ code: "SCHEMA_INVALID" });
    expect(() => readFileSync(output, "utf8")).toThrow();
  });

  test("exposes deterministic catalogue generation through the built CLI", () => {
    const output = join(
      mkdtempSync(join(tmpdir(), "tc-sdlc-catalogue-cli-")),
      "catalogue.json",
    );
    const result = spawnSync(
      process.execPath,
      [
        CLI,
        "catalogue",
        "--version", "3.0.0",
        "--workflow-commit", workflowCommit,
        "--image-digest", imageDigest,
        "--output", output,
      ],
      { encoding: "utf8" },
    );

    expect(result.status, result.stderr).toBe(0);
    expect(result.stderr).toBe("");
    expect(JSON.parse(result.stdout)).toMatchObject({
      schema: "tc.sdlc/command-result/v1",
      command: "catalogue",
      status: "ok",
      release: "3.0.0",
      catalogueDigest: expect.stringMatching(/^sha256:[a-f0-9]{64}$/),
    });
    expect(JSON.parse(readFileSync(output, "utf8"))).toMatchObject({
      release: { version: "3.0.0", workflowCommit, imageDigest },
    });
  });

  test("requires a new caller-selected repository artifact directory and preserves existing bytes", () => {
    const outside = join(mkdtempSync(join(tmpdir(), "tc-sdlc-unmanaged-artifact-")), "release");
    const unmanaged = spawnSync(
      process.execPath,
      [BUILD_RELEASE, "--artifact-output", outside],
      { encoding: "utf8", cwd: repository },
    );
    expect(unmanaged.status).not.toBe(0);
    expect(unmanaged.stderr).toContain("artifact output must be a direct child of the repository artifacts directory");
    expect(existsSync(outside)).toBe(false);

    const artifacts = join(repository, "artifacts");
    mkdirSync(artifacts, { recursive: true });
    const existing = join(artifacts, `preserved-${process.pid}`);
    mkdirSync(existing);
    const marker = join(existing, "preserve");
    writeFileSync(marker, "unchanged");
    try {
      const overwrite = spawnSync(
        process.execPath,
        [BUILD_RELEASE, "--artifact-output", existing],
        { encoding: "utf8", cwd: repository },
      );
      expect(overwrite.status).not.toBe(0);
      expect(overwrite.stderr).toContain("artifact output already exists");
      expect(readFileSync(marker, "utf8")).toBe("unchanged");
    } finally {
      rmSync(existing, { recursive: true, force: true });
    }
  });

  test("image verification requires explicit scratch and retained evidence locations", () => {
    const result = spawnSync(
      process.execPath,
      [
        VERIFY_IMAGE,
        "--image", "tc-sdlc:unused",
        "--image-digest", imageDigest,
        "--workflow-commit", workflowCommit,
      ],
      { encoding: "utf8", cwd: repository },
    );

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("missing --scratch-root");
  });
});
