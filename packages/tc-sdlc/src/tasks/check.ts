import { canonicalJson, digest } from "../canonical.js";
import { SdlcError } from "../errors.js";
import { writeCanonicalEvidence } from "../evidence/index.js";
import type {
  EvaluationReceipt,
  PreparationReceipt,
  TreeMutation,
} from "../evidence/task4.js";
import {
  parsePreparationReceipt,
  validatePreparationReceipt,
} from "../evidence/task4.js";
import { selectAffected } from "../graph/index.js";
import { snapshotFiles } from "../inputs/index.js";
import { recoverInterruptedTemporaryState } from "../maintenance/index.js";
import { runGraph, type RunOptions } from "../runtime/index.js";
import type { ReleaseCatalogue, SdlcDeclaration, SdlcLock } from "../schema/types.js";
import {
  mutations,
  materializeTree,
  phaseGraph,
  plan,
  sourceIdentity,
  taskOutputs,
} from "./common.js";

export type EvaluationOptions = Readonly<{
  root: string;
  declaration: SdlcDeclaration;
  catalogue: ReleaseCatalogue;
  lock: SdlcLock;
  receiptPath: string;
  environmentClass: string;
  producer: string;
  preparationReceipt?: PreparationReceipt | string;
  maxMutations?: number;
  changedPaths?: readonly string[];
  runOptions: Omit<RunOptions, "cwd" | "receiptPath">;
}>;

export function serialiseEvaluationReceipt(receipt: EvaluationReceipt): string {
  return canonicalJson(receipt);
}

async function evaluate(
  options: EvaluationOptions,
  all: boolean,
): Promise<EvaluationReceipt> {
  const maximumMutations = options.maxMutations ?? 1_000;
  if (!Number.isSafeInteger(maximumMutations) || maximumMutations < 1) {
    throw new TypeError("maxMutations must be a positive safe integer");
  }
  const recovery = await recoverInterruptedTemporaryState();
  let source = { commit: "unresolved", treeDigest: digest(snapshotFiles(options.root)) };
  let scheduler: EvaluationReceipt["scheduler"];
  let taskEvidence: EvaluationReceipt["tasks"] = [];
  let treeMutations: readonly TreeMutation[] = [];
  let reason: string | null = null;
  const workspace = materializeTree(options.root);
  try {
    try {
      options.runOptions.executionContext.assertIdentity();
      const full = plan({ ...options, root: workspace.root });
      const graph = phaseGraph(full, "evaluate");
      const selected = all
        ? new Set(graph.tasks.map((task) => task.key))
        : new Set(
            full.tasks
              .filter((task) =>
                selectAffected(full, options.changedPaths ?? []).includes(task.identity),
              )
              .map((task) => task.key),
          );
      const selection = graph.tasks
        .filter((task) => selected.has(task.key))
        .map((task) => task.identity);
      const fullByKey = new Map(full.tasks.map((task) => [task.key, task]));
      const requiresPreparation = (key: string, seen = new Set<string>()): boolean => {
        if (seen.has(key)) return false;
        seen.add(key);
        const task = fullByKey.get(key);
        return (
          task !== undefined &&
          task.dependsOn.some((dependency) => {
            const required = fullByKey.get(dependency);
            return required?.mode === "prepare" || requiresPreparation(dependency, seen);
          })
        );
      };
      const preparationRequired = graph.tasks.some(
        (task) => selected.has(task.key) && requiresPreparation(task.key),
      );
      source = sourceIdentity(options.root, {
        allowPreparedTree: preparationRequired,
        treeRoot: workspace.root,
      });
      if (preparationRequired) {
        const suppliedPreparation = options.preparationReceipt;
        const preparation = suppliedPreparation === undefined
          ? undefined
          : typeof suppliedPreparation === "string"
            ? parsePreparationReceipt(suppliedPreparation)
            : validatePreparationReceipt(suppliedPreparation);
        if (
          preparation === undefined ||
          preparation.status !== "succeeded" ||
          preparation.secondPass.mutationCount !== 0 ||
          preparation.finalTreeDigest !== source.treeDigest ||
          preparation.declarationDigest !== digest(options.declaration) ||
          preparation.catalogueDigest !== digest(options.catalogue) ||
          preparation.lockDigest !== digest(options.lock) ||
          canonicalJson(preparation.bootstrapContext) !==
            canonicalJson(options.runOptions.executionContext.binding)
        ) {
          throw new SdlcError(
            "PREPARATION_EVIDENCE_INVALID",
            "evaluation requires a succeeded fixed-point preparation receipt for the exact source and planning identities",
          );
        }
      }
      const before = snapshotFiles(workspace.root);
      scheduler = await runGraph(graph, selection, {
        ...options.runOptions,
        cwd: workspace.root,
        receiptPath: `${options.receiptPath}.run`,
      });
      const after = snapshotFiles(workspace.root);
      treeMutations = mutations(before, after);
      const inventory = new Map(
        graph.tasks.map((task) => [task.key, task.inputDigests] as const),
      );
      taskEvidence = graph.tasks
        .filter((task) => selected.has(task.key))
        .map((task) => ({
          key: task.key,
          identity: task.identity,
          mode: "evaluate" as const,
          trustBoundary: task.trustBoundary,
          inputs: inventory.get(task.key) ?? [],
          outputs: taskOutputs(workspace.root, graph, task.key),
        }));
      if (scheduler.status !== "succeeded") {
        reason = `scheduler_${scheduler.status}`;
      } else if (treeMutations.length > 0) {
        reason = "evaluation_mutation";
      } else if (digest(snapshotFiles(options.root)) !== source.treeDigest) {
        reason = "source_tree_drift";
      }
    } catch (error) {
      reason =
        error instanceof SdlcError && error.code === "SOURCE_DIRTY"
          ? "dirty_source_tree"
          : error instanceof SdlcError && error.code === "PREPARATION_EVIDENCE_INVALID"
            ? "preparation_evidence_invalid"
          : error instanceof Error
            ? error.message
            : String(error);
    }
    const receipt: EvaluationReceipt = {
      schema: "tc.sdlc/evaluation-receipt/v1",
      status: reason === null ? "succeeded" : "failed",
      reason,
      source,
      declarationDigest: digest(options.declaration),
      catalogueDigest: digest(options.catalogue),
      lockDigest: digest(options.lock),
      bootstrapContext: options.runOptions.executionContext.binding,
      environmentClass: options.environmentClass,
      producer: options.producer,
      recovery,
      tasks: taskEvidence,
      ...(scheduler === undefined ? {} : { scheduler }),
      mutations: treeMutations.slice(0, maximumMutations),
      mutationCount: treeMutations.length,
      mutationsTruncated: treeMutations.length > maximumMutations,
    };
    writeCanonicalEvidence(options.receiptPath, receipt);
    return receipt;
  } finally {
    workspace.dispose();
  }
}

export function check(options: EvaluationOptions): Promise<EvaluationReceipt> {
  return evaluate(options, false);
}

export function checkAll(options: EvaluationOptions): Promise<EvaluationReceipt> {
  return evaluate(options, true);
}
