import type { KeyObject } from "node:crypto";

import type { RunReceipt } from "./index.js";
import type { AutomaticRecoveryReceipt } from "../maintenance/index.js";
import type { InputDigest, TrustBoundary } from "../schema/types.js";
import type { BootstrapContextBinding } from "../bootstrap/index.js";
import { SdlcError } from "../errors.js";

export type TreeMutation = Readonly<{
  path: string;
  kind: "add" | "delete" | "content" | "mode" | "symlink";
  before?: InputDigest;
  after?: InputDigest;
}>;

export type PreparationReceipt = Readonly<{
  schema: "tc.sdlc/preparation-receipt/v1";
  status: "succeeded" | "failed";
  reason: string | null;
  declarationDigest: string;
  catalogueDigest: string;
  lockDigest: string;
  bootstrapContext: BootstrapContextBinding;
  recovery: AutomaticRecoveryReceipt;
  finalTreeDigest: string;
  firstPass: Readonly<{
    mutations: readonly TreeMutation[];
    mutationCount: number;
    mutationsTruncated: boolean;
    scheduler?: RunReceipt;
  }>;
  secondPass: Readonly<{
    mutations: readonly TreeMutation[];
    mutationCount: number;
    mutationsTruncated: boolean;
    scheduler?: RunReceipt;
  }>;
}>;

export type EvaluationTaskEvidence = Readonly<{
  key: string;
  identity: string;
  mode: "evaluate";
  trustBoundary: TrustBoundary;
  inputs: readonly InputDigest[];
  outputs: readonly InputDigest[];
}>;

export type EvaluationReceipt = Readonly<{
  schema: "tc.sdlc/evaluation-receipt/v1";
  status: "succeeded" | "failed";
  reason: string | null;
  source: Readonly<{ commit: string; treeDigest: string }>;
  declarationDigest: string;
  catalogueDigest: string;
  lockDigest: string;
  bootstrapContext: BootstrapContextBinding;
  environmentClass: string;
  producer: string;
  recovery: AutomaticRecoveryReceipt;
  tasks: readonly EvaluationTaskEvidence[];
  scheduler?: RunReceipt;
  mutations: readonly TreeMutation[];
  mutationCount: number;
  mutationsTruncated: boolean;
}>;

export type EvaluationCandidate = Omit<
  EvaluationReceipt,
  | "scheduler"
  | "mutations"
  | "mutationCount"
  | "mutationsTruncated"
  | "status"
  | "reason"
  | "recovery"
>;

export type SignedEvaluationReceipt = Readonly<{
  receipt: EvaluationReceipt;
  signature: Readonly<{
    algorithm: "Ed25519";
    producer: string;
    keyId: string;
    signedAt: string;
    expiresAt: string;
    value: string;
  }>;
}>;

export type EvaluationSigner = Readonly<{
  producer: string;
  keyId: string;
  privateKey: KeyObject | string;
  signedAt: string;
  expiresAt: string;
}>;

export type EvidencePolicy = Readonly<{
  now: string;
  producers: Readonly<
    Record<string, Readonly<{ keyId: string; publicKey: KeyObject | string }>>
  >;
}>;

export type ReceiptBindings = Readonly<{
  declarationDigest: string;
  catalogueDigest: string;
  lockDigest: string;
}>;

const terminalStatuses = new Set(["succeeded", "failed", "stalled", "cancelled"]);

function invalid(kind: "PREPARATION" | "EVALUATION", message: string): never {
  throw new SdlcError(`${kind}_EVIDENCE_INVALID`, message);
}

function record(value: unknown, kind: "PREPARATION" | "EVALUATION", label: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) invalid(kind, `${label} must be an object`);
  return value as Record<string, unknown>;
}

function exact(value: Record<string, unknown>, required: readonly string[], optional: readonly string[], kind: "PREPARATION" | "EVALUATION", label: string): void {
  if (required.some((key) => value[key] === undefined) || Object.keys(value).some((key) => !required.includes(key) && !optional.includes(key))) {
    invalid(kind, `${label} has an invalid producer-specific shape`);
  }
}

