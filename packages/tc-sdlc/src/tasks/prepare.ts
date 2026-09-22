import { canonicalJson, digest } from "../canonical.js";
import {
  writeCanonicalEvidence,
  type RunReceipt,
} from "../evidence/index.js";
import type { PreparationReceipt } from "../evidence/task4.js";
import { snapshotFiles } from "../inputs/index.js";
import { recoverInterruptedTemporaryState } from "../maintenance/index.js";
import { runGraph, type RunOptions } from "../runtime/index.js";
import type { ReleaseCatalogue, SdlcDeclaration, SdlcLock } from "../schema/types.js";
import { mutationAllowed, mutations, phaseGraph, plan } from "./common.js";

export type PreparationOptions = Readonly<{
  root: string;
  declaration: SdlcDeclaration;
  catalogue: ReleaseCatalogue;
  lock: SdlcLock;
  receiptPath: string;
  maxMutations?: number;
  runOptions: Omit<RunOptions, "cwd" | "receiptPath">;
}>;

export function serialisePreparationReceipt(receipt: PreparationReceipt): string {
  return canonicalJson(receipt);
}

export async function prepare(options: PreparationOptions): Promise<PreparationReceipt> {
  const maximumMutations = options.maxMutations ?? 1_000;
  if (!Number.isSafeInteger(maximumMutations) || maximumMutations < 1) {
    throw new TypeError("maxMutations must be a positive safe integer");
  }
  const recovery = await recoverInterruptedTemporaryState();
  const base = {
    schema: "tc.sdlc/preparation-receipt/v1" as const,
    declarationDigest: digest(options.declaration),
    catalogueDigest: digest(options.catalogue),
    lockDigest: digest(options.lock),
    bootstrapContext: options.runOptions.executionContext.binding,
    recovery,
  };
  let firstScheduler: RunReceipt | undefined;
  let secondScheduler: RunReceipt | undefined;
  let firstMutations = [] as ReturnType<typeof mutations>;
  let secondMutations = [] as ReturnType<typeof mutations>;
  let reason: string | null = null;
  let finalTreeDigest = digest(snapshotFiles(options.root));
  try {
    const graph = phaseGraph(plan(options), "prepare");
    const selection = graph.tasks.map((task) => task.identity);
    const before = snapshotFiles(options.root);
    firstScheduler = await runGraph(graph, selection, {
      ...options.runOptions,
      cwd: options.root,
      receiptPath: `${options.receiptPath}.run-1`,
    });
    const afterFirst = snapshotFiles(options.root);
    finalTreeDigest = digest(afterFirst);
    firstMutations = mutations(before, afterFirst);
    if (firstScheduler.status !== "succeeded") {
      reason = "preparation_execution_failed";
    } else if (firstMutations.some((mutation) => !mutationAllowed(graph, mutation))) {
      reason = "undeclared_mutation";
    } else {
      secondScheduler = await runGraph(graph, selection, {
        ...options.runOptions,
        cwd: options.root,
        receiptPath: `${options.receiptPath}.run-2`,
      });
      const afterSecond = snapshotFiles(options.root);
      finalTreeDigest = digest(afterSecond);
      secondMutations = mutations(afterFirst, afterSecond);
      if (secondScheduler.status !== "succeeded") {
        reason = "preparation_execution_failed";
      } else if (secondMutations.length > 0) {
        reason = "not_fixed_point";
      }
    }
  } catch (error) {
    reason = error instanceof Error ? error.message : String(error);
  }
  const receipt: PreparationReceipt = {
    ...base,
    status: reason === null ? "succeeded" : "failed",
    reason,
    finalTreeDigest,
    firstPass: {
      mutations: firstMutations.slice(0, maximumMutations),
      mutationCount: firstMutations.length,
      mutationsTruncated: firstMutations.length > maximumMutations,
      ...(firstScheduler === undefined ? {} : { scheduler: firstScheduler }),
    },
    secondPass: {
      mutations: secondMutations.slice(0, maximumMutations),
      mutationCount: secondMutations.length,
      mutationsTruncated: secondMutations.length > maximumMutations,
      ...(secondScheduler === undefined ? {} : { scheduler: secondScheduler }),
    },
  };
  writeCanonicalEvidence(options.receiptPath, receipt);
  return receipt;
}
