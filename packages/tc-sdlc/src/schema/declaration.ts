import { readFileSync } from "node:fs";
import { posix } from "node:path";

import { parse } from "yaml";

import { SdlcError } from "../errors.js";
import type { SdlcDeclaration } from "./types.js";
import { assertSchema } from "./validation.js";

function normalisePath(value: string): string {
  return posix.normalize(value.replaceAll("\\", "/"));
}

function normalisePaths(declaration: SdlcDeclaration): SdlcDeclaration {
  return {
    ...declaration,
    projects: declaration.projects
      .map((project) => ({
        ...project,
        root: normalisePath(project.root),
        ...(project.dependsOn === undefined
          ? {}
          : { dependsOn: [...project.dependsOn].sort() }),
      }))
      .sort((left, right) =>
        left.name < right.name ? -1 : left.name > right.name ? 1 : 0,
      ),
    targets: Object.fromEntries(
      Object.entries(declaration.targets).map(([name, target]) => [
        name,
        {
          ...target,
          ...(target.dependsOn === undefined
            ? {}
            : { dependsOn: [...target.dependsOn].sort() }),
          ...(target.inputs === undefined
            ? {}
            : { inputs: target.inputs.map(normalisePath).sort() }),
          ...(target.sharedInputs === undefined
            ? {}
            : { sharedInputs: target.sharedInputs.map(normalisePath).sort() }),
          ...(target.outputs === undefined
            ? {}
            : { outputs: target.outputs.map(normalisePath).sort() }),
          ...(target.resources === undefined
            ? {}
            : {
                resources: {
                  ...target.resources,
                  ports: [...target.resources.ports].sort(
                    (left, right) => left - right,
                  ),
                  exclusive: [...target.resources.exclusive].sort(),
                },
              }),
        },
      ]),
    ),
  };
}

export function validateDeclaration(value: unknown): SdlcDeclaration {
  assertSchema<SdlcDeclaration>("sdlc-v1.schema.json", value, "declaration");
  return normalisePaths(value);
}

export function loadDeclaration(path: string): SdlcDeclaration {
  let parsed: unknown;
  try {
    parsed = parse(readFileSync(path, "utf8"), { uniqueKeys: true });
  } catch (error) {
    throw new SdlcError(
      "DECLARATION_READ_FAILED",
      `could not read declaration ${path}: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
  return validateDeclaration(parsed);
}
