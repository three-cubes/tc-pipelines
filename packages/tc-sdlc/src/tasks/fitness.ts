import { readFileSync } from "node:fs";

import { bytesDigest, digest } from "../canonical.js";
import { SdlcError } from "../errors.js";
import {
  finaliseFitnessReceipt,
  fitnessFailureReceipt,
  parseFitnessReceipt,
  unresolvedFitnessReceipt,
  writeFitnessReceipt,
  type FitnessReceipt,
} from "../executors/fitness.js";
import { runGraph, type RunOptions } from "../runtime/index.js";
import type { GraphTask, ReleaseCatalogue, SdlcDeclaration, SdlcLock } from "../schema/types.js";
import { materializeTree, phaseGraph, plan } from "./common.js";

export type FitnessOptions = Readonly<{
  root: string;
  declaration: SdlcDeclaration;
  catalogue: ReleaseCatalogue;
  lock: SdlcLock;
  receiptPath: string;
  runOptions: Omit<RunOptions, "cwd" | "receiptPath">;
}>;

function bindReceipt(
  receipt: FitnessReceipt,
  options: FitnessOptions,
  runReceiptDigest: string | null,
): FitnessReceipt {
  return {
    ...receipt,
    declarationDigest: digest(options.declaration),
    catalogueDigest: digest(options.catalogue),
    lockDigest: digest(options.lock),
    runReceiptDigest,
  };
}

function terminalFailure(task: GraphTask, options: FitnessOptions, workspace: string, reason: string): FitnessReceipt {
  return bindReceipt(
    fitnessFailureReceipt(task, options.runOptions.executionContext, workspace, reason),
    options,
    null,
  );
}

export async function fitness(options: FitnessOptions): Promise<FitnessReceipt> {
  let workspace: ReturnType<typeof materializeTree> | undefined;
  let task: GraphTask | undefined;
  let publicReceiptWritten = false;
  try {
    workspace = materializeTree(options.root);
    const graph = phaseGraph(plan({ ...options, root: workspace.root }), "evaluate");
    const tasks = graph.tasks.filter((candidate) => candidate.execution.kind === "fitness");
    if (tasks.length !== 1) {
      throw new SdlcError("FITNESS_TARGET_INVALID", "the declaration must define exactly one repository-scoped tc-sdlc:fitness target");
    }
    const fitnessTask = tasks[0]!;
    task = fitnessTask;
    const runReceiptPath = `${options.receiptPath}.run`;
    const run = await runGraph(graph, [fitnessTask.identity], {
      ...options.runOptions,
      cwd: workspace.root,
      receiptPath: runReceiptPath,
    });
    const executed = run.tasks.find((candidate) => candidate.key === fitnessTask.key);
    const evidence = executed?.evidence.find((item) => item.path === "fitness.json");
    if (evidence === undefined) {
      const fallback = terminalFailure(fitnessTask, options, workspace.root, "fitness_evidence_missing");
      writeFitnessReceipt(options.receiptPath, fallback);
      publicReceiptWritten = true;
      throw new SdlcError("FITNESS_EVIDENCE_INVALID", "fitness executor did not retain fitness.json evidence");
    }
    const receipt = bindReceipt(
      parseFitnessReceipt(evidence.content),
      options,
      bytesDigest(readFileSync(runReceiptPath, "utf8")),
    );
    writeFitnessReceipt(options.receiptPath, receipt);
    publicReceiptWritten = true;
    if (run.status !== "succeeded" || receipt.gateOutcome !== "passed") {
      throw new SdlcError("FITNESS_FAILED", `fitness gate ${receipt.gateOutcome}`);
    }
    return receipt;
  } catch (error) {
    if (!publicReceiptWritten) {
      try {
        writeFitnessReceipt(
          options.receiptPath,
          task === undefined
            ? bindReceipt(
              unresolvedFitnessReceipt(
                options.runOptions.executionContext,
                workspace?.root ?? options.root,
                options.declaration.fitness.config,
                error instanceof SdlcError ? error.code.toLowerCase() : "fitness_runtime_failed",
              ),
              options,
              null,
            )
            : terminalFailure(task, options, workspace?.root ?? options.root, error instanceof SdlcError ? error.code.toLowerCase() : "fitness_runtime_failed"),
        );
      } catch {
        // Preserve the original terminal failure when evidence storage is unavailable.
      }
    }
    throw error;
  } finally {
    workspace?.dispose();
  }
}
