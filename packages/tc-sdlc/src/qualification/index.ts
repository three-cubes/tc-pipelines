import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  cpSync,
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  realpathSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { arch, platform } from "node:os";
import { basename, dirname, isAbsolute, join, posix, relative, resolve, sep } from "node:path";

import { parse } from "yaml";

import { bytesDigest, canonicalJson, digest } from "../canonical.js";
import { loadCatalogue } from "../catalogue/index.js";
import { SdlcError } from "../errors.js";
import { writeCanonicalEvidence } from "../evidence/index.js";
import {
  assertSucceededEvaluationReceipt,
  assertSucceededPreparationReceipt,
  parseEvaluationReceipt,
  parsePreparationReceipt,
  validateEvaluationReceipt,
  validatePreparationReceipt,
} from "../evidence/task4.js";
import { snapshotFiles } from "../inputs/index.js";
import { loadLock } from "../lock/index.js";
import { loadDeclaration } from "../schema/declaration.js";
import { assertSchema } from "../schema/validation.js";

type Consumer = Readonly<{
  id: string;
  fixture: string;
  languages: readonly ("python" | "node")[];
  changed: string;
  complete_tasks: readonly string[];
  affected_tasks: readonly string[];
}>;

type ConsumerManifest = Readonly<{
  schema: "tc.sdlc/disposable-consumers/v1";
  consumers: readonly Consumer[];
}>;

type ReceiptReference = Readonly<{
  path: string | null;
  digest: string | null;
  status: string | null;
  taskIdentities: readonly string[];
}>;

type PreparationReference = ReceiptReference & Readonly<{
  firstPassTaskIdentities: readonly string[];
  secondPassTaskIdentities: readonly string[];
}>;

type FixtureQualification = {
  id: string;
  fixtureDigest: string | null;
  expectedChangedPath: string | null;
  status: "succeeded" | "failed";
  reason: string | null;
  bootstrap: ReceiptReference;
  preparation: PreparationReference;
  complete: ReceiptReference;
  affected: ReceiptReference;
  identityStable: boolean | null;
};

export type ConsumerQualificationReceipt = Readonly<{
  schema: "tc.sdlc/consumer-qualification/v1";
  status: "succeeded" | "failed";
  reason: string | null;
  manifestDigest: string | null;
  catalogueDigest: string | null;
  package: Readonly<{ name: "@three-cubes/tc-sdlc"; version: string }>;
  executableDigest: string;
  environment: Readonly<{ class: string; platform: string; architecture: string }>;
  fixtures: readonly Readonly<FixtureQualification>[];
}>;

export type QualifyConsumersOptions = Readonly<{
  manifestPath: string;
  cataloguePath: string;
  outputDirectory: string;
  receiptPath: string;
  executablePath: string;
}>;

function sha256File(path: string): string {
  return `sha256:${createHash("sha256").update(readFileSync(path)).digest("hex")}`;
}

function packageDigest(executablePath: string): string {
  const packageRoot = dirname(dirname(realpathSync(executablePath)));
  const manifest = join(packageRoot, "package.json");
  const inventory = [
    {
      path: "package.json",
      digest: sha256File(manifest),
      mode: statSync(manifest).mode & 0o777,
      symlink: null,
    },
    ...["bin", "dist"].flatMap((directory) =>
      snapshotFiles(join(packageRoot, directory)).map((entry) => ({
        ...entry,
        path: `${directory}/${entry.path}`,
      })),
    ),
  ].sort((left, right) => left.path.localeCompare(right.path));
  return digest(inventory);
}

function ownRelative(root: string, path: string): string {
  const resolvedRoot = resolve(root);
  const resolvedPath = resolve(path);
  const value = relative(resolvedRoot, resolvedPath);
  if (value === "" || value === ".." || value.startsWith(`..${sep}`) || isAbsolute(value)) {
    throw new SdlcError("CONSUMER_QUALIFICATION_PATH_INVALID", "receipt must be below the owned output directory");
  }
  return value.split(sep).join(posix.sep);
}

function assertRealDirectory(path: string, label: string): void {
  const metadata = lstatSync(path);
  if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
    throw new SdlcError("CONSUMER_FIXTURE_INVALID", `${label} must be a real directory`);
  }
}

