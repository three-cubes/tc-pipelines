import { execFileSync } from "node:child_process";
import {
  chmodSync,
  copyFileSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
  symlinkSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";

import { digest } from "../canonical.js";
import { SdlcError } from "../errors.js";
import { bindGraphLock, buildGraph } from "../graph/index.js";
import { resolveProjectPath, selectorPattern } from "../graph/selector.js";
import { resolveInputInventory, snapshotFiles } from "../inputs/index.js";
import { assertCurrentLock } from "../lock/index.js";
import type {
  InputDigest,
  ReleaseCatalogue,
  SdlcDeclaration,
  SdlcGraph,
  SdlcLock,
  TaskMode,
} from "../schema/types.js";
import type { TreeMutation } from "../evidence/task4.js";

export type PlanningInput = Readonly<{
  root: string;
  declaration: SdlcDeclaration;
  catalogue: ReleaseCatalogue;
  lock: SdlcLock;
}>;

export function plan(input: PlanningInput): SdlcGraph {
  assertCurrentLock(input.lock, input.declaration, input.catalogue);
  const inventory = resolveInputInventory(input.root, input.declaration);
  const bound = bindGraphLock(
    input.declaration,
    input.lock,
    input.catalogue,
    inventory,
  );
  return buildGraph(input.declaration, bound);
}

export function phaseGraph(graph: SdlcGraph, mode: TaskMode): SdlcGraph {
  const keys = new Set(
    graph.tasks.filter((task) => task.mode === mode).map((task) => task.key),
  );
  if (
    mode === "prepare" &&
    graph.tasks
      .filter((task) => task.mode === mode)
      .some((task) => task.dependsOn.some((dependency) => !keys.has(dependency)))
  ) {
    throw new SdlcError(
      "PHASE_DEPENDENCY_INVALID",
      "prepare tasks may not depend on evaluate tasks",
    );
  }
  return {
    ...graph,
    tasks: graph.tasks
      .filter((task) => keys.has(task.key))
      .map((task) => ({
        ...task,
        dependsOn: task.dependsOn.filter((dependency) => keys.has(dependency)),
      })),
  };
}

export function mutations(
  before: readonly InputDigest[],
  after: readonly InputDigest[],
): readonly TreeMutation[] {
  const left = new Map(before.map((entry) => [entry.path, entry]));
  const right = new Map(after.map((entry) => [entry.path, entry]));
  const paths = [...new Set([...left.keys(), ...right.keys()])].sort();
  const result: TreeMutation[] = [];
  for (const path of paths) {
    const previous = left.get(path);
    const next = right.get(path);
    if (previous === undefined && next !== undefined) {
      result.push({ path, kind: "add", after: next });
    } else if (previous !== undefined && next === undefined) {
      result.push({ path, kind: "delete", before: previous });
    } else if (previous !== undefined && next !== undefined) {
      if (previous.symlink !== next.symlink) {
        result.push({ path, kind: "symlink", before: previous, after: next });
      } else if (previous.mode !== next.mode) {
        result.push({ path, kind: "mode", before: previous, after: next });
      } else if (previous.digest !== next.digest) {
        result.push({ path, kind: "content", before: previous, after: next });
      }
    }
  }
  return result;
}

export function mutationAllowed(graph: SdlcGraph, mutation: TreeMutation): boolean {
  return graph.tasks.some((task) =>
    task.outputs.some((output) =>
      selectorPattern(resolveProjectPath(task.projectRoot, output)).test(
        mutation.path,
      ),
    ),
  );
}

export function taskOutputs(
  root: string,
  graph: SdlcGraph,
  taskKey: string,
): readonly InputDigest[] {
  const task = graph.tasks.find((candidate) => candidate.key === taskKey);
  if (task === undefined) {
    return [];
  }
  return snapshotFiles(root).filter((file) =>
    task.outputs.some((output) =>
      selectorPattern(resolveProjectPath(task.projectRoot, output)).test(file.path),
    ),
  );
}

export function materializeTree(root: string): Readonly<{
  root: string;
  dispose: () => void;
}> {
  const container = mkdtempSync(join(tmpdir(), "tc-sdlc-evaluation-"));
  const workspace = resolve(container, "workspace");
  try {
    execFileSync(
      "git",
      ["clone", "--quiet", "--shared", "--no-checkout", "--", root, workspace],
      { stdio: "pipe" },
    );
    for (const file of snapshotFiles(root)) {
      const destination = resolve(workspace, file.path);
      mkdirSync(dirname(destination), { recursive: true });
      if (file.symlink !== null && file.symlink !== undefined) {
        symlinkSync(file.symlink, destination);
      } else {
        copyFileSync(resolve(root, file.path), destination);
        chmodSync(destination, file.mode ?? 0o644);
      }
    }
  } catch (error) {
    rmSync(container, { recursive: true, force: true });
    throw new SdlcError(
      "SOURCE_IDENTITY_INVALID",
      `could not materialize source workspace: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
  return {
    root: workspace,
    dispose: () => rmSync(container, { recursive: true, force: true }),
  };
}

export function sourceIdentity(
  root: string,
  options: Readonly<{
    allowPreparedTree?: boolean;
    treeRoot?: string;
  }> = {},
): Readonly<{
  commit: string;
  treeDigest: string;
}> {
  let commit: string;
  let status: string;
  try {
    commit = execFileSync("git", ["rev-parse", "HEAD"], {
      cwd: root,
      encoding: "utf8",
    }).trim();
    status = execFileSync("git", ["status", "--porcelain=v1", "--untracked-files=all"], {
      cwd: root,
      encoding: "utf8",
    });
  } catch (error) {
    throw new SdlcError(
      "SOURCE_IDENTITY_INVALID",
      `could not resolve source identity: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
  if (status.length > 0 && options.allowPreparedTree !== true) {
    throw new SdlcError("SOURCE_DIRTY", "source tree contains tracked or untracked changes");
  }
  return {
    commit,
    treeDigest: digest(snapshotFiles(options.treeRoot ?? root)),
  };
}
