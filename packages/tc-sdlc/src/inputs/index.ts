import { createHash } from "node:crypto";
import {
  lstatSync,
  readFileSync,
  readlinkSync,
  readdirSync,
  realpathSync,
} from "node:fs";
import { relative, resolve, sep } from "node:path";

import { SdlcError } from "../errors.js";
import { taskConsumesPath } from "../graph/selector.js";
import type {
  InputDigest,
  SdlcDeclaration,
  TaskDeclaration,
  TaskInputDigests,
} from "../schema/types.js";
import { validateDeclaration } from "../schema/declaration.js";

function inside(root: string, path: string): boolean {
  const value = relative(root, path);
  return value === "" || (!value.startsWith(`..${sep}`) && value !== "..");
}

export function snapshotFiles(rootValue: string): readonly InputDigest[] {
  const root = realpathSync(rootValue);
  const values: InputDigest[] = [];
  const visit = (directory: string): void => {
    for (const name of readdirSync(directory).sort()) {
      if (directory === root && name === ".git") {
        continue;
      }
      const absolute = resolve(directory, name);
      const stat = lstatSync(absolute);
      const path = relative(root, absolute).split(sep).join("/");
      if (stat.isDirectory()) {
        visit(absolute);
        continue;
      }
      let bytes: Buffer;
      let symlink: string | null = null;
      if (stat.isSymbolicLink()) {
        symlink = readlinkSync(absolute);
        let target: string;
        try {
          target = realpathSync(absolute);
        } catch {
          throw new SdlcError("INPUT_PATH_INVALID", `broken symlink input: ${path}`);
        }
        if (!inside(root, target)) {
          throw new SdlcError("INPUT_PATH_INVALID", `symlink escapes repository: ${path}`);
        }
        if (!lstatSync(target).isFile()) {
          throw new SdlcError("INPUT_PATH_INVALID", `symlink input is not a file: ${path}`);
        }
        bytes = readFileSync(target);
      } else if (stat.isFile()) {
        bytes = readFileSync(absolute);
      } else {
        continue;
      }
      values.push({
        path,
        digest: `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
        mode: stat.mode & 0o777,
        symlink,
      });
    }
  };
  visit(root);
  return values;
}

export function resolveInputInventory(
  root: string,
  declaration: SdlcDeclaration,
): TaskInputDigests {
  const input = validateDeclaration(declaration);
  const files = snapshotFiles(root);
  return Object.fromEntries(
    Object.entries(input.targets)
      .sort(([left], [right]) => left.localeCompare(right))
      .flatMap(([targetName, target]) => {
        const projects = target.scope === "repository"
          ? [{ name: input.project, root: "." }]
          : [...input.projects].sort((left, right) => left.name.localeCompare(right.name));
        return projects.map((project) => {
            const task: TaskDeclaration = {
              project: project.name,
              target: targetName,
              projectRoot: project.root,
              mode: target.mode,
              trustBoundary: target.trustBoundary,
              ...(target.scope === undefined ? {} : { scope: target.scope }),
              ...(target.command === undefined ? {} : { command: target.command }),
              ...(target.executor === undefined ? {} : { executor: target.executor }),
              ...(target.profile === undefined ? {} : { profile: target.profile }),
              dependsOn: [],
              inputs: target.inputs ?? [],
              sharedInputs: target.sharedInputs ?? [],
              outputs: target.outputs ?? [],
              resources: target.resources,
              budget: target.budget,
            };
            return [
              `${project.name}:${targetName}`,
              files.filter((file) => taskConsumesPath(task, file.path)),
            ] as const;
          });
      }),
  );
}
