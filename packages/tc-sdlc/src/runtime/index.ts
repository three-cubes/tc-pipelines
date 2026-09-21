import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { availableParallelism, tmpdir, totalmem } from "node:os";
import { basename, dirname, join, posix, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
  type RunEvent,
  type ProcessDiagnostic,
  type ProcessSample,
  type RunReceipt,
  type RunStatus,
  type TaskReceipt,
  type TaskReceiptEvidence,
  writeCanonicalEvidence,
  writeRunReceipt,
} from "../evidence/index.js";
import type { BootstrapExecutionContext } from "../bootstrap/index.js";
import { digest } from "../canonical.js";
import { SdlcError } from "../errors.js";
import type {
  GraphTask,
  SdlcGraph,
  TaskEvidenceDeclaration,
  TaskIdentity,
} from "../schema/types.js";
import {
  finaliseFitnessReceipt,
  fitnessFailureReceipt,
  prepareFitnessExecution,
  writeFitnessReceipt,
  type FitnessExecution,
} from "../executors/fitness.js";

export type HostCapacity = Readonly<{
  cpu: number;
  memoryMiB: number;
}>;

export type HostCapacityInputs = Readonly<{
  logicalCpu: number;
  totalMemoryBytes: number;
  cgroupV2CpuMax?: string;
  cgroupV2MemoryMax?: string;
  cgroupV1CpuQuotaMicros?: number;
  cgroupV1CpuPeriodMicros?: number;
  cgroupV1MemoryLimitBytes?: number;
}>;

export type RunOptions = Readonly<{
  cwd: string;
  receiptPath: string;
  capacity?: HostCapacity;
  signal?: AbortSignal;
  environment?: Readonly<Record<string, string>>;
  executionContext: BootstrapExecutionContext;
  redactions?: readonly string[];
  maxOutputBytes?: number;
  terminationGraceMs?: number;
  onEvent?: (event: RunEvent) => void;
}>;

function fileText(path: string): string | undefined {
  try {
    return readFileSync(path, "utf8").trim();
  } catch {
    return undefined;
  }
}