function stringValue(value: unknown): value is string { return typeof value === "string" && value.length > 0; }
function digestValue(value: unknown): value is string { return typeof value === "string" && /^sha256:[a-f0-9]{64}$/.test(value); }

function stringArray(value: unknown, kind: "PREPARATION" | "EVALUATION", label: string): asserts value is string[] {
  if (!Array.isArray(value) || value.some((entry) => !stringValue(entry))) invalid(kind, `${label} must be a string inventory`);
}

function digestArray(value: unknown, kind: "PREPARATION" | "EVALUATION", label: string): asserts value is string[] {
  if (!Array.isArray(value) || value.some((entry) => !digestValue(entry))) invalid(kind, `${label} must be a digest inventory`);
}

function inputDigest(value: unknown, kind: "PREPARATION" | "EVALUATION", label: string): void {
  const input = record(value, kind, label);
  exact(input, ["path", "digest", "mode", "symlink"], [], kind, label);
  if (!stringValue(input.path) || !digestValue(input.digest) || !Number.isSafeInteger(input.mode) || !(input.symlink === null || typeof input.symlink === "string")) invalid(kind, `${label} is invalid`);
}

function recovery(value: unknown, kind: "PREPARATION" | "EVALUATION"): void {
  const receipt = record(value, kind, "recovery receipt");
  exact(receipt, ["schema", "status", "boundary", "retentionHours", "candidateCount", "removedCount", "reclaimedBytes", "entriesTruncated", "cleanupFailures", "peakCleanupWorkers"], [], kind, "recovery receipt");
  if (receipt.schema !== "tc.sdlc/automatic-recovery/v1" || !["succeeded", "partial"].includes(receipt.status as string) || receipt.boundary !== "os-temporary-root" || receipt.retentionHours !== 48 || [receipt.candidateCount, receipt.removedCount, receipt.reclaimedBytes, receipt.cleanupFailures, receipt.peakCleanupWorkers].some((entry) => !Number.isSafeInteger(entry) || (entry as number) < 0) || typeof receipt.entriesTruncated !== "boolean") invalid(kind, "recovery receipt is invalid");
}

function bootstrapContext(value: unknown, kind: "PREPARATION" | "EVALUATION", lockDigest?: string): void {
  const context = record(value, kind, "bootstrap context");
  exact(context, ["schema", "release", "platform", "architecture", "lockDigest", "stateKey", "stateGenerationIdentity", "bootstrapReceiptDigest", "stateDigest", "dependencyDigest", "fitness", "adapters"], [], kind, "bootstrap context");
  if (context.schema !== "tc.sdlc/execution-context/v1" || (lockDigest !== undefined && context.lockDigest !== lockDigest) || !stringValue(context.release) || !["darwin", "linux"].includes(context.platform as string) || !stringValue(context.architecture) || !digestValue(context.lockDigest) || !stringValue(context.stateKey) || !digestValue(context.stateGenerationIdentity) || !digestValue(context.bootstrapReceiptDigest) || !digestValue(context.stateDigest) || !digestValue(context.dependencyDigest) || !Array.isArray(context.adapters)) invalid(kind, "bootstrap context is invalid");
  const fitness = record(context.fitness, kind, "bootstrap fitness binding");
  exact(fitness, ["package", "version"], [], kind, "bootstrap fitness binding");
  if (!stringValue(fitness.package) || !stringValue(fitness.version)) invalid(kind, "bootstrap fitness binding is invalid");
  for (const candidate of context.adapters) {
    const adapter = record(candidate, kind, "bootstrap adapter binding");
    exact(adapter, ["name", "version", "adapterDigest"], [], kind, "bootstrap adapter binding");
    if (!["node", "pnpm", "python", "uv"].includes(adapter.name as string) || !stringValue(adapter.version) || !digestValue(adapter.adapterDigest)) invalid(kind, "bootstrap adapter binding is invalid");
  }
}

