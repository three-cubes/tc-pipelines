import { createHash } from "node:crypto";
import {
  chmodSync,
  copyFileSync,
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { basename, dirname, relative, resolve, sep } from "node:path";

import { canonicalJson, digest } from "../canonical.js";
import { SdlcError } from "../errors.js";
import { writeCanonicalEvidence } from "../evidence/index.js";
import { evaluationCandidate } from "../evidence/signing.js";
import type {
  EvaluationCandidate,
  EvaluationReceipt,
} from "../evidence/task4.js";
import { snapshotFiles } from "../inputs/index.js";

function safe(root: string, path: string): string {
  const absolute = resolve(root, path);
  const value = relative(resolve(root), absolute);
  if (value === ".." || value.startsWith(`..${sep}`)) {
    throw new SdlcError("CACHE_PATH_INVALID", `cache path escapes root: ${path}`);
  }
  return absolute;
}

function reusable(receipt: EvaluationReceipt): void {
  if (
    receipt.status !== "succeeded" ||
    receipt.scheduler?.status !== "succeeded" ||
    receipt.tasks.length === 0 ||
    receipt.tasks.some(
      (task) =>
        task.mode !== "evaluate" ||
        task.trustBoundary !== "portable" ||
        task.outputs.length === 0,
    ) ||
    receipt.tasks.some((task) =>
      task.outputs.some((output) => output.symlink !== null && output.symlink !== undefined),
    )
  ) {
    throw new SdlcError("CACHE_ENTRY_INVALID", "only succeeded portable evaluate tasks with outputs are cacheable");
  }
}

function receiptOutputs(receipt: EvaluationReceipt) {
  const outputs = new Map<string, EvaluationReceipt["tasks"][number]["outputs"][number]>();
  for (const output of receipt.tasks.flatMap((task) => task.outputs)) {
    const existing = outputs.get(output.path);
    if (existing !== undefined && canonicalJson(existing) !== canonicalJson(output)) {
      throw new SdlcError("CACHE_ENTRY_INVALID", `conflicting output evidence: ${output.path}`);
    }
    outputs.set(output.path, output);
  }
  return [...outputs.values()].sort((left, right) => left.path.localeCompare(right.path));
}

type VerifiedOutput = Readonly<{
  path: string;
  mode: number;
  bytes: Buffer;
}>;

function stageVerifiedOutputs(
  cacheRoot: string,
  filesRoot: string,
  expected: ReturnType<typeof receiptOutputs>,
): Readonly<{ directory: string; outputs: readonly VerifiedOutput[] }> {
  const current = snapshotFiles(filesRoot);
  if (canonicalJson(current) !== canonicalJson(expected)) {
    throw new SdlcError(
      "CACHE_CORRUPT",
      "cached output content or metadata is corrupt",
    );
  }
  const directory = mkdtempSync(resolve(cacheRoot, ".tc-sdlc-restore-"));
  chmodSync(directory, 0o700);
  try {
    for (const output of expected) {
      const target = safe(directory, output.path);
      mkdirSync(dirname(target), { recursive: true });
      copyFileSync(safe(filesRoot, output.path), target);
      chmodSync(target, output.mode ?? 0o644);
    }
    const outputs = expected.map((output): VerifiedOutput => {
      const path = safe(directory, output.path);
      const stat = lstatSync(path);
      if (!stat.isFile() || stat.isSymbolicLink()) {
        throw new SdlcError(
          "CACHE_CORRUPT",
          `staged cache output is not a regular file: ${output.path}`,
        );
      }
      const bytes = readFileSync(path);
      const observed = {
        path: output.path,
        digest: `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
        mode: stat.mode & 0o777,
        symlink: null,
      };
      if (canonicalJson(observed) !== canonicalJson(output)) {
        throw new SdlcError("CACHE_CORRUPT", "staged output content or metadata is corrupt");
      }
      return { path: output.path, mode: observed.mode, bytes };
    });
    return { directory, outputs };
  } catch (error) {
    rmSync(directory, { recursive: true, force: true });
    throw error;
  }
}

function publishVerifiedOutputs(
  root: string,
  outputs: readonly VerifiedOutput[],
): void {
  const nonce = `${process.pid}-${Date.now()}`;
  const publications: Array<{
    target: string;
    temporary: string;
    backup: string;
    backupMoved: boolean;
    outputMoved: boolean;
  }> = [];
  try {
    for (const [index, output] of outputs.entries()) {
      const target = safe(root, output.path);
      mkdirSync(dirname(target), { recursive: true });
      if (existsSync(target) && lstatSync(target).isDirectory()) {
        throw new SdlcError(
          "CACHE_PATH_INVALID",
          `cache output target is a directory: ${output.path}`,
        );
      }
      const temporary = resolve(
        dirname(target),
        `.${basename(target)}.tc-sdlc-${nonce}-${index}.tmp`,
      );
      const publication = {
        target,
        temporary,
        backup: `${temporary}.backup`,
        backupMoved: false,
        outputMoved: false,
      };
      publications.push(publication);
      writeFileSync(temporary, output.bytes, { flag: "wx", mode: output.mode });
      chmodSync(temporary, output.mode);
    }
    for (const publication of publications) {
      if (existsSync(publication.target)) {
        renameSync(publication.target, publication.backup);
        publication.backupMoved = true;
      }
      renameSync(publication.temporary, publication.target);
      publication.outputMoved = true;
    }
    for (const publication of publications) {
      if (publication.backupMoved) {
        rmSync(publication.backup, { force: true });
      }
    }
  } catch (error) {
    for (const publication of [...publications].reverse()) {
      if (publication.outputMoved) {
        rmSync(publication.target, { force: true });
      }
      if (publication.backupMoved && existsSync(publication.backup)) {
        renameSync(publication.backup, publication.target);
      }
    }
    throw error;
  } finally {
    for (const publication of publications) {
      rmSync(publication.temporary, { force: true });
      rmSync(publication.backup, { force: true });
    }
  }
}

export function storeEvaluationCache(
  root: string,
  cacheRoot: string,
  receipt: EvaluationReceipt,
): Readonly<{ key: string }> {
  reusable(receipt);
  const candidate = evaluationCandidate(receipt);
  const key = digest(candidate).slice("sha256:".length);
  const entry = safe(cacheRoot, key);
  const files = resolve(entry, "files");
  mkdirSync(files, { recursive: true });
  const current = new Map(snapshotFiles(root).map((file) => [file.path, file]));
  for (const output of receiptOutputs(receipt)) {
    if (canonicalJson(current.get(output.path)) !== canonicalJson(output)) {
      throw new SdlcError(
        "CACHE_OUTPUT_MISMATCH",
        `output no longer matches evaluation evidence: ${output.path}`,
      );
    }
    const source = safe(root, output.path);
    const target = safe(files, output.path);
    mkdirSync(dirname(target), { recursive: true });
    copyFileSync(source, target);
    chmodSync(target, output.mode ?? 0o644);
  }
  writeCanonicalEvidence(resolve(entry, "manifest.json"), { candidate, receipt });
  return { key };
}

export function restoreEvaluationCache(
  root: string,
  cacheRoot: string,
  key: string,
  candidate: EvaluationCandidate,
): true {
  if (!/^[a-f0-9]{64}$/.test(key)) {
    throw new SdlcError("CACHE_PATH_INVALID", "cache key is not canonical SHA-256");
  }
  const entry = safe(cacheRoot, key);
  const manifest = JSON.parse(readFileSync(resolve(entry, "manifest.json"), "utf8")) as {
    candidate: EvaluationCandidate;
    receipt: EvaluationReceipt;
  };
  if (canonicalJson(manifest.candidate) !== canonicalJson(candidate)) {
    throw new SdlcError("CACHE_CANDIDATE_MISMATCH", "cache entry does not match candidate");
  }
  if (
    canonicalJson(evaluationCandidate(manifest.receipt)) !==
    canonicalJson(manifest.candidate)
  ) {
    throw new SdlcError(
      "CACHE_CANDIDATE_MISMATCH",
      "cache manifest candidate does not match its evaluation receipt",
    );
  }
  reusable(manifest.receipt);
  const filesRoot = resolve(entry, "files");
  const expected = receiptOutputs(manifest.receipt);
  const staged = stageVerifiedOutputs(cacheRoot, filesRoot, expected);
  try {
    publishVerifiedOutputs(root, staged.outputs);
  } finally {
    rmSync(staged.directory, { recursive: true, force: true });
  }
  return true;
}
