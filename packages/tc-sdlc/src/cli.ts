#!/usr/bin/env node

import { readFileSync } from "node:fs";

import { bootstrap } from "./bootstrap/index.js";
import { loadBootstrapExecutionContext } from "./bootstrap/context.js";
import { bytesDigest, canonicalJson } from "./canonical.js";
import {
  generateReleaseCatalogue,
  loadCatalogue,
  writeReleaseCatalogue,
} from "./catalogue/index.js";
import { SdlcError } from "./errors.js";
import {
  preflightFitnessReceipt,
  unavailableFitnessReceipt,
  writeFitnessReceipt,
} from "./executors/fitness.js";
import type { PreparationReceipt } from "./evidence/task4.js";
import { assertCurrentLock, loadLock, resolveLock, writeLock } from "./lock/index.js";
import { maintain } from "./maintenance/index.js";
import { loadDeclaration } from "./schema/declaration.js";
import { check, checkAll } from "./tasks/check.js";
import { prepare } from "./tasks/prepare.js";
import { fitness } from "./tasks/fitness.js";

type Command =
  | "catalogue"
  | "lock"
  | "validate"
  | "bootstrap"
  | "maintain"
  | "prepare"
  | "check"
  | "check-all"
  | "fitness";

function parseOptions(
  args: readonly string[],
  required: readonly string[],
  optional: readonly string[] = [],
): Record<string, string> {
  const options: Record<string, string> = {};
  for (let index = 0; index < args.length; index += 2) {
    const flag = args[index];
    const value = args[index + 1];
    if (flag === undefined || !flag.startsWith("--") || value === undefined) {
      throw new SdlcError("USAGE", "options must be provided as --name value pairs");
    }
    const name = flag.slice(2);
    if ((!required.includes(name) && !optional.includes(name)) || options[name] !== undefined) {
      throw new SdlcError("USAGE", `unknown or repeated option ${flag}`);
    }
    options[name] = value;
  }
  for (const name of required) {
    if (options[name] === undefined) {
      throw new SdlcError("USAGE", `missing required option --${name}`);
    }
  }
  return options;
}

function success(command: Command, payload: Record<string, unknown>): void {
  process.stdout.write(
    `${JSON.stringify({
      schema: "tc.sdlc/command-result/v1",
      command,
      status: "ok",
      ...payload,
    })}\n`,
  );
}

function requestedReceipt(args: readonly string[]): string | undefined {
  const index = args.indexOf("--receipt");
  return index === -1 ? undefined : args[index + 1];
}

