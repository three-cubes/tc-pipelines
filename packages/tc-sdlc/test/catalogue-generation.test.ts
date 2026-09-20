import * as sdlc from "../dist/index.js";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

import { describe, expect, test } from "vitest";

const CLI = fileURLToPath(new URL("../dist/cli.js", import.meta.url));
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
});
