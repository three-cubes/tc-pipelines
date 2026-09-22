import {
  closeSync,
  fsyncSync,
  openSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { dirname } from "node:path";

import { canonicalJson } from "../canonical.js";

export type RunStatus = "succeeded" | "failed" | "stalled" | "cancelled";
export type TaskRunStatus = RunStatus | "skipped";

export type RunEvent = Readonly<{
  taskKey: string;
  taskIdentity: string;
  type: "start" | "heartbeat" | "output" | "cancellation" | "terminal";
  stream?: "stdout" | "stderr";
  text?: string;
  status?: TaskRunStatus;
  reason?: string;
}>;

export type ProcessSample = Readonly<{
  pid: number;
  parentPid: number;
  state: string;
  elapsed: string;
  cpuPercent: number;
  residentMemoryKiB: number;
}>;

export type ProcessDiagnostic = Readonly<{
  pid: number;
  running: boolean;
  cpu: number;
  memoryMiB: number;
  ports: readonly number[];
  exclusive: readonly string[];
  stdoutBytes: number;
  stderrBytes: number;
  processes: readonly ProcessSample[];
}>;

export type TaskReceipt = Readonly<{
  key: string;
  identity: string;
  status: TaskRunStatus;
  exitCode: number | null;
  reason: string | null;
  stdout: string;
  stderr: string;
  outputTruncated: boolean;
  events: readonly RunEvent[];
  diagnostic?: ProcessDiagnostic;
}>;

export type RunReceipt = Readonly<{
  schema: "tc.sdlc/run-receipt/v1";
  declarationDigest: string;
  lockDigest: string;
  selection: readonly string[];
  status: RunStatus;
  tasks: readonly TaskReceipt[];
}>;

export function serialiseRunReceipt(receipt: RunReceipt): string {
  return canonicalJson(receipt);
}

export function writeRunReceipt(path: string, receipt: RunReceipt): void {
  writeCanonicalEvidence(path, receipt);
}

export function writeCanonicalEvidence(path: string, value: unknown): void {
  const temporary = `${path}.tmp-${process.pid}`;
  try {
    writeFileSync(temporary, canonicalJson(value), { mode: 0o600 });
    const descriptor = openSync(temporary, "r");
    try {
      fsyncSync(descriptor);
    } finally {
      closeSync(descriptor);
    }
    renameSync(temporary, path);
    if (process.platform !== "win32") {
      const directory = openSync(dirname(path), "r");
      try {
        fsyncSync(directory);
      } finally {
        closeSync(directory);
      }
    }
  } catch (error) {
    try {
      unlinkSync(temporary);
    } catch {
      // The temporary was never created or the atomic rename already consumed it.
    }
    throw error;
  }
}