function runReceipt(value: unknown, kind: "PREPARATION" | "EVALUATION"): void {
  const receipt = record(value, kind, "scheduler receipt");
  exact(receipt, ["schema", "declarationDigest", "lockDigest", "bootstrapContext", "scratchId", "scratchCleanup", "reason", "selection", "status", "tasks"], [], kind, "scheduler receipt");
  if (receipt.schema !== "tc.sdlc/run-receipt/v1" || !digestValue(receipt.declarationDigest) || !digestValue(receipt.lockDigest) || !stringValue(receipt.scratchId) || !["removed", "retained"].includes(receipt.scratchCleanup as string) || !(receipt.reason === null || typeof receipt.reason === "string") || !terminalStatuses.has(receipt.status as string) || !Array.isArray(receipt.tasks)) invalid(kind, "scheduler receipt is invalid");
  digestArray(receipt.selection, kind, "scheduler selection");
  bootstrapContext(receipt.bootstrapContext, kind, receipt.lockDigest);
  for (const candidate of receipt.tasks) {
    const task = record(candidate, kind, "scheduler task");
    exact(task, ["key", "identity", "status", "exitCode", "reason", "stdout", "stderr", "outputTruncated", "executionContextDigest", "scratchId", "resources", "evidence", "missingEvidence", "events"], ["diagnostic"], kind, "scheduler task");
    if (!stringValue(task.key) || !digestValue(task.identity) || ![...terminalStatuses, "skipped"].includes(task.status as string) || !(task.exitCode === null || Number.isSafeInteger(task.exitCode)) || !(task.reason === null || typeof task.reason === "string") || typeof task.stdout !== "string" || typeof task.stderr !== "string" || typeof task.outputTruncated !== "boolean" || !digestValue(task.executionContextDigest) || !stringValue(task.scratchId) || !Array.isArray(task.evidence) || !Array.isArray(task.events)) invalid(kind, "scheduler task is invalid");
    const resources = record(task.resources, kind, "scheduler resources");
    exact(resources, ["cpu", "memoryMiB", "ports", "exclusive"], [], kind, "scheduler resources");
    if (typeof resources.cpu !== "number" || resources.cpu <= 0 || typeof resources.memoryMiB !== "number" || resources.memoryMiB <= 0 || !Array.isArray(resources.ports) || resources.ports.some((port) => !Number.isSafeInteger(port) || (port as number) < 0)) invalid(kind, "scheduler resources are invalid");
    stringArray(resources.exclusive, kind, "scheduler exclusive resources");
    stringArray(task.missingEvidence, kind, "scheduler missing evidence");
    for (const item of task.evidence) {
      const evidence = record(item, kind, "scheduler evidence");
      exact(evidence, ["path", "sourceDigest", "contentDigest", "mediaType", "content"], [], kind, "scheduler evidence");
      if (!stringValue(evidence.path) || !digestValue(evidence.sourceDigest) || !digestValue(evidence.contentDigest) || !stringValue(evidence.mediaType) || typeof evidence.content !== "string") invalid(kind, "scheduler evidence is invalid");
    }
    for (const item of task.events) {
      const event = record(item, kind, "scheduler event");
      exact(event, ["taskKey", "taskIdentity", "type"], ["stream", "text", "status", "reason"], kind, "scheduler event");
      if (!stringValue(event.taskKey) || !digestValue(event.taskIdentity) || !["start", "heartbeat", "output", "cancellation", "terminal"].includes(event.type as string) || (event.stream !== undefined && !["stdout", "stderr"].includes(event.stream as string)) || (event.text !== undefined && typeof event.text !== "string") || (event.status !== undefined && ![...terminalStatuses, "skipped"].includes(event.status as string)) || (event.reason !== undefined && typeof event.reason !== "string")) invalid(kind, "scheduler event is invalid");
    }
    if (task.diagnostic !== undefined) {
      const diagnostic = record(task.diagnostic, kind, "scheduler diagnostic");
      exact(diagnostic, ["pid", "running", "cpu", "memoryMiB", "ports", "exclusive", "stdoutBytes", "stderrBytes", "processes"], [], kind, "scheduler diagnostic");
      if (!Number.isSafeInteger(diagnostic.pid) || typeof diagnostic.running !== "boolean" || typeof diagnostic.cpu !== "number" || typeof diagnostic.memoryMiB !== "number" || !Array.isArray(diagnostic.ports) || !Array.isArray(diagnostic.exclusive) || !Number.isSafeInteger(diagnostic.stdoutBytes) || !Number.isSafeInteger(diagnostic.stderrBytes) || !Array.isArray(diagnostic.processes)) invalid(kind, "scheduler diagnostic is invalid");
      stringArray(diagnostic.exclusive, kind, "scheduler diagnostic exclusives");
      for (const item of diagnostic.processes) {
        const process = record(item, kind, "scheduler process");
        exact(process, ["pid", "parentPid", "state", "elapsed", "cpuPercent", "residentMemoryKiB"], [], kind, "scheduler process");
        if (!Number.isSafeInteger(process.pid) || !Number.isSafeInteger(process.parentPid) || !stringValue(process.state) || !stringValue(process.elapsed) || typeof process.cpuPercent !== "number" || typeof process.residentMemoryKiB !== "number") invalid(kind, "scheduler process is invalid");
      }
    }
  }
}