async function run(command: Command, args: readonly string[]): Promise<void> {
  if (command === "maintain") {
    const options = parseOptions(
      args,
      ["state-root", "receipt", "mode"],
      [
        "temporary-root",
        "retention-hours",
        "cleanup-workers",
        "cleanup-worker-ms",
        "uv",
        "pnpm",
        "buildx",
        "docker-builder",
      ],
    );
    if (options.mode !== "dry-run" && options.mode !== "apply") {
      throw new SdlcError("USAGE", "--mode must be dry-run or apply");
    }
    const retentionHours =
      options["retention-hours"] === undefined
        ? undefined
        : Number(options["retention-hours"]);
    const cleanupWorkers =
      options["cleanup-workers"] === undefined
        ? undefined
        : Number(options["cleanup-workers"]);
    const cleanupWorkerMs =
      options["cleanup-worker-ms"] === undefined
        ? undefined
        : Number(options["cleanup-worker-ms"]);
    const receipt = await maintain({
      stateRoot: options["state-root"]!,
      receiptPath: options.receipt!,
      mode: options.mode,
      ...(options["temporary-root"] === undefined
        ? {}
        : { temporaryRoot: options["temporary-root"] }),
      ...(retentionHours === undefined ? {} : { retentionHours }),
      ...(cleanupWorkers === undefined ? {} : { cleanupWorkers }),
      ...(cleanupWorkerMs === undefined ? {} : { cleanupWorkerMs }),
      ...(options.uv === undefined ? {} : { uvExecutable: options.uv }),
      ...(options.pnpm === undefined ? {} : { pnpmExecutable: options.pnpm }),
      ...(options.buildx === undefined ? {} : { buildxExecutable: options.buildx }),
      ...(options["docker-builder"] === undefined
        ? {}
        : { dockerBuilder: options["docker-builder"] }),
    });
    if (receipt.status !== "succeeded") {
      throw new SdlcError("MAINTENANCE_FAILED", `maintenance failed: ${receipt.reason}`);
    }
    success(command, {
      receipt: options.receipt,
      receiptSchema: receipt.schema,
      candidateCount: receipt.candidateCount,
      removedCount: receipt.removedCount,
      reclaimedBytes: receipt.reclaimedBytes,
      cleanupWorkers: receipt.cleanupWorkers,
      cleanupWorkerMs: receipt.cleanupWorkerMs,
      cleanupFailures: receipt.cleanupFailures,
    });
    return;
  }

  if (command === "catalogue") {
    const options = parseOptions(args, [
      "version",
      "fitness-version",
      "workflow-commit",
      "image-digest",
      "output",
    ]);
    const catalogue = generateReleaseCatalogue({
      releaseVersion: options.version!,
      fitnessVersion: options["fitness-version"]!,
      workflowCommit: options["workflow-commit"]!,
      imageDigest: options["image-digest"]!,
    });
    writeReleaseCatalogue(options.output!, catalogue);
    success(command, {
      release: catalogue.release.version,
      catalogueDigest: bytesDigest(canonicalJson(catalogue)),
      output: options.output,
    });
    return;
  }

  if (command === "lock") {
    const options = parseOptions(args, ["declaration", "catalogue", "output"]);
    const declaration = loadDeclaration(options.declaration!);
    const catalogue = loadCatalogue(options.catalogue!);
    const lock = resolveLock(declaration, catalogue);
    writeLock(options.output!, lock);
    const lockBytes = canonicalJson(lock);
    success(command, {
      release: lock.release,
      declarationDigest: lock.declarationDigest,
      catalogueDigest: lock.catalogueDigest,
      lockDigest: bytesDigest(lockBytes),
    });
    return;
  }

  if (command === "validate") {
    const options = parseOptions(args, ["declaration", "catalogue", "lock"]);
    const declaration = loadDeclaration(options.declaration!);
    const catalogue = loadCatalogue(options.catalogue!);
    const loaded = loadLock(options.lock!);
    assertCurrentLock(loaded.lock, declaration, catalogue);
    success(command, {
      release: loaded.lock.release,
      declarationDigest: loaded.lock.declarationDigest,
      catalogueDigest: loaded.lock.catalogueDigest,
      lockDigest: bytesDigest(loaded.bytes),
    });
    return;
  }

  if (command === "bootstrap") {
    const options = parseOptions(
      args,
      ["declaration", "catalogue", "lock", "root", "state-root", "receipt"],
      ["offline", "max-diagnostics"],
    );
    const declaration = loadDeclaration(options.declaration!);
    const catalogue = loadCatalogue(options.catalogue!);
    const loaded = loadLock(options.lock!);
    const offline = options.offline === undefined ? false : options.offline === "true";
    if (options.offline !== undefined && options.offline !== "true" && options.offline !== "false") {
      throw new SdlcError("USAGE", "--offline must be true or false");
    }
    const maxDiagnostics =
      options["max-diagnostics"] === undefined
        ? undefined
        : Number(options["max-diagnostics"]);
    const receipt = await bootstrap({
      root: options.root!,
      stateRoot: options["state-root"]!,
      declaration,
      catalogue,
      lock: loaded.lock,
      receiptPath: options.receipt!,
      host: { offline },
      ...(maxDiagnostics === undefined ? {} : { maxDiagnostics }),
    });
    if (receipt.status !== "succeeded") {
      throw new SdlcError("BOOTSTRAP_FAILED", `bootstrap failed: ${receipt.reason}`);
    }
    success(command, {
      receipt: options.receipt,
      receiptSchema: receipt.schema,
      release: receipt.release,
      lockDigest: receipt.lockDigest,
      reused: receipt.reused,
    });
    return;
  }

  if (command === "fitness") {
    let options: Record<string, string>;
    try {
      options = parseOptions(args, ["declaration", "catalogue", "lock", "root", "state-root", "bootstrap-receipt", "receipt"]);
    } catch (error) {
      const receipt = requestedReceipt(args);
      if (receipt !== undefined) writeFitnessReceipt(receipt, preflightFitnessReceipt("fitness_input_invalid"));
      throw error;
    }
    let declaration;
    let catalogue;
    let loaded;
    try {
      declaration = loadDeclaration(options.declaration!);
      catalogue = loadCatalogue(options.catalogue!);
      loaded = loadLock(options.lock!);
    } catch (error) {
      writeFitnessReceipt(options.receipt!, preflightFitnessReceipt("fitness_input_invalid"));
      throw error;
    }
    try {
      assertCurrentLock(loaded.lock, declaration, catalogue);
    } catch (error) {
      writeFitnessReceipt(
        options.receipt!,
        unavailableFitnessReceipt(
          declaration,
          catalogue,
          loaded.lock,
          options.root!,
          "fitness_lock_invalid",
        ),
      );
      throw error;
    }
    let executionContext;
    try {
      executionContext = loadBootstrapExecutionContext(
        options["bootstrap-receipt"]!,
        options["state-root"]!,
        loaded.lock,
        catalogue,
      );
    } catch (error) {
      writeFitnessReceipt(
        options.receipt!,
        unavailableFitnessReceipt(
          declaration,
          catalogue,
          loaded.lock,
          options.root!,
          "fitness_bootstrap_context_invalid",
        ),
      );
      throw new SdlcError(
        "FITNESS_BOOTSTRAP_CONTEXT_INVALID",
        error instanceof Error ? error.message : "fitness bootstrap context is unavailable",
      );
    }
    try {
      const receipt = await fitness({
        root: options.root!,
        declaration,
        catalogue,
        lock: loaded.lock,
        receiptPath: options.receipt!,
        runOptions: { executionContext },
      });
      success(command, { receipt: options.receipt, receiptSchema: receipt.schema });
    } finally {
      executionContext.lease.release();
    }
    return;
  }

  const required = ["declaration", "catalogue", "lock", "root", "receipt"];
  required.push("bootstrap-receipt", "state-root");
  if (command === "check") {
    required.push("changed", "environment", "producer", "preparation-receipt");
  } else if (command === "check-all") {
    required.push("environment", "producer", "preparation-receipt");
  }
  const options = parseOptions(args, required);
  const declaration = loadDeclaration(options.declaration!);
  const catalogue = loadCatalogue(options.catalogue!);
  const loaded = loadLock(options.lock!);
  assertCurrentLock(loaded.lock, declaration, catalogue);
  const executionContext = loadBootstrapExecutionContext(
    options["bootstrap-receipt"]!,
    options["state-root"]!,
    loaded.lock,
    catalogue,
  );
  const preparationReceipt =
    command === "prepare"
      ? undefined
      : (JSON.parse(
          readFileSync(options["preparation-receipt"]!, "utf8"),
        ) as PreparationReceipt);
  const receipt = await (async () => {
    try {
      return command === "prepare"
        ? await prepare({
            root: options.root!,
            declaration,
            catalogue,
            lock: loaded.lock,
            receiptPath: options.receipt!,
            runOptions: { executionContext },
          })
        : command === "check"
          ? await check({
              root: options.root!,
              declaration,
              catalogue,
              lock: loaded.lock,
              receiptPath: options.receipt!,
              changedPaths: options.changed!.split(",").filter(Boolean),
              environmentClass: options.environment!,
              producer: options.producer!,
              preparationReceipt,
              runOptions: { executionContext },
            })
          : await checkAll({
              root: options.root!,
              declaration,
              catalogue,
              lock: loaded.lock,
              receiptPath: options.receipt!,
              environmentClass: options.environment!,
              producer: options.producer!,
              preparationReceipt,
              runOptions: { executionContext },
            });
    } finally {
      executionContext.lease.release();
    }
  })();
  if (receipt.status !== "succeeded") {
    throw new SdlcError("TASK_FAILED", `${command} failed: ${receipt.reason}`);
  }
  success(command, { receipt: options.receipt, receiptSchema: receipt.schema });
}

const rawCommand = process.argv[2];
const commands: readonly Command[] = [
  "catalogue",
  "lock",
  "validate",
  "bootstrap",
  "maintain",
  "prepare",
  "check",
  "check-all",
  "fitness",
];
const envelopeCommand = commands.includes(rawCommand as Command) ? rawCommand : "unknown";

try {
  if (!commands.includes(rawCommand as Command)) {
    throw new SdlcError(
      "USAGE",
      "command must be catalogue, lock, validate, bootstrap, maintain, prepare, check, check-all or fitness",
    );
  }
  await run(rawCommand as Command, process.argv.slice(3));
} catch (error) {
  const code = error instanceof SdlcError ? error.code : "INTERNAL_ERROR";
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(
    `${JSON.stringify({
      schema: "tc.sdlc/command-error/v1",
      command: envelopeCommand,
      status: "error",
      error: { code, message },
    })}\n`,
  );
  process.exitCode = 1;
}
