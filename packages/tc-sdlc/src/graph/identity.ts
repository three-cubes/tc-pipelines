import { digest } from "../canonical.js";
import type {
  InputDigest,
  TaskDeclaration,
  TaskIdentity,
} from "../schema/types.js";
import { assertRelativePath, normalisePath } from "./path.js";

function sorted(values: readonly string[]): readonly string[] {
  return [...values].sort((left, right) =>
    left < right ? -1 : left > right ? 1 : 0,
  );
}

export function taskIdentity(
  task: TaskDeclaration,
  inputs: readonly InputDigest[],
  lockDigest: string,
): TaskIdentity {
  assertRelativePath(task.projectRoot, "task project root");
  for (const path of [
    ...task.inputs,
    ...(task.sharedInputs ?? []),
    ...task.outputs,
  ]) {
    assertRelativePath(path, "task declared path");
  }
  for (const input of inputs) {
    assertRelativePath(input.path, "task input digest path");
  }
  return digest({
    task: {
      project: task.project,
      target: task.target,
      projectRoot: normalisePath(task.projectRoot),
      ...(task.command === undefined ? {} : { command: task.command }),
      ...(task.executor === undefined ? {} : { executor: task.executor }),
      dependsOn: sorted(task.dependsOn),
      inputs: sorted(task.inputs.map(normalisePath)),
      sharedInputs: sorted((task.sharedInputs ?? []).map(normalisePath)),
      outputs: sorted(task.outputs.map(normalisePath)),
    },
    inputs: inputs
      .map((input) => ({
        path: normalisePath(input.path),
        digest: input.digest,
      }))
      .sort((left, right) =>
        left.path === right.path
          ? left.digest < right.digest
            ? -1
            : left.digest > right.digest
              ? 1
              : 0
          : left.path < right.path
            ? -1
            : 1,
      ),
    lockDigest,
  });
}