function assertRealFixture(manifestDirectory: string, fixture: string): string {
  if (
    fixture.length === 0 ||
    posix.isAbsolute(fixture.replaceAll("\\", "/")) ||
    fixture.replaceAll("\\", "/").split("/").some((segment) => segment === "" || segment === "." || segment === "..")
  ) {
    throw new SdlcError("CONSUMER_FIXTURE_INVALID", "fixture path must be a relative non-traversing path");
  }
  const root = realpathSync(manifestDirectory);
  const candidate = resolve(root, fixture);
  if (candidate === root || !candidate.startsWith(`${root}${sep}`) || !existsSync(candidate)) {
    throw new SdlcError("CONSUMER_FIXTURE_INVALID", `fixture does not exist beneath manifest directory: ${fixture}`);
  }
  let cursor = root;
  for (const part of relative(root, candidate).split(sep)) {
    cursor = join(cursor, part);
    const metadata = lstatSync(cursor);
    if (metadata.isSymbolicLink()) {
      throw new SdlcError("CONSUMER_FIXTURE_INVALID", `fixture may not traverse symbolic links: ${fixture}`);
    }
  }
  assertRealDirectory(candidate, `fixture ${fixture}`);
  const stack = [candidate];
  while (stack.length > 0) {
    const current = stack.pop()!;
    for (const name of readdirSync(current).sort()) {
      if (name.toLocaleLowerCase("en-US") === ".git") {
        throw new SdlcError("CONSUMER_FIXTURE_INVALID", "fixture may not contain Git metadata");
      }
      const child = join(current, name);
      const metadata = lstatSync(child);
      if (metadata.isSymbolicLink()) {
        throw new SdlcError("CONSUMER_FIXTURE_INVALID", `fixture may not contain symbolic links: ${fixture}`);
      }
      if (metadata.isDirectory()) stack.push(child);
    }
  }
  return candidate;
}

function manifestError(message: string): never {
  throw new SdlcError("CONSUMER_MANIFEST_INVALID", message);
}

function stringList(value: unknown, name: string): readonly string[] {
  if (!Array.isArray(value) || value.length === 0 || value.some((entry) => typeof entry !== "string" || entry.length === 0)) {
    return manifestError(`${name} must be a non-empty list of strings`);
  }
  return value;
}

function loadManifest(path: string): ConsumerManifest {
  let value: unknown;
  try {
    value = parse(readFileSync(path, "utf8"), { uniqueKeys: true });
  } catch (error) {
    throw new SdlcError("CONSUMER_MANIFEST_INVALID", `could not read consumer manifest: ${error instanceof Error ? error.message : String(error)}`);
  }
  if (value === null || typeof value !== "object" || Array.isArray(value)) return manifestError("manifest must be an object");
  const root = value as Record<string, unknown>;
  if (Object.keys(root).some((key) => key !== "schema" && key !== "consumers")) return manifestError("manifest contains an unknown field");
  if (root.schema !== "tc.sdlc/disposable-consumers/v1" || !Array.isArray(root.consumers) || root.consumers.length === 0) {
    return manifestError("manifest schema or consumers is invalid");
  }
  const ids = new Set<string>();
  const consumers = root.consumers.map((entry): Consumer => {
    if (entry === null || typeof entry !== "object" || Array.isArray(entry)) return manifestError("consumer must be an object");
    const consumer = entry as Record<string, unknown>;
    const allowed = ["id", "fixture", "languages", "changed", "complete_tasks", "affected_tasks"];
    if (Object.keys(consumer).some((key) => !allowed.includes(key))) return manifestError("consumer contains an unknown field");
    if (typeof consumer.id !== "string" || !/^[a-z0-9][a-z0-9-]*$/.test(consumer.id) || ids.has(consumer.id)) {
      return manifestError("consumer id must be unique and URL-safe");
    }
    ids.add(consumer.id);
    if (typeof consumer.fixture !== "string" || typeof consumer.changed !== "string") return manifestError("consumer fixture and changed must be strings");
    const languages = stringList(consumer.languages, "languages");
    if (languages.some((language) => language !== "python" && language !== "node") || new Set(languages).size !== languages.length) return manifestError("languages must contain unique python or node values");
    return {
      id: consumer.id,
      fixture: consumer.fixture,
      languages: languages as readonly ("python" | "node")[],
      changed: consumer.changed,
      complete_tasks: stringList(consumer.complete_tasks, "complete_tasks"),
      affected_tasks: stringList(consumer.affected_tasks, "affected_tasks"),
    };
  });
  return { schema: "tc.sdlc/disposable-consumers/v1", consumers };
}

function packageVersion(): string {
  const packageJson = JSON.parse(readFileSync(new URL("../../package.json", import.meta.url), "utf8")) as { version?: unknown };
  if (typeof packageJson.version !== "string") throw new SdlcError("CONSUMER_QUALIFICATION_INTERNAL", "package version is unavailable");
  return packageJson.version;
}

function validateOutputDestination(output: string, receipt: string): void {
  if (existsSync(output)) {
    throw new SdlcError("CONSUMER_OUTPUT_EXISTS", "consumer qualification output directory must not already exist");
  }
  const parent = dirname(output);
  if (!existsSync(parent) || !lstatSync(parent).isDirectory() || lstatSync(parent).isSymbolicLink()) {
    throw new SdlcError("CONSUMER_QUALIFICATION_PATH_INVALID", "output parent must be an existing real directory");
  }
  const relativeReceipt = ownRelative(output, receipt);
  if (posix.dirname(relativeReceipt) !== "." || relativeReceipt === "." || relativeReceipt.startsWith(".")) {
    throw new SdlcError("CONSUMER_QUALIFICATION_PATH_INVALID", "outer receipt path collides with reserved qualification namespace");
  }
}

