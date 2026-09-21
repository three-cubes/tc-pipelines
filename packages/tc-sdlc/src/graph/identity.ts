import { digest } from "../canonical.js";
import { SdlcError } from "../errors.js";
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

export function canonicalInputDigests(
  inputs: readonly InputDigest[],
): readonly InputDigest[] {
  const identities = new Set<string>();
  const canonical = inputs.map((input) => {
    assertRelativePath(input.path, "task input digest path");
    if (!/^sha256:[a-f0-9]{64}$/.test(input.digest)) {
      throw new SdlcError(
        "GRAPH_INPUT_DIGEST_INVALID",
        `task input digest is not canonical SHA-256: ${input.digest}`,
      );
    }
    const path = normalisePath(input.path);
    const identity = path.toLowerCase();
    if (identities.has(identity)) {
      throw new SdlcError(
        "GRAPH_INPUT_DIGEST_INVALID",
        `task input digests contain a platform-equivalent path: ${path}`,
      );
    }
    identities.add(identity);
    return {
      path,
      digest: input.digest,
      ...(input.mode === undefined ? {} : { mode: input.mode }),
      ...(input.symlink === undefined ? {} : { symlink: input.symlink }),
    };
  });
  return canonical.sort((left, right) =>
    left.path === right.path
      ? left.digest < right.digest
        ? -1
        : left.digest > right.digest
          ? 1
          : 0
      : left.path < right.path
        ? -1
        : 1,
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
  for (const item of task.evidence ?? []) {
    assertRelativePath(item.path, "task declared evidence path");
  }
  const canonicalInputs = canonicalInputDigests(inputs);
  return digest({
    task: {
      project: task.project,
      target: task.target,
      projectRoot: normalisePath(task.projectRoot),
      mode: task.mode,
      trustBoundary: task.trustBoundary,
      ...(task.command === undefined ? {} : { command: task.command }),
      ...(task.executor === undefined ? {} : { executor: task.executor }),
      dependsOn: sorted(task.dependsOn),
      inputs: sorted(task.inputs.map(normalisePath)),
      sharedInputs: sorted((task.sharedInputs ?? []).map(normalisePath)),
      outputs: sorted(task.outputs.map(normalisePath)),
      evidence: [...(task.evidence ?? [])]
        .map((item) => ({ path: normalisePath(item.path), mediaType: item.mediaType }))
        .sort((left, right) => left.path < right.path ? -1 : left.path > right.path ? 1 : 0),
      ...(task.resources === undefined
        ? {}
        : {
            resources: {
              cpu: task.resources.cpu,
              memoryMiB: task.resources.memoryMiB,
              ports: [...task.resources.ports].sort(
                (left, right) => left - right,
              ),
              exclusive: sorted(task.resources.exclusive),
            },
          }),
      ...(task.budget === undefined ? {} : { budget: task.budget }),
    },
    inputs: canonicalInputs,
    lockDigest,
  });
}
