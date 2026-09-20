import { canonicalJson, digest } from "../canonical.js";
import { SdlcError } from "../errors.js";
import { validateLock } from "../lock/index.js";
import { buildPresetTasks } from "../preset/index.js";
import { validateDeclaration } from "../schema/declaration.js";
import type {
  GraphTask,
  SdlcDeclaration,
  SdlcGraph,
  SdlcLock,
  TaskIdentity,
} from "../schema/types.js";
import { assertRelativePath, normalisePath } from "./path.js";

export { taskIdentity } from "./identity.js";

function assertUniqueIdentities(
  values: readonly string[],
  kind: string,
): void {
  const exact = new Set<string>();
  const folded = new Set<string>();
  for (const value of values) {
    if (exact.has(value)) {
      throw new SdlcError(
        "GRAPH_DUPLICATE_IDENTITY",
        `duplicate ${kind} identity: ${value}`,
      );
    }
    const platformIdentity = value.toLowerCase();
    if (folded.has(platformIdentity)) {
      throw new SdlcError(
        "GRAPH_PLATFORM_AMBIGUITY",
        `${kind} identities differ only by platform case rules: ${value}`,
      );
    }
    exact.add(value);
    folded.add(platformIdentity);
  }
}

function assertUnambiguousPaths(
  values: readonly string[],
  context: string,
): void {
  const identities = new Set<string>();
  for (const value of values) {
    const identity = normalisePath(value).toLowerCase();
    if (identities.has(identity)) {
      throw new SdlcError(
        "GRAPH_PLATFORM_AMBIGUITY",
        `${context} contains platform-equivalent paths: ${value}`,
      );
    }
    identities.add(identity);
  }
}

function validateGraphDeclaration(
  raw: SdlcDeclaration,
  declaration: SdlcDeclaration,
): void {
  assertUniqueIdentities(
    declaration.projects.map((project) => project.name),
    "project",
  );
  const targetNames = Object.keys(declaration.targets);
  assertUniqueIdentities(targetNames, "target");

  for (const project of raw.projects) {
    assertRelativePath(project.root, `project ${project.name} root`);
  }
  for (const [targetName, target] of Object.entries(raw.targets)) {
    for (const path of target.inputs ?? []) {
      assertRelativePath(path, `target ${targetName} input`);
    }
    for (const path of target.sharedInputs ?? []) {
      assertRelativePath(path, `target ${targetName} shared input`);
    }
    for (const path of target.outputs ?? []) {
      assertRelativePath(path, `target ${targetName} output`);
    }
    assertUnambiguousPaths(target.inputs ?? [], `target ${targetName} inputs`);
    assertUnambiguousPaths(
      target.sharedInputs ?? [],
      `target ${targetName} shared inputs`,
    );
    assertUnambiguousPaths(target.outputs ?? [], `target ${targetName} outputs`);
  }

  const roots = new Map<string, string>();
  for (const project of declaration.projects) {
    const platformRoot = project.root.toLowerCase();
    const existing = roots.get(platformRoot);
    if (existing !== undefined) {
      throw new SdlcError(
        "GRAPH_PLATFORM_AMBIGUITY",
        `project roots are ambiguous across platforms: ${existing}, ${project.root}`,
      );
    }
    roots.set(platformRoot, project.root);
  }

  const projectNames = new Set(
    declaration.projects.map((project) => project.name),
  );
  for (const project of declaration.projects) {
    for (const dependency of project.dependsOn ?? []) {
      if (!projectNames.has(dependency)) {
        throw new SdlcError(
          "GRAPH_UNKNOWN_DEPENDENCY",
          `project ${project.name} depends on unknown project ${dependency}`,
        );
      }
    }
  }
  const targetNameSet = new Set(targetNames);
  for (const [targetName, target] of Object.entries(declaration.targets)) {
    for (const dependency of target.dependsOn ?? []) {
      if (!targetNameSet.has(dependency)) {
        throw new SdlcError(
          "GRAPH_UNKNOWN_DEPENDENCY",
          `target ${targetName} depends on unknown target ${dependency}`,
        );
      }
    }
  }
}

