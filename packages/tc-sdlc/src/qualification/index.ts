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
import { fileURLToPath } from "node:url";

import { parse } from "yaml";

import { bytesDigest, canonicalJson, digest } from "../canonical.js";
import { loadCatalogue } from "../catalogue/index.js";
import { SdlcError } from "../errors.js";
import { writeCanonicalEvidence } from "../evidence/index.js";
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
  package: Readonly<{ name: "@three-cubes/tc-sdlc"; version: string }>;
  executableDigest: string;
  environment: Readonly<{ class: string; platform: string; architecture: string }>;
  fixtures: readonly Readonly<FixtureQualification>[];
}>;

export type QualifyConsumersOptions = Readonly<{
  manifestPath: string;
  outputDirectory: string;
  receiptPath: string;
  executablePath: string;
}>;

function sha256File(path: string): string {
  return `sha256:${createHash("sha256").update(readFileSync(path)).digest("hex")}`;
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
      if (name === ".git") {
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

function packagedCataloguePath(): string {
  return fileURLToPath(new URL("../release/catalogue.json", import.meta.url));
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
  if (consumerIds.includes(relativeReceipt) || relativeReceipt === ".state") {
    throw new SdlcError("CONSUMER_QUALIFICATION_PATH_INVALID", "outer receipt path collides with reserved qualification namespace");
  }
}

function emptyReference(): ReceiptReference {
  return { path: null, digest: null, status: null, taskIdentities: [] };
}

function emptyPreparationReference(): PreparationReference {
  return { ...emptyReference(), firstPassTaskIdentities: [], secondPassTaskIdentities: [] };
}

function receiptValue(path: string, schema: string): Record<string, unknown> {
  let value: unknown;
  try {
    value = JSON.parse(readFileSync(path, "utf8"));
  } catch {
    throw new SdlcError("CONSUMER_RECEIPT_INVALID", `nested ${schema} receipt is unreadable`);
  }
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    (value as Record<string, unknown>).schema !== schema
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

function assertBoundReceipt(
  receipt: Record<string, unknown>,
  expected: Readonly<{ declarationDigest: string; catalogueDigest: string; lockDigest: string }>,
): void {
  if (
    receipt.declarationDigest !== expected.declarationDigest ||
    receipt.catalogueDigest !== expected.catalogueDigest ||
    receipt.lockDigest !== expected.lockDigest
  ) {
    throw new SdlcError("CONSUMER_RECEIPT_INVALID", "nested receipt is not bound to the copied consumer declaration, catalogue and lock");
  }
}

function receiptReference(output: string, path: string, taskIdentities: readonly string[] = []): ReceiptReference {
  if (!existsSync(path)) return emptyReference();
  let value: { status?: unknown; taskIdentities?: unknown; tasks?: unknown; scheduler?: { selection?: unknown } };
  try {
    value = JSON.parse(readFileSync(path, "utf8")) as typeof value;
  } catch {
    return { path: ownRelative(output, path), digest: sha256File(path), status: null, taskIdentities: [] };
  }
  const identities = taskIdentities.length > 0
    ? [...taskIdentities].sort()
    : Array.isArray(value.taskIdentities)
      ? value.taskIdentities.filter((entry): entry is string => typeof entry === "string").sort()
      : Array.isArray(value.tasks)
        ? value.tasks.map((entry) => (entry as { identity?: unknown }).identity).filter((entry): entry is string => typeof entry === "string").sort()
        : Array.isArray(value.scheduler?.selection)
          ? value.scheduler.selection.filter((entry): entry is string => typeof entry === "string").sort()
          : [];
  return { path: ownRelative(output, path), digest: sha256File(path), status: typeof value.status === "string" ? value.status : null, taskIdentities: identities };
}

function preparationReference(output: string, path: string): PreparationReference {
  const reference = receiptReference(output, path);
  if (!existsSync(path)) return emptyPreparationReference();
  try {
    const value = receiptValue(path, "tc.sdlc/preparation-receipt/v1") as {
      firstPass?: { scheduler?: { selection?: unknown } };
      secondPass?: { scheduler?: { selection?: unknown } };
    };
    const identities = (selection: unknown): readonly string[] =>
      Array.isArray(selection)
        ? selection.filter((entry): entry is string => typeof entry === "string").sort()
        : [];
    return {
      ...reference,
      firstPassTaskIdentities: identities(value.firstPass?.scheduler?.selection),
      secondPassTaskIdentities: identities(value.secondPass?.scheduler?.selection),
    };
  } catch {
    return { ...reference, firstPassTaskIdentities: [], secondPassTaskIdentities: [] };
  }
}

function receiptTaskKeys(path: string): readonly string[] {
  if (!existsSync(path)) return [];
  const value = JSON.parse(readFileSync(path, "utf8")) as { tasks?: unknown };
  if (!Array.isArray(value.tasks)) return [];
  return value.tasks
    .map((entry) => (entry as { key?: unknown }).key)
    .filter((entry): entry is string => typeof entry === "string")
    .sort();
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
  let reason: string | null = null;
  try {
    const authorityPath = packagedCataloguePath();
    const authority = loadCatalogue(authorityPath);
    if (authority.release.package.version !== packageInfo.version) {
      throw new SdlcError("CONSUMER_QUALIFICATION_INTERNAL", "packed package version does not match its release catalogue authority");
    }
    packageInfo = authority.release.package;
    const manifest = loadManifest(options.manifestPath);
    reserveOuterReceipt(output, receipt, manifest.consumers.map((consumer) => consumer.id));
    manifestDigest = sha256File(options.manifestPath);
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
        runPublic(options.executablePath, ["catalogue", "--input", authorityPath, "--output", catalogue]);
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
        if (bootstrapReceipt.lockDigest !== bindings.lockDigest || bootstrapReceipt.release !== copiedCatalogue.release.version) {
          throw new SdlcError("CONSUMER_RECEIPT_INVALID", "bootstrap receipt is not bound to the copied consumer lock and release");
        }
        appendChange(checkout, consumer.changed);
        runPublic(options.executablePath, ["prepare", "--declaration", join(checkout, "sdlc.yaml"), "--catalogue", catalogue, "--lock", lock, "--root", checkout, "--state-root", state, "--bootstrap-receipt", bootstrap, "--receipt", preparation]);
        const preparationReceipt = requireSucceededReceipt(preparation, "tc.sdlc/preparation-receipt/v1");
        assertBoundReceipt(preparationReceipt, bindings);
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
        const completeReceipt = requireSucceededReceipt(complete, "tc.sdlc/evaluation-receipt/v1");
        const affectedReceipt = requireSucceededReceipt(affected, "tc.sdlc/evaluation-receipt/v1");
        assertBoundReceipt(completeReceipt, bindings);
        assertBoundReceipt(affectedReceipt, bindings);
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
    package: packageInfo,
    executableDigest: sha256File(options.executablePath),
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
