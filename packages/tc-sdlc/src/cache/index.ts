import {
  chmodSync,
  copyFileSync,
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { dirname, relative, resolve, sep } from "node:path";

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
  reusable(manifest.receipt);
  const filesRoot = resolve(entry, "files");
  const expected = receiptOutputs(manifest.receipt);
  const actual = snapshotFiles(filesRoot);
  if (canonicalJson(actual) !== canonicalJson(expected)) {
    throw new SdlcError("CACHE_CORRUPT", "cached output content or metadata is corrupt");
  }
  for (const output of expected) {
    const source = safe(filesRoot, output.path);
    const target = safe(root, output.path);
    mkdirSync(dirname(target), { recursive: true });
    if (existsSync(target) && lstatSync(target).isSymbolicLink()) {
      rmSync(target);
    }
    copyFileSync(source, target);
    chmodSync(target, output.mode ?? 0o644);
  }
  return true;
}
