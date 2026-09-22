import type {
  PathCaseSensitivity,
  TaskDeclaration,
} from "../schema/types.js";
import { normalisePath } from "./path.js";

export function resolveProjectPath(root: string, path: string): string {
  return path === "." ? root : normalisePath(`${root}/${path}`);
}

export function selectorPattern(
  selector: string,
  caseSensitivity: PathCaseSensitivity = "sensitive",
): RegExp {
  let pattern = "";
  for (let index = 0; index < selector.length; index += 1) {
    const character = selector[index] ?? "";
    if (character === "*" && selector[index + 1] === "*") {
      if (selector[index + 2] === "/") {
        pattern += "(?:.*/)?";
        index += 2;
      } else {
        pattern += ".*";
        index += 1;
      }
    } else if (character === "*") {
      pattern += "[^/]*";
    } else if (character === "?") {
      pattern += "[^/]";
    } else {
      pattern += character.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }
  }
  return new RegExp(
    `^${pattern}(?:/.*)?$`,
    caseSensitivity === "insensitive" ? "i" : "",
  );
}

export function taskConsumesPath(
  task: TaskDeclaration,
  path: string,
  caseSensitivity: PathCaseSensitivity = "sensitive",
): boolean {
  const canonicalPath = normalisePath(path);
  const pathIdentity =
    caseSensitivity === "insensitive"
      ? canonicalPath.toLowerCase()
      : canonicalPath;
  const rootIdentity =
    caseSensitivity === "insensitive"
      ? task.projectRoot.toLowerCase()
      : task.projectRoot;
  return (
    task.inputs.some((input) =>
      selectorPattern(
        resolveProjectPath(task.projectRoot, input),
        caseSensitivity,
      ).test(canonicalPath),
    ) ||
    (task.sharedInputs ?? []).some((input) =>
      selectorPattern(input, caseSensitivity).test(canonicalPath),
    ) ||
    (task.inputs.length === 0 &&
      (task.sharedInputs ?? []).length === 0 &&
      (pathIdentity === rootIdentity ||
        pathIdentity.startsWith(`${rootIdentity}/`)))
  );
}
