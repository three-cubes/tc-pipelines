import { createHash } from "node:crypto";
import { existsSync, lstatSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import type { BootstrapExecutionContext } from "../bootstrap/index.js";
import { digest } from "../canonical.js";
import { writeCanonicalEvidence } from "../evidence/index.js";
import { assertSchema } from "../schema/validation.js";
import type { GraphTask } from "../schema/types.js";
import type { ReleaseCatalogue, SdlcDeclaration, SdlcLock } from "../schema/types.js";

export type FitnessReceipt = Readonly<{
  schema: "tc.sdlc/fitness-receipt/v1";
  status: "succeeded" | "failed" | "stalled" | "cancelled";
  reason: string | null;
  declarationDigest: string | null;
  catalogueDigest: string | null;
  lockDigest: string | null;
  bootstrapContextDigest: string | null;
  task: Readonly<{ key: string | null; identity: string | null }>;
  engine: Readonly<{
    distribution: "three-cubes-fitness" | null;
    expectedVersion: string | null;
    observedVersion: string | null;
    executableDigest: string | null;
    environmentDigest: string | null;
  }>;
  config: Readonly<{ path: string | null; digest: string | null }>;
  profile: Readonly<{ name: string | null; tier: string | null }>;
  gateOutcome: "passed" | "failed" | "versionMismatch" | "invalidConfig" | "notRun";
  exitCode: number | null;
  runReceiptDigest: string | null;
}>;

export type FitnessExecution = Readonly<{
  executable: string | null;
  args: readonly string[];
  receipt: FitnessReceipt;
  failureReason?: string;
}>;

function sha256File(path: string): string | null {
  try {
    return `sha256:${createHash("sha256").update(readFileSync(path)).digest("hex")}`;
  } catch {
    return null;
  }
}

function receiptBase(task: GraphTask, context: BootstrapExecutionContext, cwd: string): FitnessReceipt {
  if (task.execution.kind !== "fitness") throw new TypeError("fitness executor required");
  const configPath = join(cwd, task.projectRoot, task.execution.config);
  const configDigest = existsSync(configPath) && lstatSync(configPath).isFile() ? sha256File(configPath) : null;
  return {
    schema: "tc.sdlc/fitness-receipt/v1",
    status: "failed",
    reason: null,
    declarationDigest: null,
    catalogueDigest: null,
    lockDigest: context.binding.lockDigest,
    bootstrapContextDigest: digest(context.binding),
    task: { key: task.key, identity: task.identity },
    engine: {
      distribution: "three-cubes-fitness",
      expectedVersion: context.binding.fitness.version,
      observedVersion: null,
      executableDigest: null,
      environmentDigest: context.environment.VIRTUAL_ENV === undefined ? null : digest(context.environment),
    },
    config: { path: task.execution.config, digest: configDigest },
    profile: { name: task.execution.profile, tier: task.execution.tier },
    gateOutcome: configDigest === null ? "invalidConfig" : "notRun",
    exitCode: null,
    runReceiptDigest: null,
  };
}

export function finaliseFitnessReceipt(
  receipt: FitnessReceipt,
  status: FitnessReceipt["status"],
  reason: string | null,
  exitCode: number | null,
): FitnessReceipt {
  return {
    ...receipt,
    status,
    reason,
    gateOutcome: status === "succeeded" ? "passed" : receipt.gateOutcome === "notRun" ? "failed" : receipt.gateOutcome,
    exitCode,
  };
}

export function writeFitnessReceipt(path: string, receipt: FitnessReceipt): void {
  assertSchema<FitnessReceipt>("fitness-receipt-v1.schema.json", receipt, "fitness receipt");
  writeCanonicalEvidence(path, receipt);
}

export function parseFitnessReceipt(value: string): FitnessReceipt {
  const receipt: unknown = JSON.parse(value);
  assertSchema<FitnessReceipt>("fitness-receipt-v1.schema.json", receipt, "fitness receipt");
  return receipt;
}

function failed(receipt: FitnessReceipt, reason: string): FitnessExecution {
  return { executable: null, args: [], failureReason: reason, receipt: finaliseFitnessReceipt(receipt, "failed", reason, null) };
}

export function fitnessFailureReceipt(task: GraphTask, context: BootstrapExecutionContext, cwd: string, reason: string): FitnessReceipt {
  return finaliseFitnessReceipt(receiptBase(task, context, cwd), "failed", reason, null);
}

export function unresolvedFitnessReceipt(
  context: BootstrapExecutionContext,
  cwd: string,
  config: string,
  reason: string,
): FitnessReceipt {
  const configPath = join(cwd, config);
  const configDigest = existsSync(configPath) && lstatSync(configPath).isFile() ? sha256File(configPath) : null;
  return {
    schema: "tc.sdlc/fitness-receipt/v1",
    status: "failed",
    reason,
    declarationDigest: null,
    catalogueDigest: null,
    lockDigest: context.binding.lockDigest,
    bootstrapContextDigest: digest(context.binding),
    task: { key: null, identity: null },
    engine: {
      distribution: "three-cubes-fitness",
      expectedVersion: context.binding.fitness.version,
      observedVersion: null,
      executableDigest: null,
      environmentDigest: context.environment.VIRTUAL_ENV === undefined ? null : digest(context.environment),
    },
    config: { path: config, digest: configDigest },
    profile: { name: null, tier: null },
    gateOutcome: configDigest === null ? "invalidConfig" : "notRun",
    exitCode: null,
    runReceiptDigest: null,
  };
}

export function unavailableFitnessReceipt(
  declaration: SdlcDeclaration,
  catalogue: ReleaseCatalogue,
  lock: SdlcLock,
  root: string,
  reason: string,
): FitnessReceipt {
  const configPath = join(root, declaration.fitness.config);
  const configDigest = existsSync(configPath) && lstatSync(configPath).isFile() ? sha256File(configPath) : null;
  return {
    schema: "tc.sdlc/fitness-receipt/v1",
    status: "failed",
    reason,
    declarationDigest: digest(declaration),
    catalogueDigest: digest(catalogue),
    lockDigest: digest(lock),
    bootstrapContextDigest: null,
    task: { key: null, identity: null },
    engine: {
      distribution: "three-cubes-fitness",
      expectedVersion: lock.fitness.version,
      observedVersion: null,
      executableDigest: null,
      environmentDigest: null,
    },
    config: { path: declaration.fitness.config, digest: configDigest },
    profile: { name: null, tier: null },
    gateOutcome: configDigest === null ? "invalidConfig" : "notRun",
    exitCode: null,
    runReceiptDigest: null,
  };
}

/** Receipt for failures before declaration, catalogue, or lock parsing establishes bindings. */
export function preflightFitnessReceipt(reason: string): FitnessReceipt {
  return {
    schema: "tc.sdlc/fitness-receipt/v1",
    status: "failed",
    reason,
    declarationDigest: null,
    catalogueDigest: null,
    lockDigest: null,
    bootstrapContextDigest: null,
    task: { key: null, identity: null },
    engine: {
      distribution: null,
      expectedVersion: null,
      observedVersion: null,
      executableDigest: null,
      environmentDigest: null,
    },
    config: { path: null, digest: null },
    profile: { name: null, tier: null },
    gateOutcome: "notRun",
    exitCode: null,
    runReceiptDigest: null,
  };
}

export function prepareFitnessExecution(task: GraphTask, context: BootstrapExecutionContext, cwd: string): FitnessExecution {
  if (task.execution.kind !== "fitness") throw new TypeError("fitness executor required");
  const execution = task.execution;
  const base = receiptBase(task, context, cwd);
  if (base.config.digest === null) return failed(base, "fitness_config_invalid");
  const virtualEnvironment = context.environment.VIRTUAL_ENV;
  if (virtualEnvironment === undefined) return failed(base, "fitness_environment_missing");
  const sitePackages = join(virtualEnvironment, "lib", "python3.13", "site-packages");
  let metadataDirectories: string[];
  try {
    metadataDirectories = readdirSync(sitePackages).filter((name) => /^three_cubes_fitness-[^/]+\.dist-info$/.test(name));
  } catch {
    return failed(base, "fitness_metadata_missing");
  }
  if (metadataDirectories.length !== 1) return failed(base, metadataDirectories.length === 0 ? "fitness_metadata_missing" : "fitness_metadata_ambiguous");
  const metadata = join(sitePackages, metadataDirectories[0]!, "METADATA");
  let observedVersion: string | null;
  try {
    observedVersion = readFileSync(metadata, "utf8").match(/^Version:\s*(.+)$/m)?.[1]?.trim() ?? null;
  } catch {
    return failed(base, "fitness_metadata_invalid");
  }
  if (observedVersion === null || !/^[0-9]+\.[0-9]+\.[0-9]+$/.test(observedVersion)) return failed(base, "fitness_metadata_invalid");
  const executable = join(virtualEnvironment, "bin", "tc-fitness");
  const receipt: FitnessReceipt = { ...base, engine: { ...base.engine, observedVersion } };
  if (!existsSync(executable) || !lstatSync(executable).isFile() || lstatSync(executable).isSymbolicLink()) return failed(receipt, "fitness_executable_missing");
  const executableDigest = sha256File(executable);
  if (executableDigest === null) return failed(receipt, "fitness_executable_missing");
  const executableReceipt: FitnessReceipt = { ...receipt, engine: { ...receipt.engine, executableDigest } };
  if (observedVersion !== executableReceipt.engine.expectedVersion) {
    return { executable: null, args: [], failureReason: "fitness_version_mismatch", receipt: { ...finaliseFitnessReceipt(executableReceipt, "failed", "fitness_version_mismatch", null), gateOutcome: "versionMismatch" } };
  }
  return { executable, args: ["run", "--repo-root", join(cwd, task.projectRoot), "--tier", execution.tier], receipt: executableReceipt };
}