function mutation(value: unknown, kind: "PREPARATION" | "EVALUATION"): void {
  const item = record(value, kind, "tree mutation");
  exact(item, ["path", "kind"], ["before", "after"], kind, "tree mutation");
  if (!stringValue(item.path) || !["add", "delete", "content", "mode", "symlink"].includes(item.kind as string)) invalid(kind, "tree mutation is invalid");
  if (item.before !== undefined) inputDigest(item.before, kind, "tree mutation before input");
  if (item.after !== undefined) inputDigest(item.after, kind, "tree mutation after input");
}

export function validatePreparationReceipt(value: unknown): PreparationReceipt {
  const receipt = record(value, "PREPARATION", "preparation receipt");
  exact(receipt, ["schema", "status", "reason", "declarationDigest", "catalogueDigest", "lockDigest", "bootstrapContext", "recovery", "finalTreeDigest", "firstPass", "secondPass"], [], "PREPARATION", "preparation receipt");
  if (receipt.schema !== "tc.sdlc/preparation-receipt/v1" || !["succeeded", "failed"].includes(receipt.status as string) || !(receipt.reason === null || typeof receipt.reason === "string") || !digestValue(receipt.declarationDigest) || !digestValue(receipt.catalogueDigest) || !digestValue(receipt.lockDigest) || !digestValue(receipt.finalTreeDigest)) invalid("PREPARATION", "preparation receipt is invalid");
  bootstrapContext(receipt.bootstrapContext, "PREPARATION", receipt.lockDigest);
  recovery(receipt.recovery, "PREPARATION");
  for (const passName of ["firstPass", "secondPass"] as const) {
    const pass = record(receipt[passName], "PREPARATION", `${passName} preparation pass`);
    exact(pass, ["mutations", "mutationCount", "mutationsTruncated"], ["scheduler"], "PREPARATION", `${passName} preparation pass`);
    if (!Array.isArray(pass.mutations) || !Number.isSafeInteger(pass.mutationCount) || (pass.mutationCount as number) < 0 || typeof pass.mutationsTruncated !== "boolean") invalid("PREPARATION", `${passName} preparation pass is invalid`);
    if (
      (pass.mutationCount as number) < pass.mutations.length ||
      pass.mutationsTruncated !== ((pass.mutationCount as number) > pass.mutations.length)
    ) {
      invalid("PREPARATION", `${passName} mutation inventory is inconsistent`);
    }
    for (const item of pass.mutations) mutation(item, "PREPARATION");
    if (pass.scheduler !== undefined) runReceipt(pass.scheduler, "PREPARATION");
  }
  return receipt as PreparationReceipt;
}

export function parsePreparationReceipt(bytes: string): PreparationReceipt {
  let value: unknown;
  try { value = JSON.parse(bytes); } catch { return invalid("PREPARATION", "preparation receipt is not valid JSON"); }
  return validatePreparationReceipt(value);
}