function reserveOuterReceipt(output: string, receipt: string, consumerIds: readonly string[]): void {
  const relativeReceipt = ownRelative(output, receipt);
  const foldedReceipt = relativeReceipt.toLocaleLowerCase("en-US");
  if (
    consumerIds.some((id) => id.toLocaleLowerCase("en-US") === foldedReceipt) ||
    [".state", "candidate-catalogue.json"].some((name) => name.toLocaleLowerCase("en-US") === foldedReceipt)
  ) {
    throw new SdlcError("CONSUMER_QUALIFICATION_PATH_INVALID", "outer receipt path collides with reserved qualification namespace");
  }
}

function emptyReference(): ReceiptReference {
  return { path: null, digest: null, status: null, taskIdentities: [] };
}

function emptyPreparationReference(): PreparationReference {
  return { ...emptyReference(), firstPassTaskIdentities: [], secondPassTaskIdentities: [] };
}

const terminalStatuses = new Set(["succeeded", "failed", "stalled", "cancelled"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function stringValue(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function digestValue(value: unknown): value is string {
  return typeof value === "string" && /^sha256:[a-f0-9]{64}$/.test(value);
}

function requireExactKeys(value: Record<string, unknown>, required: readonly string[], optional: readonly string[] = []): void {
  if (
    required.some((key) => value[key] === undefined) ||
    Object.keys(value).some((key) => !required.includes(key) && !optional.includes(key))
  ) {
    throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has an invalid producer-specific shape");
  }
}

function receiptValue(path: string, schema: string): Record<string, unknown> {
  let value: unknown;
  try {
    value = JSON.parse(readFileSync(path, "utf8"));
  } catch {
    throw new SdlcError("CONSUMER_RECEIPT_INVALID", `nested ${schema} receipt is unreadable`);
  }
  if (
    !isRecord(value) || value.schema !== schema
  ) {
    throw new SdlcError("CONSUMER_RECEIPT_INVALID", `nested receipt does not have schema ${schema}`);
  }
  return value as Record<string, unknown>;
}

function requireSucceededReceipt(path: string, schema: string): Record<string, unknown> {
  const value = receiptValue(path, schema);
  if (value.status !== "succeeded") {
    throw new SdlcError("CONSUMER_RECEIPT_INVALID", `nested ${schema} receipt is not succeeded`);
  }
  return value;
}

function requireStringArray(value: unknown): void {
  if (!Array.isArray(value) || value.some((entry) => !stringValue(entry))) {
    throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has an invalid string inventory");
  }
}

function requireDigestArray(value: unknown): void {
  if (!Array.isArray(value) || value.some((entry) => !digestValue(entry))) {
    throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has an invalid digest inventory");
  }
}

function requireRecovery(value: unknown): void {
  if (!isRecord(value)) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has an invalid recovery receipt");
  requireExactKeys(value, ["schema", "status", "boundary", "retentionHours", "candidateCount", "removedCount", "reclaimedBytes", "entriesTruncated", "cleanupFailures", "peakCleanupWorkers"]);
  if (value.schema !== "tc.sdlc/automatic-recovery/v1" || !["succeeded", "partial"].includes(value.status as string) || value.boundary !== "os-temporary-root" || value.retentionHours !== 48 || [value.candidateCount, value.removedCount, value.reclaimedBytes, value.cleanupFailures, value.peakCleanupWorkers].some((entry) => !Number.isSafeInteger(entry) || (entry as number) < 0) || typeof value.entriesTruncated !== "boolean") {
    throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has an invalid recovery receipt");
  }
}

function requireBootstrapContext(value: unknown, lockDigest?: string): void {
  if (!isRecord(value)) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has an invalid bootstrap context binding");
  requireExactKeys(value, ["schema", "release", "platform", "architecture", "lockDigest", "stateKey", "stateGenerationIdentity", "bootstrapReceiptDigest", "stateDigest", "dependencyDigest", "fitness", "adapters"]);
  if (value.schema !== "tc.sdlc/execution-context/v1" || (lockDigest !== undefined && value.lockDigest !== lockDigest) || !stringValue(value.release) || !["darwin", "linux"].includes(value.platform as string) || !stringValue(value.architecture) || !digestValue(value.lockDigest) || !stringValue(value.stateKey) || !digestValue(value.stateGenerationIdentity) || !digestValue(value.bootstrapReceiptDigest) || !digestValue(value.stateDigest) || !digestValue(value.dependencyDigest) || !isRecord(value.fitness) || !Array.isArray(value.adapters)) {
    throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has an invalid bootstrap context binding");
  }
  requireExactKeys(value.fitness, ["package", "version"]);
  if (!stringValue(value.fitness.package) || !stringValue(value.fitness.version)) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has an invalid bootstrap context binding");
  for (const adapter of value.adapters) {
    if (!isRecord(adapter)) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has an invalid bootstrap context binding");
    requireExactKeys(adapter, ["name", "version", "adapterDigest"]);
    if (!["node", "pnpm", "python", "uv"].includes(adapter.name as string) || !stringValue(adapter.version) || !digestValue(adapter.adapterDigest)) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has an invalid bootstrap context binding");
  }
}

function requireRunReceipt(value: unknown): void {
  if (!isRecord(value)) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has an invalid scheduler receipt");
  requireExactKeys(value, ["schema", "declarationDigest", "lockDigest", "bootstrapContext", "scratchId", "scratchCleanup", "reason", "selection", "status", "tasks"]);
  if (value.schema !== "tc.sdlc/run-receipt/v1" || !digestValue(value.declarationDigest) || !digestValue(value.lockDigest) || !stringValue(value.scratchId) || !["removed", "retained"].includes(value.scratchCleanup as string) || !(value.reason === null || typeof value.reason === "string") || !terminalStatuses.has(value.status as string) || !Array.isArray(value.tasks)) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has an invalid scheduler receipt");
  requireDigestArray(value.selection);
  requireBootstrapContext(value.bootstrapContext, value.lockDigest);
  for (const task of value.tasks) {
    if (!isRecord(task)) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has an invalid scheduler task");
    requireExactKeys(task, ["key", "identity", "status", "exitCode", "reason", "stdout", "stderr", "outputTruncated", "executionContextDigest", "scratchId", "resources", "evidence", "missingEvidence", "events"], ["diagnostic"]);
    if (!stringValue(task.key) || !digestValue(task.identity) || ![...terminalStatuses, "skipped"].includes(task.status as string) || !(task.exitCode === null || Number.isSafeInteger(task.exitCode)) || !(task.reason === null || typeof task.reason === "string") || typeof task.stdout !== "string" || typeof task.stderr !== "string" || typeof task.outputTruncated !== "boolean" || !digestValue(task.executionContextDigest) || !stringValue(task.scratchId) || !isRecord(task.resources) || !Array.isArray(task.evidence) || !Array.isArray(task.events)) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has an invalid scheduler task");
    requireExactKeys(task.resources, ["cpu", "memoryMiB", "ports", "exclusive"]);
    if (typeof task.resources.cpu !== "number" || task.resources.cpu <= 0 || typeof task.resources.memoryMiB !== "number" || task.resources.memoryMiB <= 0 || !Array.isArray(task.resources.ports) || task.resources.ports.some((port) => !Number.isSafeInteger(port) || port < 0) || !Array.isArray(task.resources.exclusive)) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has an invalid scheduler resources");
    requireStringArray(task.resources.exclusive); requireStringArray(task.missingEvidence);
    for (const evidence of task.evidence) { if (!isRecord(evidence)) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has invalid scheduler evidence"); requireExactKeys(evidence, ["path", "sourceDigest", "contentDigest", "mediaType", "content"]); if (!stringValue(evidence.path) || !digestValue(evidence.sourceDigest) || !digestValue(evidence.contentDigest) || !stringValue(evidence.mediaType) || typeof evidence.content !== "string") throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has invalid scheduler evidence"); }
    for (const event of task.events) { if (!isRecord(event)) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has invalid scheduler event"); requireExactKeys(event, ["taskKey", "taskIdentity", "type"], ["stream", "text", "status", "reason"]); if (!stringValue(event.taskKey) || !digestValue(event.taskIdentity) || !["start", "heartbeat", "output", "cancellation", "terminal"].includes(event.type as string) || (event.stream !== undefined && !["stdout", "stderr"].includes(event.stream as string)) || (event.text !== undefined && typeof event.text !== "string") || (event.status !== undefined && ![...terminalStatuses, "skipped"].includes(event.status as string)) || (event.reason !== undefined && typeof event.reason !== "string")) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has invalid scheduler event"); }
    if (task.diagnostic !== undefined) { if (!isRecord(task.diagnostic)) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has invalid scheduler diagnostic"); requireExactKeys(task.diagnostic, ["pid", "running", "cpu", "memoryMiB", "ports", "exclusive", "stdoutBytes", "stderrBytes", "processes"]); if (!Number.isSafeInteger(task.diagnostic.pid) || typeof task.diagnostic.running !== "boolean" || typeof task.diagnostic.cpu !== "number" || typeof task.diagnostic.memoryMiB !== "number" || !Array.isArray(task.diagnostic.ports) || !Array.isArray(task.diagnostic.exclusive) || !Number.isSafeInteger(task.diagnostic.stdoutBytes) || !Number.isSafeInteger(task.diagnostic.stderrBytes) || !Array.isArray(task.diagnostic.processes)) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has invalid scheduler diagnostic"); requireStringArray(task.diagnostic.exclusive); for (const process of task.diagnostic.processes) { if (!isRecord(process)) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has invalid scheduler process"); requireExactKeys(process, ["pid", "parentPid", "state", "elapsed", "cpuPercent", "residentMemoryKiB"]); if (!Number.isSafeInteger(process.pid) || !Number.isSafeInteger(process.parentPid) || !stringValue(process.state) || !stringValue(process.elapsed) || typeof process.cpuPercent !== "number" || typeof process.residentMemoryKiB !== "number") throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt has invalid scheduler process"); } }
  }
}

