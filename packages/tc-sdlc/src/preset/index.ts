import { SdlcError } from "../errors.js";
import { resolveExecutorContract } from "../executors/index.js";
import { canonicalInputDigests, taskIdentity } from "../graph/identity.js";
import { taskConsumesPath } from "../graph/selector.js";
import type {
  GraphProject,
  GraphTask,
  SdlcDeclaration,
  TaskDeclaration,
  TaskInputDigests,
} from "../schema/types.js";

function sorted(values: readonly string[]): readonly string[] {
  return [...values].sort((left, right) =>
    left < right ? -1 : left > right ? 1 : 0,
  );
}

export function buildPresetTasks(
  declaration: SdlcDeclaration,
  projects: readonly GraphProject[],
  lockDigest: string,
  resolvedInputs: TaskInputDigests,
): readonly GraphTask[] {
  const targetEntries = Object.entries(declaration.targets).sort(
    ([left], [right]) => (left < right ? -1 : left > right ? 1 : 0),
  );
  const tasks: GraphTask[] = [];

  for (const project of projects) {
    for (const [targetName, target] of targetEntries) {
      const task: TaskDeclaration = {
        project: project.name,
        target: targetName,
        projectRoot: project.root,
        ...(target.command === undefined ? {} : { command: target.command }),
        ...(target.executor === undefined ? {} : { executor: target.executor }),
        dependsOn: sorted([
          ...(target.dependsOn ?? []).map(
            (dependency) => `${project.name}:${dependency}`,
          ),
          ...project.dependsOn.map(
            (dependency) => `${dependency}:${targetName}`,
          ),
        ]),
        inputs: sorted(target.inputs ?? []),
        sharedInputs: sorted(target.sharedInputs ?? []),
        outputs: sorted(target.outputs ?? []),
      };
      const key = `${task.project}:${task.target}`;
      if (!Object.hasOwn(resolvedInputs, key)) {
        throw new SdlcError(
          "GRAPH_INPUT_DIGEST_INVALID",
          `missing resolved input digest set for ${key}`,
        );
      }
      const inputDigests = canonicalInputDigests(
        resolvedInputs[key] ?? [],
      );
      for (const input of inputDigests) {
        if (!taskConsumesPath(task, input.path)) {
          throw new SdlcError(
            "GRAPH_INPUT_DIGEST_INVALID",
            `resolved input ${input.path} is not consumed by ${key}`,
          );
        }
      }
      tasks.push({
        ...task,
        key,
        identity: taskIdentity(task, inputDigests, lockDigest),
        inputDigests,
        execution: resolveExecutorContract(target),
      });
    }
  }
  const taskKeys = new Set(tasks.map((task) => task.key));
  for (const key of Object.keys(resolvedInputs)) {
    if (!taskKeys.has(key)) {
      throw new SdlcError(
        "GRAPH_INPUT_DIGEST_INVALID",
        `resolved input digest set references unknown task ${key}`,
      );
    }
  }
  return tasks;
}