function assertAcyclic(tasks: readonly GraphTask[]): void {
  const byKey = new Map(tasks.map((task) => [task.key, task]));
  if (byKey.size !== tasks.length) {
    throw new SdlcError(
      "GRAPH_DUPLICATE_IDENTITY",
      "project and target names produce a duplicate task identity",
    );
  }
  const visiting = new Set<string>();
  const visited = new Set<string>();

  const visit = (key: string): void => {
    if (visiting.has(key)) {
      throw new SdlcError("GRAPH_CYCLE", `task dependency cycle includes ${key}`);
    }
    if (visited.has(key)) {
      return;
    }
    visiting.add(key);
    const task = byKey.get(key);
    if (task === undefined) {
      throw new SdlcError(
        "GRAPH_UNKNOWN_DEPENDENCY",
        `task depends on unknown task ${key}`,
      );
    }
    for (const dependency of task.dependsOn) {
      visit(dependency);
    }
    visiting.delete(key);
    visited.add(key);
  };

  for (const task of tasks) {
    visit(task.key);
  }
}

function sorted(values: readonly string[]): readonly string[] {
  return [...values].sort((left, right) =>
    left < right ? -1 : left > right ? 1 : 0,
  );
}

export function buildGraph(
  declarationValue: SdlcDeclaration,
  lockValue: SdlcLock,
): SdlcGraph {
  const declaration = validateDeclaration(declarationValue);
  const lock = validateLock(lockValue);
  validateGraphDeclaration(declarationValue, declaration);
  const declarationDigest = digest(declaration);
  if (lock.declarationDigest !== declarationDigest) {
    throw new SdlcError(
      "LOCK_STALE",
      "lock does not match the declaration used for graph planning",
    );
  }
  const lockDigest = digest(lock);
  const projects = declaration.projects.map((project) => ({
    name: project.name,
    root: project.root,
    dependsOn: sorted(project.dependsOn ?? []),
  }));
  const tasks = buildPresetTasks(declaration, projects, lockDigest);
  assertAcyclic(tasks);

  return {
    schema: "tc.sdlc/graph/v1",
    declarationDigest,
    lockDigest,
    projects,
    tasks,
  };
}

export function serialiseGraph(graph: SdlcGraph): string {
  return canonicalJson(graph);
}

function resolveProjectPath(root: string, path: string): string {
  return path === "." ? root : normalisePath(`${root}/${path}`);
}

function selectorPattern(selector: string): RegExp {
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
  return new RegExp(`^${pattern}(?:/.*)?$`);
}

function taskConsumes(task: GraphTask, changedPath: string): boolean {
  return (
    task.inputs.some((input) =>
      selectorPattern(resolveProjectPath(task.projectRoot, input)).test(
        changedPath,
      ),
    ) ||
    (task.sharedInputs ?? []).some((input) =>
      selectorPattern(input).test(changedPath),
    ) ||
    (task.inputs.length === 0 &&
      (task.sharedInputs ?? []).length === 0 &&
      (changedPath === task.projectRoot ||
        changedPath.startsWith(`${task.projectRoot}/`)))
  );
}

export function selectAffected(
  graph: SdlcGraph,
  changedPaths: readonly string[],
): readonly TaskIdentity[] {
  const tasksByKey = new Map(graph.tasks.map((task) => [task.key, task]));
  const consumers = new Map<string, string[]>();
  for (const task of graph.tasks) {
    for (const dependency of task.dependsOn) {
      const entries = consumers.get(dependency) ?? [];
      entries.push(task.key);
      consumers.set(dependency, entries);
    }
  }

  const selected = new Set<string>();
  const pendingPaths: string[] = [];
  const seenPaths = new Set<string>();
  const enqueuePath = (path: string): void => {
    if (!seenPaths.has(path)) {
      seenPaths.add(path);
      pendingPaths.push(path);
    }
  };
  const selectTask = (key: string): void => {
    if (selected.has(key)) {
      return;
    }
    const task = tasksByKey.get(key);
    if (task === undefined) {
      throw new SdlcError(
        "GRAPH_UNKNOWN_DEPENDENCY",
        `selection references unknown task ${key}`,
      );
    }
    selected.add(key);
    for (const output of task.outputs) {
      enqueuePath(resolveProjectPath(task.projectRoot, output));
    }
    for (const consumer of consumers.get(key) ?? []) {
      selectTask(consumer);
    }
  };

  for (const changedPath of changedPaths) {
    assertRelativePath(changedPath, "changed path");
    enqueuePath(normalisePath(changedPath));
  }

  while (pendingPaths.length > 0) {
    const changedPath = pendingPaths.shift();
    if (changedPath === undefined) {
      break;
    }
    if (changedPath === "sdlc.yaml" || changedPath === "tc-sdlc.lock") {
      for (const task of graph.tasks) {
        selectTask(task.key);
      }
      continue;
    }
    for (const task of graph.tasks) {
      if (taskConsumes(task, changedPath)) {
        selectTask(task.key);
      }
    }
  }

  return graph.tasks
    .filter((task) => selected.has(task.key))
    .map((task) => task.identity);
}