function requireBootstrapReceiptShape(value: Record<string, unknown>): void {
  requireExactKeys(value, ["schema", "status", "reason", "release", "lockDigest", "platform", "architecture", "stateKey", "stateDigest", "reused", "taskIdentities", "adapters", "dependencies", "recovery", "diagnostics", "diagnosticsCount", "diagnosticsTruncated"]);
  if (
    !["succeeded", "failed"].includes(value.status as string) || !(value.reason === null || typeof value.reason === "string") || !stringValue(value.release) || !digestValue(value.lockDigest) ||
    !["darwin", "linux"].includes(value.platform as string) || !stringValue(value.architecture) || !stringValue(value.stateKey) || !(value.stateDigest === null || digestValue(value.stateDigest)) || typeof value.reused !== "boolean" || !Array.isArray(value.adapters) || !Array.isArray(value.dependencies) ||
    !Array.isArray(value.diagnostics) || !Number.isSafeInteger(value.diagnosticsCount) || typeof value.diagnosticsTruncated !== "boolean"
  ) {
    throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested bootstrap receipt is not a complete producer receipt");
  }
  requireDigestArray(value.taskIdentities); requireRecovery(value.recovery);
  for (const adapter of value.adapters) { if (!isRecord(adapter)) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested bootstrap receipt has invalid adapter"); requireExactKeys(adapter, ["name", "version", "provider", "executableDigest", "launcherDigest", "adapterDigest", "launcher"]); if (!["node", "pnpm", "python", "uv"].includes(adapter.name as string) || !stringValue(adapter.version) || !["homebrew", "canonical-image", "catalogue-distribution"].includes(adapter.provider as string) || !digestValue(adapter.executableDigest) || !digestValue(adapter.launcherDigest) || !digestValue(adapter.adapterDigest) || !stringValue(adapter.launcher)) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested bootstrap receipt has invalid adapter"); }
  for (const dependency of value.dependencies) { if (!isRecord(dependency)) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested bootstrap receipt has invalid dependency"); requireExactKeys(dependency, ["manager", "lockDigest", "manifestDigest", "environment", "inputs"], ["installedDigest"]); if (!["pnpm", "uv"].includes(dependency.manager as string) || !digestValue(dependency.lockDigest) || !digestValue(dependency.manifestDigest) || !stringValue(dependency.environment) || !Array.isArray(dependency.inputs) || (dependency.installedDigest !== undefined && !digestValue(dependency.installedDigest))) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested bootstrap receipt has invalid dependency"); for (const input of dependency.inputs) { if (!isRecord(input)) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested bootstrap receipt has invalid dependency input"); requireExactKeys(input, ["path", "digest"]); if (!stringValue(input.path) || !digestValue(input.digest)) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested bootstrap receipt has invalid dependency input"); } }
  for (const diagnostic of value.diagnostics) { if (!isRecord(diagnostic)) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested bootstrap receipt has invalid diagnostic"); requireExactKeys(diagnostic, ["code", "message", "action"], ["capability", "expected", "observed"]); if (!stringValue(diagnostic.code) || !stringValue(diagnostic.message) || !stringValue(diagnostic.action) || (diagnostic.capability !== undefined && !["node", "pnpm", "python", "uv"].includes(diagnostic.capability as string)) || (diagnostic.expected !== undefined && !stringValue(diagnostic.expected)) || (diagnostic.observed !== undefined && !stringValue(diagnostic.observed))) throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested bootstrap receipt has invalid diagnostic"); }
}