function numberValue(value: string | undefined): number | undefined {
  if (value === undefined) {
    return undefined;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export function resolveHostCapacity(input: HostCapacityInputs): HostCapacity {
  if (!(input.logicalCpu > 0) || !(input.totalMemoryBytes > 0)) {
    throw new SdlcError(
      "RUN_CAPACITY_INVALID",
      "detected logical CPU and memory must be positive",
    );
  }
  let cpu = input.logicalCpu;
  if (input.cgroupV2CpuMax !== undefined) {
    const [quotaValue, periodValue] = input.cgroupV2CpuMax.trim().split(/\s+/);
    if (quotaValue !== "max") {
      const quota = Number(quotaValue);
      const period = Number(periodValue);
      if (quota > 0 && period > 0) {
        cpu = Math.min(cpu, quota / period);
      }
    }
  } else if (
    input.cgroupV1CpuQuotaMicros !== undefined &&
    input.cgroupV1CpuQuotaMicros > 0 &&
    input.cgroupV1CpuPeriodMicros !== undefined &&
    input.cgroupV1CpuPeriodMicros > 0
  ) {
    cpu = Math.min(
      cpu,
      input.cgroupV1CpuQuotaMicros / input.cgroupV1CpuPeriodMicros,
    );
  }
  let memoryBytes = input.totalMemoryBytes;
  const cgroupV2Memory =
    input.cgroupV2MemoryMax === "max"
      ? undefined
      : numberValue(input.cgroupV2MemoryMax);
  const cgroupMemory = cgroupV2Memory ?? input.cgroupV1MemoryLimitBytes;
  if (cgroupMemory !== undefined && cgroupMemory < 2 ** 60) {
    if (cgroupMemory > 0) {
      memoryBytes = Math.min(memoryBytes, cgroupMemory);
    }
  }
  return {
    cpu: Math.max(cpu, 0.001),
    memoryMiB: Math.max(1, Math.floor(memoryBytes / 1024 / 1024)),
  };
}

function detectedCapacity(): HostCapacity {
  return resolveHostCapacity({
    logicalCpu: availableParallelism(),
    totalMemoryBytes: totalmem(),
    cgroupV2CpuMax: fileText("/sys/fs/cgroup/cpu.max"),
    cgroupV2MemoryMax: fileText("/sys/fs/cgroup/memory.max"),
    cgroupV1CpuQuotaMicros: numberValue(
      fileText("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"),
    ),
    cgroupV1CpuPeriodMicros: numberValue(
      fileText("/sys/fs/cgroup/cpu/cpu.cfs_period_us"),
    ),
    cgroupV1MemoryLimitBytes: numberValue(
      fileText("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    ),
  });
}

type Allocation = {
  cpu: number;
  memoryMiB: number;
  ports: Set<number>;
  exclusive: Set<string>;
};

function canAllocate(
  task: GraphTask,
  capacity: HostCapacity,
  allocation: Allocation,
): boolean {
  return (
    allocation.cpu + task.resources.cpu <= capacity.cpu &&
    allocation.memoryMiB + task.resources.memoryMiB <= capacity.memoryMiB &&
    task.resources.ports.every((port) => !allocation.ports.has(port)) &&
    task.resources.exclusive.every(
      (resource) => !allocation.exclusive.has(resource),
    )
  );
}

function impossible(task: GraphTask, capacity: HostCapacity): boolean {
  return (
    task.resources.cpu > capacity.cpu ||
    task.resources.memoryMiB > capacity.memoryMiB
  );
}

function allocate(task: GraphTask, allocation: Allocation, direction: 1 | -1): void {
  allocation.cpu += direction * task.resources.cpu;
  allocation.memoryMiB += direction * task.resources.memoryMiB;
  for (const port of task.resources.ports) {
    if (direction === 1) {
      allocation.ports.add(port);
    } else {
      allocation.ports.delete(port);
    }
  }
  for (const resource of task.resources.exclusive) {
    if (direction === 1) {
      allocation.exclusive.add(resource);
    } else {
      allocation.exclusive.delete(resource);
    }
  }
}

function emit(
  task: GraphTask,
  events: RunEvent[],
  options: RunOptions,
  event: Omit<RunEvent, "taskKey" | "taskIdentity">,
): void {
  const value: RunEvent = {
    taskKey: task.key,
    taskIdentity: task.identity,
    ...event,
  };
  events.push(value);
  if (event.type !== "terminal") options.onEvent?.(value);
}

function terminateProcessGroup(
  child: ReturnType<typeof spawn>,
  graceMs: number,
): void {
  if (child.pid === undefined || child.exitCode !== null) {
    return;
  }
  if (process.platform === "win32") {
    spawn("taskkill", ["/pid", String(child.pid), "/t", "/f"], {
      stdio: "ignore",
    });
    return;
  }
  try {
    process.kill(-child.pid, "SIGTERM");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ESRCH") {
      throw error;
    }
    return;
  }
  setTimeout(() => {
    try {
      process.kill(-(child.pid as number), "SIGKILL");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ESRCH") {
        throw error;
      }
    }
  }, graceMs);
}

function captureProcessGroup(processGroupId: number): readonly ProcessSample[] {
  if (process.platform === "win32" || processGroupId < 1) {
    return [];
  }
  const result = spawnSync(
    "ps",
    ["-ax", "-o", "pid=,ppid=,pgid=,stat=,etime=,pcpu=,rss="],
    {
      encoding: "utf8",
      env: { PATH: process.env.PATH ?? "", LC_ALL: "C" },
      maxBuffer: 128 * 1024,
      timeout: 1_000,
    },
  );
  if (result.status !== 0 || typeof result.stdout !== "string") {
    return [];
  }
  const samples: ProcessSample[] = [];
  for (const line of result.stdout.split("\n")) {
    const [pidValue, parentPidValue, groupValue, state, elapsed, cpu, memory] =
      line.trim().split(/\s+/);
    if (
      groupValue === undefined ||
      Number(groupValue) !== processGroupId ||
      state === undefined ||
      elapsed === undefined ||
      cpu === undefined ||
      memory === undefined
    ) {
      continue;
    }
    const sample = {
      pid: Number(pidValue),
      parentPid: Number(parentPidValue),
      state,
      elapsed,
      cpuPercent: Number(cpu),
      residentMemoryKiB: Number(memory),
    };
    if (
      Object.values(sample).every(
        (value) => typeof value === "string" || Number.isFinite(value),
      )
    ) {
      samples.push(sample);
    }
  }
  return samples.sort((left, right) => left.pid - right.pid);
}

type OutputCapture = {
  pending: string;
  text: string;
  bytes: number;
  truncated: boolean;
};

function utf8Prefix(value: string, maximumBytes: number): string {
  if (Buffer.byteLength(value) <= maximumBytes) {
    return value;
  }
  let end = Math.min(value.length, maximumBytes);
  while (end > 0 && Buffer.byteLength(value.slice(0, end)) > maximumBytes) {
    end -= 1;
  }
  return value.slice(0, end);
}

function redacted(value: string, redactions: readonly string[]): string {
  return redactions.reduce(
    (text, secret) => text.replaceAll(secret, "[REDACTED]"),
    value,
  );
}

function safeBoundary(
  value: string,
  redactions: readonly string[],
): number {
  const longest = redactions.reduce(
    (maximum, secret) => Math.max(maximum, secret.length),
    0,
  );
  let boundary = Math.max(0, value.length - Math.max(0, longest - 1));
  for (const secret of redactions) {
    let offset = value.indexOf(secret);
    while (offset >= 0) {
      if (offset < boundary && offset + secret.length > boundary) {
        boundary = offset;
      }
      offset = value.indexOf(secret, offset + 1);
    }
  }
  return boundary;
}

const ambientToolVariables = /^(?:PATH|HOME|TMPDIR|TMP|TEMP|VIRTUAL_ENV|PYTHONPATH|PYTHONHOME|PYTHONPYCACHEPREFIX|NODE_PATH|NODE_OPTIONS|TC_SDLC_NODE_(?:LAUNCHER|LOADER|MODULES)|PNPM_HOME|PNPM_STORE_DIR|NPM_CONFIG_[A-Z0-9_]*|XDG_[A-Z0-9_]*|UV_[A-Z0-9_]*|COREPACK_[A-Z0-9_]*|CONDA_[A-Z0-9_]*|NVM_DIR)$/;

function taskEnvironment(
  options: RunOptions,
  scratch: string,
): NodeJS.ProcessEnv {
  const forbidden = Object.keys(options.environment ?? {}).find((name) =>
    ambientToolVariables.test(name) ||
    /^(?:TC_SDLC_EXECUTION_CONTEXT_DIGEST|TC_SDLC_BOOTSTRAP_STATE_KEY|TC_SDLC_BOOTSTRAP_STATE_ROOT|TC_SDLC_FITNESS_VERSION|TC_SDLC_TASK_EVIDENCE_DIR)$/.test(name),
  );
  if (forbidden !== undefined) {
    throw new SdlcError(
      "TASK_ENVIRONMENT_INVALID",
      `task environment may not override bootstrap-owned variable ${forbidden}`,
    );
  }
  const inherited: NodeJS.ProcessEnv = {};
  for (const [name, value] of Object.entries(process.env)) {
    if (!ambientToolVariables.test(name) && value !== undefined) {
      inherited[name] = value;
    }
  }
  const isolated = {
    HOME: join(scratch, "home"),
    TMPDIR: join(scratch, "tmp"),
    TMP: join(scratch, "tmp"),
    TEMP: join(scratch, "tmp"),
    XDG_CONFIG_HOME: join(scratch, "home", "config"),
    XDG_CACHE_HOME: join(scratch, "cache", "xdg"),
    XDG_DATA_HOME: join(scratch, "data", "xdg"),
    XDG_STATE_HOME: join(scratch, "state", "xdg"),
    UV_CACHE_DIR: join(scratch, "cache", "uv"),
    PYTHONPYCACHEPREFIX: join(scratch, "cache", "python"),
    PYTHONDONTWRITEBYTECODE: "1",
    COREPACK_HOME: join(scratch, "cache", "corepack"),
    PNPM_HOME: join(scratch, "pnpm"),
    PNPM_STORE_DIR: join(scratch, "cache", "pnpm-store"),
    NPM_CONFIG_CACHE: join(scratch, "cache", "npm"),
    TC_SDLC_TASK_EVIDENCE_DIR: join(scratch, "evidence"),
  };
  for (const path of Object.values(isolated)) {
    mkdirSync(path, { recursive: true, mode: 0o700 });
  }
  const executionEnvironment = options.executionContext.environment;
  const nodeModules = executionEnvironment.TC_SDLC_NODE_MODULES;
  const nodeLoader = join(dirname(fileURLToPath(import.meta.url)), "node-loader.js");
  const nodeLauncher = executionEnvironment.TC_SDLC_NODE_LAUNCHER;
  if (nodeModules !== undefined && (nodeLauncher === undefined || !existsSync(nodeLoader))) {
    throw new SdlcError("TASK_ENVIRONMENT_INVALID", "state-owned Node module resolver is unavailable");
  }
  const nodeBin = join(scratch, "node-bin");
  if (nodeModules !== undefined && nodeLauncher !== undefined) {
    mkdirSync(nodeBin, { recursive: true, mode: 0o700 });
    const wrapper = join(nodeBin, "node");
    writeFileSync(
      wrapper,
      `#!/bin/sh\nexec "$TC_SDLC_NODE_LAUNCHER" --import "$TC_SDLC_NODE_LOADER" "$@"\n`,
      { mode: 0o700 },
    );
  }
  return {
    ...inherited,
    ...options.environment,
    ...executionEnvironment,
    ...isolated,
    ...(nodeModules === undefined
      ? {}
      : {
          PATH: `${nodeBin}:${executionEnvironment.PATH}`,
          TC_SDLC_NODE_LOADER: pathToFileURL(nodeLoader).href,
        }),
  };
}

function taskRedactions(options: RunOptions): readonly string[] {
  const environments = [process.env, options.environment ?? {}, options.executionContext.environment];
  const discovered = environments.flatMap((environment) =>
    Object.entries(environment)
      .filter(([name, value]) => value !== undefined && /(?:secret|token|password|credential|key)/i.test(name))
      .map(([, value]) => value as string),
  );
  return [...new Set([...(options.redactions ?? []), ...discovered])]
    .filter((value) => value.length > 0)
    .sort((left, right) => right.length - left.length);
}

function capturedTaskEvidence(
  directory: string,
  declarations: readonly TaskEvidenceDeclaration[],
  redactions: readonly string[],
): Readonly<{ evidence: readonly TaskReceiptEvidence[]; missing: readonly string[] }> {
  const maximumFileBytes = 2 * 1024 * 1024;
  const maximumTotalBytes = 4 * 1024 * 1024;
  const declared = new Map(declarations.map((item) => [posix.normalize(item.path), item]));
  if (!existsSync(directory)) {
    return { evidence: [], missing: [...declared.keys()].sort() };
  }
  const evidenceRoot = lstatSync(directory);
  if (!evidenceRoot.isDirectory() || evidenceRoot.isSymbolicLink()) {
    throw new SdlcError("TASK_EVIDENCE_INVALID", "task evidence root is not a real directory");
  }
  const found = new Map<string, string>();
  let totalBytes = 0;
  const visit = (current: string, prefix: string): void => {
    for (const name of readdirSync(current).sort()) {
      const path = join(current, name);
      const relativePath = prefix === "" ? name : `${prefix}/${name}`;
      const metadata = lstatSync(path);
      if (metadata.isSymbolicLink()) {
        throw new SdlcError("TASK_EVIDENCE_INVALID", `task evidence may not contain symlinks: ${relativePath}`);
      }
      if (metadata.isDirectory()) {
        visit(path, relativePath);
        continue;
      }
      if (!metadata.isFile() || metadata.size > maximumFileBytes || totalBytes + metadata.size > maximumTotalBytes) {
        throw new SdlcError("TASK_EVIDENCE_INVALID", `task evidence exceeds the retained evidence limit: ${relativePath}`);
      }
      if (!declared.has(posix.normalize(relativePath))) {
        throw new SdlcError("TASK_EVIDENCE_INVALID", `task wrote undeclared evidence: ${relativePath}`);
      }
      found.set(posix.normalize(relativePath), path);
    }
  };
  visit(directory, "");
  const evidence: TaskReceiptEvidence[] = [];
  const missing: string[] = [];
  for (const [relativePath, declaration] of declared) {
    const path = found.get(relativePath);
    if (path === undefined) {
      missing.push(relativePath);
      continue;
    }
    const bytes = readFileSync(path);
    totalBytes += bytes.length;
    if (bytes.length > maximumFileBytes || totalBytes > maximumTotalBytes) {
      throw new SdlcError("TASK_EVIDENCE_INVALID", `task evidence exceeds the retained evidence limit: ${relativePath}`);
    }
    let text: string;
    try {
      text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    } catch {
      throw new SdlcError("TASK_EVIDENCE_INVALID", `task evidence is not valid UTF-8: ${relativePath}`);
    }
    if (declaration.mediaType === "application/json") {
      try {
        JSON.parse(text);
      } catch {
        throw new SdlcError("TASK_EVIDENCE_INVALID", `task evidence is not valid JSON: ${relativePath}`);
      }
    }
    const retained = redacted(text, redactions);
    if (declaration.mediaType === "application/json") {
      try {
        JSON.parse(retained);
      } catch {
        throw new SdlcError("TASK_EVIDENCE_INVALID", `redaction did not preserve JSON evidence: ${relativePath}`);
      }
    }
    const retainedBytes = Buffer.from(retained, "utf8");
    evidence.push({
      path: relativePath,
      sourceDigest: `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
      contentDigest: `sha256:${createHash("sha256").update(retainedBytes).digest("hex")}`,
      mediaType: declaration.mediaType,
      content: retained,
    });
  }
  return { evidence, missing: missing.sort() };
}

async function executeTask(
  task: GraphTask,
  options: RunOptions,
  scratchRoot: string,
  scratchId: string,
): Promise<TaskReceipt> {
  const taskScratch = join(scratchRoot, digest({ identity: task.identity }).slice(7, 31));
  mkdirSync(taskScratch, { recursive: true, mode: 0o700 });
  writeCanonicalEvidence(join(taskScratch, ".tc-sdlc-temporary.json"), {
    schema: "tc.sdlc/temporary-owner/v1",
    owner: "@three-cubes/tc-sdlc",
    kind: "test-run",
    pid: process.pid,
    taskIdentity: task.identity,
  });
  const evidenceDirectory = join(taskScratch, "evidence");
  const taskEvidence: TaskReceiptEvidence[] = [];
  const taskContext = {
    executionContextDigest: digest(options.executionContext.binding),
    scratchId,
    resources: task.resources,
    evidence: taskEvidence,
    missingEvidence: (task.evidence ?? []).map((item) => posix.normalize(item.path)),
  };
  const events: RunEvent[] = [];
  emit(task, events, options, { type: "start" });
  try {
    options.executionContext.assertIdentity();
    options.executionContext.lease.assertCurrent();
  } catch {
    const reason = "bootstrap_state_changed";
    if (task.execution.kind === "fitness") {
      try {
        mkdirSync(evidenceDirectory, { recursive: true, mode: 0o700 });
        writeFitnessReceipt(
          join(evidenceDirectory, "fitness.json"),
          fitnessFailureReceipt(task, options.executionContext, options.cwd, reason),
        );
        const captured = capturedTaskEvidence(evidenceDirectory, task.evidence ?? [], taskRedactions(options));
        taskEvidence.push(...captured.evidence);
        taskContext.missingEvidence.splice(0, taskContext.missingEvidence.length, ...captured.missing);
      } catch {
        // The task receipt below records the terminal evidence-write failure.
      }
    }
    emit(task, events, options, { type: "terminal", status: "failed", reason });
    return {
      key: task.key,
      identity: task.identity,
      status: "failed",
      exitCode: null,
      reason,
      stdout: "",
      stderr: "",
      outputTruncated: false,
      ...taskContext,
      events,
    };
  }
  if (task.execution.kind === "executor") {
    emit(task, events, options, {
      type: "terminal",
      status: "failed",
      reason: "executor_not_available",
    });
    return {
      key: task.key,
      identity: task.identity,
      status: "failed",
      exitCode: null,
      reason: "executor_not_available",
      stdout: "",
      stderr: "",
      outputTruncated: false,
      ...taskContext,
      events,
    };
  }
  let command: string;
  let commandArguments: readonly string[] = [];
  let shell = true;
  let fitnessExecution: FitnessExecution | undefined;
  try {
    if (task.execution.kind === "command") {
      command = task.execution.command;
    } else {
      fitnessExecution = prepareFitnessExecution(task, options.executionContext, options.cwd);
      command = fitnessExecution.executable ?? "";
      commandArguments = fitnessExecution.args;
      shell = false;
    }
  } catch (error) {
    let reason = "task_environment_setup_failed";
    if (task.execution.kind === "fitness") {
      try {
        mkdirSync(evidenceDirectory, { recursive: true, mode: 0o700 });
        writeFitnessReceipt(join(evidenceDirectory, "fitness.json"), fitnessFailureReceipt(task, options.executionContext, options.cwd, reason));
        const captured = capturedTaskEvidence(evidenceDirectory, task.evidence ?? [], taskRedactions(options));
        taskEvidence.push(...captured.evidence);
        taskContext.missingEvidence.splice(0, taskContext.missingEvidence.length, ...captured.missing);
      } catch {
        reason = "fitness_evidence_write_failed";
      }
    }
    emit(task, events, options, { type: "terminal", status: "failed", reason });
    return {
      key: task.key,
      identity: task.identity,
      status: "failed",
      exitCode: null,
      reason,
      stdout: "",
      stderr: error instanceof Error ? error.message : String(error),
      outputTruncated: false,
      ...taskContext,
      events,
    };
  }
  let environment: NodeJS.ProcessEnv;
  try {
    environment = taskEnvironment(options, taskScratch);
  } catch (error) {
    let reason = error instanceof SdlcError && error.code === "TASK_ENVIRONMENT_INVALID"
      ? "task_environment_invalid"
      : "task_environment_setup_failed";
    if (fitnessExecution !== undefined) {
      try {
        mkdirSync(evidenceDirectory, { recursive: true, mode: 0o700 });
        writeFitnessReceipt(join(evidenceDirectory, "fitness.json"), finaliseFitnessReceipt(fitnessExecution.receipt, "failed", reason, null));
        const captured = capturedTaskEvidence(evidenceDirectory, task.evidence ?? [], taskRedactions(options));
        taskEvidence.push(...captured.evidence);
        taskContext.missingEvidence.splice(0, taskContext.missingEvidence.length, ...captured.missing);
      } catch {
        reason = "fitness_evidence_write_failed";
      }
    }
    emit(task, events, options, { type: "terminal", status: "failed", reason });
    return {
      key: task.key,
      identity: task.identity,
      status: "failed",
      exitCode: null,
      reason,
      stdout: "",
      stderr: error instanceof Error ? error.message : String(error),
      outputTruncated: false,
      ...taskContext,
      events,
    };
  }
  if (fitnessExecution?.failureReason !== undefined) {
    let reason = fitnessExecution.failureReason;
    try {
      mkdirSync(evidenceDirectory, { recursive: true, mode: 0o700 });
      writeFitnessReceipt(join(evidenceDirectory, "fitness.json"), fitnessExecution.receipt);
    } catch {
      reason = "fitness_evidence_write_failed";
    }
    const redactions = taskRedactions(options);
    const captured = capturedTaskEvidence(evidenceDirectory, task.evidence ?? [], redactions);
    taskEvidence.push(...captured.evidence);
    taskContext.missingEvidence.splice(0, taskContext.missingEvidence.length, ...captured.missing);
    emit(task, events, options, { type: "terminal", status: "failed", reason });
    return {
      key: task.key,
      identity: task.identity,
      status: "failed",
      exitCode: null,
      reason,
      stdout: "",
      stderr: "",
      outputTruncated: false,
      ...taskContext,
      events,
    };
  }

  return new Promise((resolve) => {
    const captures: Record<"stdout" | "stderr", OutputCapture> = {
      stdout: { pending: "", text: "", bytes: 0, truncated: false },
      stderr: { pending: "", text: "", bytes: 0, truncated: false },
    };
    let stdoutBytes = 0;
    let stderrBytes = 0;
    let lastProgress = Date.now();
    let forced:
      | Readonly<{
          status: "stalled" | "cancelled" | "failed";
          reason: string;
          diagnostic?: ProcessDiagnostic;
        }>
      | undefined;
    const child = spawn(command, commandArguments, {
      cwd: join(options.cwd, task.projectRoot),
      env: environment,
      shell,
      stdio: ["ignore", "pipe", "pipe"],
      detached: process.platform !== "win32",
    });
    const maximumOutput = options.maxOutputBytes ?? 64 * 1024;
    const redactions = taskRedactions(options);
    const captureOutput = (
      stream: "stdout" | "stderr",
      text: string,
      flush = false,
    ): void => {
      const capture = captures[stream];
      const combined = `${capture.pending}${text}`;
      const boundary = flush ? combined.length : safeBoundary(combined, redactions);
      const ready = redacted(combined.slice(0, boundary), redactions);
      capture.pending = combined.slice(boundary);
      const remaining = Math.max(0, maximumOutput - capture.bytes);
      const retained = utf8Prefix(ready, remaining);
      if (Buffer.byteLength(retained) < Buffer.byteLength(ready)) {
        capture.truncated = true;
      }
      if (retained.length > 0) {
        capture.text += retained;
        capture.bytes += Buffer.byteLength(retained);
        emit(task, events, options, { type: "output", stream, text: retained });
      }
    };
    const heartbeat = setInterval(() => {
      emit(task, events, options, { type: "heartbeat" });
      if (
        forced === undefined &&
        Date.now() - lastProgress >= task.budget.noProgressMs
      ) {
        const diagnostic: ProcessDiagnostic = {
          pid: child.pid ?? -1,
          running: child.exitCode === null,
          cpu: task.resources.cpu,
          memoryMiB: task.resources.memoryMiB,
          ports: task.resources.ports,
          exclusive: task.resources.exclusive,
          stdoutBytes,
          stderrBytes,
          processes: captureProcessGroup(child.pid ?? -1),
        };
        forced = { status: "stalled", reason: "no_progress", diagnostic };
        emit(task, events, options, {
          type: "cancellation",
          reason: forced.reason,
        });
        clearInterval(heartbeat);
        terminateProcessGroup(child, options.terminationGraceMs ?? 1_000);
      }
    }, task.budget.heartbeatMs);
    const phaseBudget = setTimeout(() => {
      if (forced === undefined) {
        forced = { status: "failed", reason: "phase_budget_exceeded" };
        emit(task, events, options, {
          type: "cancellation",
          reason: forced.reason,
        });
        clearInterval(heartbeat);
        terminateProcessGroup(child, options.terminationGraceMs ?? 1_000);
      }
    }, task.budget.phaseMs);
    const abort = (): void => {
      if (forced === undefined) {
        forced = { status: "cancelled", reason: "operator_abort" };
        emit(task, events, options, {
          type: "cancellation",
          reason: forced.reason,
        });
        clearInterval(heartbeat);
        clearTimeout(phaseBudget);
        terminateProcessGroup(child, options.terminationGraceMs ?? 1_000);
      }
    };
    options.signal?.addEventListener("abort", abort, { once: true });
    if (options.signal?.aborted === true) {
      abort();
    }
    child.stdout.on("data", (chunk: Buffer) => {
      const text = chunk.toString("utf8");
      stdoutBytes += chunk.length;
      lastProgress = Date.now();
      captureOutput("stdout", text);
    });
    child.stderr.on("data", (chunk: Buffer) => {
      const text = chunk.toString("utf8");
      stderrBytes += chunk.length;
      lastProgress = Date.now();
      captureOutput("stderr", text);
    });
    child.on("error", (error) => {
      captureOutput("stderr", error.message);
    });
    child.on("close", (code) => {
      clearInterval(heartbeat);
      clearTimeout(phaseBudget);
      options.signal?.removeEventListener("abort", abort);
      captureOutput("stdout", "", true);
      captureOutput("stderr", "", true);
      let status: TaskReceipt["status"] = forced?.status ?? (code === 0 ? "succeeded" : "failed");
      let reason = forced?.reason ?? (code === 0 ? null : "process_exit_nonzero");
      if (fitnessExecution !== undefined) {
        const receipt = finaliseFitnessReceipt(fitnessExecution.receipt, status, reason, code);
        try {
          mkdirSync(evidenceDirectory, { recursive: true, mode: 0o700 });
          writeFitnessReceipt(join(evidenceDirectory, "fitness.json"), receipt);
        } catch {
          status = "failed";
          reason = "fitness_evidence_write_failed";
        }
      }
      try {
        options.executionContext.assertIdentity();
        options.executionContext.lease.assertCurrent();
      } catch {
        status = "failed";
        reason = "bootstrap_state_changed";
      }
      try {
        const captured = capturedTaskEvidence(
          evidenceDirectory,
          task.evidence ?? [],
          redactions,
        );
        taskEvidence.push(...captured.evidence);
        taskContext.missingEvidence.splice(0, taskContext.missingEvidence.length, ...captured.missing);
        if (status === "succeeded" && captured.missing.length > 0) {
          status = "failed";
          reason = "task_evidence_invalid";
        }
      } catch {
        status = "failed";
        reason = "task_evidence_invalid";
      }
      emit(task, events, options, {
        type: "terminal",
        status,
        ...(reason === null ? {} : { reason }),
      });
      resolve({
        key: task.key,
        identity: task.identity,
        status,
        exitCode: forced === undefined ? code : null,
        reason,
        stdout: captures.stdout.text,
        stderr: captures.stderr.text,
        outputTruncated:
          captures.stdout.truncated || captures.stderr.truncated,
        ...taskContext,
        events,
        ...(forced?.diagnostic === undefined
          ? {}
          : { diagnostic: forced.diagnostic }),
      });
    });
  });
}

function skippedReceipt(
  task: GraphTask,
  reason: string,
  options: RunOptions,
  scratchId: string,
): TaskReceipt {
  return {
    key: task.key,
    identity: task.identity,
    status: "skipped",
    exitCode: null,
    reason,
    stdout: "",
    stderr: "",
    outputTruncated: false,
    executionContextDigest: digest(options.executionContext.binding),
    scratchId,
    resources: task.resources,
    evidence: [],
    missingEvidence: (task.evidence ?? []).map((item) => posix.normalize(item.path)),
    events: [
      {
        taskKey: task.key,
        taskIdentity: task.identity,
        type: "terminal",
        status: "skipped",
        reason,
      },
    ],
  };
}

function failedAdmissionReceipt(task: GraphTask, options: RunOptions, scratchId: string): TaskReceipt {
  const reason = "resource_capacity_exceeded";
  return {
    key: task.key,
    identity: task.identity,
    status: "failed",
    exitCode: null,
    reason,
    stdout: "",
    stderr: "",
    outputTruncated: false,
    executionContextDigest: digest(options.executionContext.binding),
    scratchId,
    resources: task.resources,
    evidence: [],
    missingEvidence: (task.evidence ?? []).map((item) => posix.normalize(item.path)),
    events: [
      {
        taskKey: task.key,
        taskIdentity: task.identity,
        type: "terminal",
        status: "failed",
        reason,
      },
    ],
  };
}

function cancelledBeforeStartReceipt(task: GraphTask, options: RunOptions, scratchId: string): TaskReceipt {
  const reason = "operator_abort";
  return {
    key: task.key,
    identity: task.identity,
    status: "cancelled",
    exitCode: null,
    reason,
    stdout: "",
    stderr: "",
    outputTruncated: false,
    executionContextDigest: digest(options.executionContext.binding),
    scratchId,
    resources: task.resources,
    evidence: [],
    missingEvidence: (task.evidence ?? []).map((item) => posix.normalize(item.path)),
    events: [
      {
        taskKey: task.key,
        taskIdentity: task.identity,
        type: "cancellation",
        reason,
      },
      {
        taskKey: task.key,
        taskIdentity: task.identity,
        type: "terminal",
        status: "cancelled",
        reason,
      },
    ],
  };
}

export async function runGraph(
  graph: SdlcGraph,
  selection: readonly TaskIdentity[],
  options: RunOptions,
): Promise<RunReceipt> {
  const selected = new Set(selection);
  if (selected.size !== selection.length) {
    throw new SdlcError(
      "RUN_SELECTION_INVALID",
      "selection contains duplicate task identities",
    );
  }
  const tasks = graph.tasks.filter((task) => selected.has(task.identity));
  if (tasks.length !== selection.length) {
    throw new SdlcError(
      "RUN_SELECTION_INVALID",
      "selection contains an unknown task identity",
    );
  }
  const selectedKeys = new Set(tasks.map((task) => task.key));
  for (const task of tasks) {
    for (const dependency of task.dependsOn) {
      if (!selectedKeys.has(dependency)) {
        throw new SdlcError(
          "RUN_SELECTION_INVALID",
          `selection omits dependency ${dependency} required by ${task.key}`,
        );
      }
    }
  }
  options.executionContext.assertIdentity();
  options.executionContext.lease.assertCurrent();
  const scratchRoot = mkdtempSync(join(tmpdir(), "tc-sdlc-run-"));
  const scratchId = basename(scratchRoot);
  const scratchMarker = {
    schema: "tc.sdlc/temporary-owner/v1",
    owner: "@three-cubes/tc-sdlc",
    kind: "test-run",
    pid: process.pid,
  } as const;
  writeCanonicalEvidence(join(scratchRoot, ".tc-sdlc-temporary.json"), scratchMarker);
  const scratchIdentity = lstatSync(scratchRoot, { bigint: true });
  const scratchIdentityValue = {
    device: scratchIdentity.dev.toString(),
    inode: scratchIdentity.ino.toString(),
    birthtimeNanoseconds: scratchIdentity.birthtimeNs.toString(),
  };
  let cleanupStatus: "removed" | "retained" = "retained";
  let receiptReason: string | null = null;
  const receipts = new Map<string, TaskReceipt>();
  const pending = new Set(tasks.map((task) => task.key));
  const running = new Map<
    string,
    Promise<Readonly<{ task: GraphTask; receipt: TaskReceipt }>>
  >();
  let taskReceipts: TaskReceipt[] = [];
  let status: RunStatus = "failed";
  let stateIntegrityFailed = false;

  try {
    const capacity = options.capacity ?? detectedCapacity();
    if (!(capacity.cpu > 0) || !(capacity.memoryMiB > 0)) {
      throw new SdlcError("RUN_CAPACITY_INVALID", "host capacity must be positive");
    }
    const allocation: Allocation = {
      cpu: 0,
      memoryMiB: 0,
      ports: new Set(),
      exclusive: new Set(),
    };

    while (pending.size > 0 || running.size > 0) {
      let advanced = false;
      for (const task of tasks) {
        if (!pending.has(task.key)) {
          continue;
        }
        if (options.signal?.aborted === true) {
          const receipt = cancelledBeforeStartReceipt(task, options, scratchId);
          receipts.set(task.key, receipt);
          for (const event of receipt.events) {
            if (event.type !== "terminal") options.onEvent?.(event);
          }
          pending.delete(task.key);
          advanced = true;
          continue;
        }
        const dependencies = task.dependsOn;
        if (dependencies.some((key) => !receipts.has(key))) {
          continue;
        }
        const failed = dependencies.find(
          (key) => receipts.get(key)?.status !== "succeeded",
        );
        if (failed !== undefined) {
          const receipt = skippedReceipt(task, `dependency_failed:${failed}`, options, scratchId);
          receipts.set(task.key, receipt);
          pending.delete(task.key);
          advanced = true;
          continue;
        }
        if (impossible(task, capacity)) {
          const receipt = failedAdmissionReceipt(task, options, scratchId);
          receipts.set(task.key, receipt);
          pending.delete(task.key);
          advanced = true;
          continue;
        }
        if (canAllocate(task, capacity, allocation)) {
          allocate(task, allocation, 1);
          const execution = executeTask(task, options, scratchRoot, scratchId).then((receipt) => ({
            task,
            receipt,
          }));
          running.set(task.key, execution);
          pending.delete(task.key);
          advanced = true;
        }
      }
      if (running.size > 0) {
        const completed = await Promise.race(running.values());
        running.delete(completed.task.key);
        allocate(completed.task, allocation, -1);
        receipts.set(completed.task.key, completed.receipt);
        continue;
      }
      if (pending.size > 0 && !advanced) {
        throw new SdlcError("RUN_GRAPH_INVALID", "selected task dependencies cannot be scheduled");
      }
    }

    taskReceipts = tasks.map((task) => receipts.get(task.key) as TaskReceipt);
    status = taskReceipts.some((receipt) => receipt.status === "cancelled")
      ? "cancelled"
      : taskReceipts.some((receipt) => receipt.status === "stalled")
        ? "stalled"
        : taskReceipts.every((receipt) => receipt.status === "succeeded")
          ? "succeeded"
          : "failed";
  } catch (error) {
    receiptReason = error instanceof Error ? error.message : String(error);
    if (running.size > 0) {
      const settled = await Promise.allSettled(running.values());
      for (const result of settled) {
        if (result.status === "fulfilled") {
          receipts.set(result.value.task.key, result.value.receipt);
        }
      }
    }
    taskReceipts = tasks.map((task) =>
      receipts.get(task.key) ?? skippedReceipt(
        task,
        `run_aborted:${receiptReason}`,
        options,
        scratchId,
      ),
    );
    status = "failed";
  } finally {
    try {
    options.executionContext.verifyIntegrity();
    options.executionContext.lease.assertCurrent();
    } catch {
      receiptReason ??= "bootstrap_state_changed";
      stateIntegrityFailed = true;
    }
    try {
    const currentIdentity = lstatSync(scratchRoot, { bigint: true });
    const markerPath = join(scratchRoot, ".tc-sdlc-temporary.json");
    const marker = JSON.parse(readFileSync(markerPath, "utf8")) as unknown;
    const unchangedRoot = currentIdentity.dev.toString() === scratchIdentityValue.device &&
      currentIdentity.ino.toString() === scratchIdentityValue.inode &&
      currentIdentity.birthtimeNs.toString() === scratchIdentityValue.birthtimeNanoseconds &&
      currentIdentity.isDirectory() && !currentIdentity.isSymbolicLink() &&
      digest(marker) === digest(scratchMarker);
    if (!unchangedRoot) throw new Error("run scratch root identity changed");
    rmSync(scratchRoot, { recursive: true });
    cleanupStatus = existsSync(scratchRoot) ? "retained" : "removed";
    if (cleanupStatus !== "removed") receiptReason ??= "scratch_cleanup_failed";
    } catch {
      receiptReason ??= "scratch_cleanup_failed";
    }
  }
  if (stateIntegrityFailed) {
    taskReceipts = taskReceipts.map((receipt) => {
      if (receipt.status !== "succeeded") return receipt;
      return {
        ...receipt,
        status: "failed",
        reason: "bootstrap_state_changed",
        exitCode: null,
        events: receipt.events.map((event) =>
          event.type === "terminal"
            ? { ...event, status: "failed", reason: "bootstrap_state_changed" }
            : event,
        ),
      };
    });
    status = "failed";
  }
  const terminalStatus = receiptReason !== null
    ? "failed"
    : status;
  const receipt: RunReceipt = {
    schema: "tc.sdlc/run-receipt/v1",
    declarationDigest: graph.declarationDigest,
    lockDigest: graph.lockDigest,
    bootstrapContext: options.executionContext.binding,
    scratchId,
    scratchCleanup: cleanupStatus,
    reason: receiptReason,
    selection: tasks.map((task) => task.identity),
    status: terminalStatus,
    tasks: taskReceipts,
  };
  writeRunReceipt(options.receiptPath, receipt);
  for (const task of taskReceipts) {
    for (const event of task.events) {
      if (event.type === "terminal") options.onEvent?.(event);
    }
  }
  return receipt;
}