export function validateEvaluationReceipt(value: unknown): EvaluationReceipt {
  const receipt = record(value, "EVALUATION", "evaluation receipt");
  exact(receipt, ["schema", "status", "reason", "source", "declarationDigest", "catalogueDigest", "lockDigest", "bootstrapContext", "environmentClass", "producer", "recovery", "tasks", "mutations", "mutationCount", "mutationsTruncated"], ["scheduler"], "EVALUATION", "evaluation receipt");
  if (receipt.schema !== "tc.sdlc/evaluation-receipt/v1" || !["succeeded", "failed"].includes(receipt.status as string) || !(receipt.reason === null || typeof receipt.reason === "string") || !digestValue(receipt.declarationDigest) || !digestValue(receipt.catalogueDigest) || !digestValue(receipt.lockDigest) || !stringValue(receipt.environmentClass) || !stringValue(receipt.producer) || !Array.isArray(receipt.tasks) || !Array.isArray(receipt.mutations) || !Number.isSafeInteger(receipt.mutationCount) || (receipt.mutationCount as number) < 0 || typeof receipt.mutationsTruncated !== "boolean") invalid("EVALUATION", "evaluation receipt is invalid");
  const source = record(receipt.source, "EVALUATION", "evaluation source");
  exact(source, ["commit", "treeDigest"], [], "EVALUATION", "evaluation source");
  if (!stringValue(source.commit) || !digestValue(source.treeDigest)) invalid("EVALUATION", "evaluation source is invalid");
  bootstrapContext(receipt.bootstrapContext, "EVALUATION", receipt.lockDigest);
  recovery(receipt.recovery, "EVALUATION");
  for (const candidate of receipt.tasks) {
    const task = record(candidate, "EVALUATION", "evaluation task");
    exact(task, ["key", "identity", "mode", "trustBoundary", "inputs", "outputs"], [], "EVALUATION", "evaluation task");
    if (!stringValue(task.key) || !digestValue(task.identity) || task.mode !== "evaluate" || !["portable", "hosted", "live", "deployment"].includes(task.trustBoundary as string) || !Array.isArray(task.inputs) || !Array.isArray(task.outputs)) invalid("EVALUATION", "evaluation task is invalid");
    for (const input of [...task.inputs, ...task.outputs]) inputDigest(input, "EVALUATION", "evaluation task input");
  }
  for (const item of receipt.mutations) mutation(item, "EVALUATION");
  if (receipt.scheduler !== undefined) runReceipt(receipt.scheduler, "EVALUATION");
  return receipt as EvaluationReceipt;
}

export function parseEvaluationReceipt(bytes: string): EvaluationReceipt {
  let value: unknown;
  try { value = JSON.parse(bytes); } catch { return invalid("EVALUATION", "evaluation receipt is not valid JSON"); }
  return validateEvaluationReceipt(value);
}

function assertBindings(receipt: ReceiptBindings, expected: ReceiptBindings, kind: "PREPARATION" | "EVALUATION"): void {
  if (receipt.declarationDigest !== expected.declarationDigest || receipt.catalogueDigest !== expected.catalogueDigest || receipt.lockDigest !== expected.lockDigest) invalid(kind, `${kind.toLowerCase()} receipt is not bound to the supplied declaration, catalogue and lock`);
}

export function assertSucceededPreparationReceipt(receipt: PreparationReceipt, expected: ReceiptBindings): void {
  assertBindings(receipt, expected, "PREPARATION");
  if (receipt.status !== "succeeded") invalid("PREPARATION", "preparation receipt is not succeeded");
  if (receipt.firstPass.scheduler?.status !== "succeeded" || receipt.secondPass.scheduler?.status !== "succeeded") {
    invalid("PREPARATION", "succeeded preparation receipt requires two succeeded scheduler passes");
  }
}

export function assertSucceededEvaluationReceipt(receipt: EvaluationReceipt, expected: ReceiptBindings): void {
  assertBindings(receipt, expected, "EVALUATION");
  if (receipt.status !== "succeeded") invalid("EVALUATION", "evaluation receipt is not succeeded");
}