function requireBootstrapReceipt(value: Record<string, unknown>, expected: Readonly<{ lockDigest: string; release: string }>): void {
  requireBootstrapReceiptShape(value);
  if (value.status !== "succeeded" || value.release !== expected.release || value.lockDigest !== expected.lockDigest || !digestValue(value.stateDigest)) {
    throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested bootstrap receipt is not a complete succeeded receipt bound to the copied lock and release");
  }
}

function receiptReference(output: string, path: string, taskIdentities: readonly string[] = []): ReceiptReference {
  const referencePath = (() => {
    try { return ownRelative(output, path); } catch { return null; }
  })();
  if (!existsSync(path)) return emptyReference();
  let digestValueAtPath: string | null = null;
  try { digestValueAtPath = sha256File(path); } catch { /* retain the path when a hostile file becomes unreadable */ }
  let value: { schema?: unknown; status?: unknown; taskIdentities?: unknown; tasks?: unknown; scheduler?: { selection?: unknown } };
  try {
    const parsed = JSON.parse(readFileSync(path, "utf8"));
    if (!isRecord(parsed)) return { path: referencePath, digest: digestValueAtPath, status: null, taskIdentities: [] };
    value = parsed as typeof value;
    if (value.schema === "tc.sdlc/bootstrap-receipt/v1") requireBootstrapReceiptShape(value);
    else if (value.schema === "tc.sdlc/preparation-receipt/v1") validatePreparationReceipt(value);
    else if (value.schema === "tc.sdlc/evaluation-receipt/v1") validateEvaluationReceipt(value);
    else return { path: referencePath, digest: digestValueAtPath, status: null, taskIdentities: [] };
  } catch {
    return { path: referencePath, digest: digestValueAtPath, status: null, taskIdentities: [] };
  }
  const identities = taskIdentities.length > 0 ? [...taskIdentities].sort() :
    Array.isArray(value.taskIdentities) ? value.taskIdentities.filter(digestValue).sort() :
    Array.isArray(value.tasks) ? value.tasks.flatMap((entry) => isRecord(entry) && digestValue(entry.identity) ? [entry.identity] : []).sort() :
    Array.isArray(value.scheduler?.selection) ? value.scheduler.selection.filter(digestValue).sort() : [];
  return { path: referencePath, digest: digestValueAtPath, status: terminalStatuses.has(value.status as string) ? value.status as string : null, taskIdentities: identities };
}

