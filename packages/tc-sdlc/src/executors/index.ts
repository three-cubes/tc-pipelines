import { SdlcError } from "../errors.js";
import type { TargetDeclaration } from "../schema/types.js";

export type ExecutorContract =
  | Readonly<{ kind: "command"; command: string }>
  | Readonly<{ kind: "executor"; executor: string }>;

export function resolveExecutorContract(
  target: TargetDeclaration,
): ExecutorContract {
  if (target.command !== undefined && target.executor === undefined) {
    return { kind: "command", command: target.command };
  }
  if (target.executor !== undefined && target.command === undefined) {
    return { kind: "executor", executor: target.executor };
  }
  throw new SdlcError(
    "GRAPH_EXECUTOR_INVALID",
    "a target must declare exactly one command or executor",
  );
}
