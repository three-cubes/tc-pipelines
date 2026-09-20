import { digest } from "../canonical.js";
import { resolveExecutorContract } from "../executors/index.js";
import { taskIdentity } from "../graph/identity.js";
import type {
  GraphProject,
  GraphTask,
  SdlcDeclaration,
  TaskDeclaration,
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
      const inputDigests = task.inputs.map((path) => ({
        path,
        digest: digest({ selector: path }),
      }));
      tasks.push({
        ...task,
        key: `${project.name}:${targetName}`,
        identity: taskIdentity(task, inputDigests, lockDigest),
        execution: resolveExecutorContract(target),
      });
    }
  }
  return tasks;
}