function preparationReference(output: string, path: string): PreparationReference {
  const reference = receiptReference(output, path);
  if (!existsSync(path)) return emptyPreparationReference();
  try {
    const value = parsePreparationReceipt(readFileSync(path, "utf8"));
    const identities = (selection: unknown): readonly string[] =>
      Array.isArray(selection) && selection.every(digestValue)
        ? [...selection].sort()
        : (() => { throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested preparation receipt has an invalid scheduler selection"); })();
    return {
      ...reference,
      firstPassTaskIdentities: value.firstPass.scheduler === undefined ? [] : identities(value.firstPass.scheduler.selection),
      secondPassTaskIdentities: value.secondPass.scheduler === undefined ? [] : identities(value.secondPass.scheduler.selection),
    };
  } catch {
    return { ...reference, status: null, taskIdentities: [], firstPassTaskIdentities: [], secondPassTaskIdentities: [] };
  }
}

function receiptTaskKeys(path: string): readonly string[] {
  try {
    const value = JSON.parse(readFileSync(path, "utf8"));
    if (!isRecord(value) || !Array.isArray(value.tasks)) return [];
    return value.tasks.flatMap((entry) => isRecord(entry) && stringValue(entry.key) ? [entry.key] : []).sort();
  } catch { return []; }
}

function runPublic(executable: string, args: readonly string[]): void {
  const environment = Object.fromEntries(
    Object.entries(process.env).filter(([name]) => !name.startsWith("GIT_")),
  );
  const result = spawnSync(process.execPath, [executable, ...args], { encoding: "utf8", env: environment });
  if (result.status !== 0) {
    const diagnostic = typeof result.stderr === "string" ? result.stderr.trim() : "";
    throw new SdlcError("CONSUMER_COMMAND_FAILED", diagnostic || `tc-sdlc ${args[0]} failed`);
  }
}

function initialiseCheckout(root: string): void {
  const gitHome = join(dirname(root), "git-home");
  mkdirSync(gitHome, { recursive: true, mode: 0o700 });
  const environment = {
    PATH: "/usr/bin:/bin",
    HOME: gitHome,
    GIT_CONFIG_NOSYSTEM: "1",
    GIT_CONFIG_GLOBAL: "/dev/null",
    GIT_TERMINAL_PROMPT: "0",
  };
  for (const args of [["init", "-q"], ["config", "user.name", "tc-sdlc qualification"], ["config", "user.email", "qualification@three-cubes.invalid"], ["add", "."], ["commit", "-qm", "fixture"]] as const) {
    const result = spawnSync("git", args, { cwd: root, env: environment, encoding: "utf8" });
    if (result.status !== 0) throw new SdlcError("CONSUMER_CHECKOUT_FAILED", `could not initialise disposable Git checkout: ${result.stderr}`);
  }
}

function capacityIdentities(output: string, executable: string, base: readonly string[], singleReceipt: string, detectedReceipt: string): boolean {
  runPublic(executable, [...base, "--receipt", singleReceipt, "--capacity", "1"]);
  runPublic(executable, [...base, "--receipt", detectedReceipt]);
  requireSucceededReceipt(singleReceipt, "tc.sdlc/evaluation-receipt/v1");
  requireSucceededReceipt(detectedReceipt, "tc.sdlc/evaluation-receipt/v1");
  const single = receiptReference(output, singleReceipt).taskIdentities;
  const detected = receiptReference(output, detectedReceipt).taskIdentities;
  return canonicalJson(single) === canonicalJson(detected);
}

function appendChange(root: string, changed: string): void {
  const normalised = changed.replaceAll("\\", "/");
  if (normalised.length === 0 || posix.isAbsolute(normalised) || normalised.split("/").some((part) => part === "" || part === "." || part === "..")) {
    throw new SdlcError("CONSUMER_MANIFEST_INVALID", "changed path must be a relative non-traversing file path");
  }
  const path = resolve(root, normalised);
  if (!path.startsWith(`${resolve(root)}${sep}`) || !existsSync(path) || !statSync(path).isFile() || lstatSync(path).isSymbolicLink()) {
    throw new SdlcError("CONSUMER_FIXTURE_INVALID", `changed path does not name a real fixture file: ${changed}`);
  }
  writeFileSync(path, `${readFileSync(path, "utf8")}\n`);
}

export async function qualifyConsumers(options: QualifyConsumersOptions): Promise<ConsumerQualificationReceipt> {
  const output = resolve(options.outputDirectory);
  const receipt = resolve(options.receiptPath);
  validateOutputDestination(output, receipt);
  mkdirSync(output, { mode: 0o700 });
  let packageInfo: Readonly<{ name: "@three-cubes/tc-sdlc"; version: string }> = {
    name: "@three-cubes/tc-sdlc",
    version: packageVersion(),
  };
  const environment = { class: `native-${platform()}`, platform: platform(), architecture: arch() };
  const fixtures: FixtureQualification[] = [];
  let manifestDigest: string | null = null;
  let catalogueDigest: string | null = null;
  let reason: string | null = null;
  try {
    const authority = loadCatalogue(options.cataloguePath);
    catalogueDigest = digest(authority);
    if (authority.release.package.version !== packageInfo.version) {
      throw new SdlcError("CONSUMER_QUALIFICATION_INTERNAL", "packed package version does not match its release catalogue authority");
    }
    packageInfo = authority.release.package;
    const manifest = loadManifest(options.manifestPath);
    reserveOuterReceipt(output, receipt, manifest.consumers.map((consumer) => consumer.id));
    manifestDigest = sha256File(options.manifestPath);
    const candidateCatalogue = join(output, "candidate-catalogue.json");
    runPublic(options.executablePath, ["catalogue", "--input", options.cataloguePath, "--output", candidateCatalogue]);
    for (const consumer of manifest.consumers) {
      const bootstrap = join(output, consumer.id, "evidence", "bootstrap.json");
      const preparation = join(output, consumer.id, "evidence", "preparation.json");
      const complete = join(output, consumer.id, "evidence", "complete.json");
      const affected = join(output, consumer.id, "evidence", "affected.json");
      const completeSingle = `${complete}.single`;
      const affectedSingle = `${affected}.single`;
      const fixtureResult: FixtureQualification = {
        id: consumer.id,
        fixtureDigest: null as string | null,
        expectedChangedPath: consumer.changed,
        status: "failed",
        reason: null as string | null,
        bootstrap: emptyReference(),
        preparation: emptyPreparationReference(),
        complete: emptyReference(),
        affected: emptyReference(),
        identityStable: null as boolean | null,
      };
      try {
        const source = assertRealFixture(dirname(resolve(options.manifestPath)), consumer.fixture);
        if (consumer.languages.includes("python") && !existsSync(join(source, "uv.lock"))) throw new SdlcError("CONSUMER_FIXTURE_INVALID", `Python fixture is missing uv.lock: ${consumer.id}`);
        if (consumer.languages.includes("node") && !existsSync(join(source, "pnpm-lock.yaml"))) throw new SdlcError("CONSUMER_FIXTURE_INVALID", `Node fixture is missing pnpm-lock.yaml: ${consumer.id}`);
        fixtureResult.fixtureDigest = digest(snapshotFiles(source));
        const checkout = join(output, consumer.id, "checkout");
        mkdirSync(dirname(bootstrap), { recursive: true, mode: 0o700 });
        cpSync(source, checkout, { recursive: true, dereference: false, errorOnExist: true });
        initialiseCheckout(checkout);
        const catalogue = join(output, consumer.id, "catalogue.json");
        const lock = join(checkout, "tc-sdlc.lock");
        const state = join(output, ".state", consumer.id);
        runPublic(options.executablePath, ["catalogue", "--input", candidateCatalogue, "--output", catalogue]);
        runPublic(options.executablePath, ["lock", "--declaration", join(checkout, "sdlc.yaml"), "--catalogue", catalogue, "--output", lock]);
        const declaration = loadDeclaration(join(checkout, "sdlc.yaml"));
        const copiedCatalogue = loadCatalogue(catalogue);
        const copiedLock = loadLock(lock).lock;
        const bindings = {
          declarationDigest: digest(declaration),
          catalogueDigest: digest(copiedCatalogue),
          lockDigest: digest(copiedLock),
        };
        runPublic(options.executablePath, ["bootstrap", "--declaration", join(checkout, "sdlc.yaml"), "--catalogue", catalogue, "--lock", lock, "--root", checkout, "--state-root", state, "--receipt", bootstrap]);
        const bootstrapReceipt = requireSucceededReceipt(bootstrap, "tc.sdlc/bootstrap-receipt/v1");
        requireBootstrapReceipt(bootstrapReceipt, { lockDigest: bindings.lockDigest, release: copiedCatalogue.release.version });
        appendChange(checkout, consumer.changed);
        runPublic(options.executablePath, ["prepare", "--declaration", join(checkout, "sdlc.yaml"), "--catalogue", catalogue, "--lock", lock, "--root", checkout, "--state-root", state, "--bootstrap-receipt", bootstrap, "--receipt", preparation]);
        const preparationReceipt = parsePreparationReceipt(readFileSync(preparation, "utf8"));
        assertSucceededPreparationReceipt(preparationReceipt, bindings);
        if (
          preparationReceipt.bootstrapContext === null ||
          typeof preparationReceipt.bootstrapContext !== "object" ||
          canonicalJson(preparationReceipt.firstPass) === canonicalJson(undefined) ||
          canonicalJson(preparationReceipt.secondPass) === canonicalJson(undefined)
        ) {
          throw new SdlcError("CONSUMER_RECEIPT_INVALID", "preparation receipt does not retain both fixed-point passes and bootstrap binding");
        }
        const common = ["--declaration", join(checkout, "sdlc.yaml"), "--catalogue", catalogue, "--lock", lock, "--root", checkout, "--state-root", state, "--bootstrap-receipt", bootstrap, "--preparation-receipt", preparation, "--environment", environment.class, "--producer", "tc-sdlc qualify-consumers"];
        const completeStable = capacityIdentities(output, options.executablePath, ["check-all", ...common], completeSingle, complete);
        const affectedStable = capacityIdentities(output, options.executablePath, ["check", ...common, "--changed", consumer.changed], affectedSingle, affected);
        const completeReference = receiptReference(output, complete);
        const affectedReference = receiptReference(output, affected);
        const completeReceipt = parseEvaluationReceipt(readFileSync(complete, "utf8"));
        const affectedReceipt = parseEvaluationReceipt(readFileSync(affected, "utf8"));
        assertSucceededEvaluationReceipt(completeReceipt, bindings);
        assertSucceededEvaluationReceipt(affectedReceipt, bindings);
        if (
          canonicalJson(completeReceipt.bootstrapContext) !== canonicalJson(preparationReceipt.bootstrapContext) ||
          canonicalJson(affectedReceipt.bootstrapContext) !== canonicalJson(preparationReceipt.bootstrapContext)
        ) {
          throw new SdlcError("CONSUMER_RECEIPT_INVALID", "evaluation receipt bootstrap binding does not match preparation");
        }
        if (canonicalJson(receiptTaskKeys(complete)) !== canonicalJson([...consumer.complete_tasks].sort())) throw new SdlcError("CONSUMER_TASK_SET_MISMATCH", `complete task set does not match fixture declaration: ${consumer.id}`);
        if (canonicalJson(receiptTaskKeys(affected)) !== canonicalJson([...consumer.affected_tasks].sort())) throw new SdlcError("CONSUMER_AFFECTED_CLOSURE_MISMATCH", `affected task set does not match fixture declaration: ${consumer.id}`);
        if (!completeStable || !affectedStable) throw new SdlcError("CONSUMER_IDENTITY_UNSTABLE", `task identities changed with capacity: ${consumer.id}`);
        fixtureResult.status = "succeeded";
        fixtureResult.bootstrap = receiptReference(output, bootstrap);
        fixtureResult.preparation = preparationReference(output, preparation);
        fixtureResult.complete = completeReference;
        fixtureResult.affected = affectedReference;
        fixtureResult.identityStable = true;
      } catch (error) {
        fixtureResult.reason = error instanceof Error ? error.message : String(error);
        fixtureResult.bootstrap = receiptReference(output, bootstrap);
        fixtureResult.preparation = preparationReference(output, preparation);
        fixtureResult.complete = receiptReference(output, existsSync(complete) ? complete : completeSingle);
        fixtureResult.affected = receiptReference(output, existsSync(affected) ? affected : affectedSingle);
      }
      fixtures.push(fixtureResult);
      if (fixtureResult.status !== "succeeded") throw new SdlcError("CONSUMER_QUALIFICATION_FAILED", fixtureResult.reason ?? `consumer fixture failed: ${consumer.id}`);
    }
  } catch (error) {
    reason = error instanceof Error ? error.message : String(error);
  }
  const result: ConsumerQualificationReceipt = {
    schema: "tc.sdlc/consumer-qualification/v1",
    status: reason === null ? "succeeded" : "failed",
    reason,
    manifestDigest,
    catalogueDigest,
    package: packageInfo,
    executableDigest: packageDigest(options.executablePath),
    environment,
    fixtures,
  };
  assertSchema<ConsumerQualificationReceipt>(
    "consumer-qualification-v1.schema.json",
    result,
    "consumer qualification receipt",
  );
  writeCanonicalEvidence(receipt, result);
  return result;
}
