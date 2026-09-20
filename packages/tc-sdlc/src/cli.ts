#!/usr/bin/env node

import { readFileSync } from "node:fs";

import { bytesDigest, canonicalJson } from "./canonical.js";
import { loadCatalogue } from "./catalogue/index.js";
import { SdlcError } from "./errors.js";
import type { PreparationReceipt } from "./evidence/task4.js";
import { assertCurrentLock, loadLock, resolveLock, writeLock } from "./lock/index.js";
import { loadDeclaration } from "./schema/declaration.js";
import { check, checkAll } from "./tasks/check.js";
import { prepare } from "./tasks/prepare.js";

type Command = "lock" | "validate" | "prepare" | "check" | "check-all";

function parseOptions(args: readonly string[], required: readonly string[]): Record<string, string> {
  const options: Record<string, string> = {};
  for (let index = 0; index < args.length; index += 2) {
    const flag = args[index];
    const value = args[index + 1];
    if (flag === undefined || !flag.startsWith("--") || value === undefined) {
      throw new SdlcError("USAGE", "options must be provided as --name value pairs");
    }
    const name = flag.slice(2);
    if (!required.includes(name) || options[name] !== undefined) {
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

async function run(command: Command, args: readonly string[]): Promise<void> {
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

  const required = ["declaration", "catalogue", "lock", "root", "receipt"];
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
  const preparationReceipt =
    command === "prepare"
      ? undefined
      : (JSON.parse(
          readFileSync(options["preparation-receipt"]!, "utf8"),
        ) as PreparationReceipt);
  const receipt =
    command === "prepare"
      ? await prepare({
          root: options.root!,
          declaration,
          catalogue,
          lock: loaded.lock,
          receiptPath: options.receipt!,
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
          });
  if (receipt.status !== "succeeded") {
    throw new SdlcError("TASK_FAILED", `${command} failed: ${receipt.reason}`);
  }
  success(command, { receipt: options.receipt, receiptSchema: receipt.schema });
}

const rawCommand = process.argv[2];
const commands: readonly Command[] = ["lock", "validate", "prepare", "check", "check-all"];
const envelopeCommand = commands.includes(rawCommand as Command) ? rawCommand : "unknown";

try {
  if (!commands.includes(rawCommand as Command)) {
    throw new SdlcError("USAGE", "command must be lock, validate, prepare, check or check-all");
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
