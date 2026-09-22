import { SdlcError } from "../errors.js";
import type { SdlcFitness, TargetDeclaration } from "../schema/types.js";

export type ExecutorContract =
  | Readonly<{ kind: "command"; command: string }>
  | Readonly<{
      kind: "fitness";
      profile: string;
      tier: string;
      config: SdlcFitness["config"];
    }>
  | Readonly<{ kind: "executor"; executor: string }>;

export function resolveExecutorContract(
  target: TargetDeclaration,
  fitness?: SdlcFitness,
): ExecutorContract {
  if (target.command !== undefined && target.executor === undefined) {
    return { kind: "command", command: target.command };
  }
  if (target.executor !== undefined && target.command === undefined) {
    if (target.executor === "tc-sdlc:fitness") {
      const tier = target.profile === undefined ? undefined : fitness?.profiles[target.profile];
      if (
        target.scope !== "repository" ||
        target.profile === undefined ||
        tier === undefined ||
        !target.evidence?.some((item) => item.path === "fitness.json" && item.mediaType === "application/json")
      ) {
        throw new SdlcError(
          "GRAPH_EXECUTOR_INVALID",
          "tc-sdlc:fitness must be repository-scoped with a declared profile and fitness.json evidence",
        );
      }
      return { kind: "fitness", profile: target.profile, tier, config: fitness!.config };
    }
    return { kind: "executor", executor: target.executor };
  }
  throw new SdlcError(
    "GRAPH_EXECUTOR_INVALID",
    "a target must declare exactly one command or executor",
  );
}
