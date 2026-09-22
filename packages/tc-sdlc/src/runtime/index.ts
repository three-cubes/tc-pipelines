import { spawn, spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { availableParallelism, totalmem } from "node:os";
import { join } from "node:path";

import {
  type RunEvent,
  type ProcessDiagnostic,
  type ProcessSample,
  type RunReceipt,
  type RunStatus,
  type TaskReceipt,
  writeRunReceipt,
} from "../evidence/index.js";
import { SdlcError } from "../errors.js";
import type { GraphTask, SdlcGraph, TaskIdentity } from "../schema/types.js";

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
  options.onEvent?.(value);
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

async function executeTask(
  task: GraphTask,
  options: RunOptions,
): Promise<TaskReceipt> {
  const events: RunEvent[] = [];
  emit(task, events, options, { type: "start" });
  if (task.execution.kind !== "command") {
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
      events,
    };
  }
  const command = task.execution.command;

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
    const child = spawn(command, {
      cwd: join(options.cwd, task.projectRoot),
      env: {
        PATH: process.env.PATH ?? "",
        ...options.environment,
      },
      shell: true,
      stdio: ["ignore", "pipe", "pipe"],
      detached: process.platform !== "win32",
    });
    const maximumOutput = options.maxOutputBytes ?? 64 * 1024;
    const environmentRedactions = Object.entries(options.environment ?? {})
      .filter(([name]) => /(?:secret|token|password|credential|key)/i.test(name))
      .map(([, value]) => value);
    const redactions = [...(options.redactions ?? []), ...environmentRedactions]
      .filter((value) => value.length > 0)
      .sort((left, right) => right.length - left.length);
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
      const status = forced?.status ?? (code === 0 ? "succeeded" : "failed");
      const reason = forced?.reason ?? (code === 0 ? null : "process_exit_nonzero");
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
        events,
        ...(forced?.diagnostic === undefined
          ? {}
          : { diagnostic: forced.diagnostic }),
      });
    });
  });
}

function skippedReceipt(task: GraphTask, reason: string): TaskReceipt {
  return {
    key: task.key,
    identity: task.identity,
    status: "skipped",
    exitCode: null,
    reason,
    stdout: "",
    stderr: "",
    outputTruncated: false,
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

function failedAdmissionReceipt(task: GraphTask): TaskReceipt {
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

function cancelledBeforeStartReceipt(task: GraphTask): TaskReceipt {
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
  const receipts = new Map<string, TaskReceipt>();
  const pending = new Set(tasks.map((task) => task.key));
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
  const running = new Map<
    string,
    Promise<Readonly<{ task: GraphTask; receipt: TaskReceipt }>>
  >();

  while (pending.size > 0 || running.size > 0) {
    let advanced = false;
    for (const task of tasks) {
      if (!pending.has(task.key)) {
        continue;
      }
      if (options.signal?.aborted === true) {
        const receipt = cancelledBeforeStartReceipt(task);
        receipts.set(task.key, receipt);
        for (const event of receipt.events) {
          options.onEvent?.(event);
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
        const receipt = skippedReceipt(task, `dependency_failed:${failed}`);
        receipts.set(task.key, receipt);
        options.onEvent?.(receipt.events[0] as RunEvent);
        pending.delete(task.key);
        advanced = true;
        continue;
      }
      if (impossible(task, capacity)) {
        const receipt = failedAdmissionReceipt(task);
        receipts.set(task.key, receipt);
        options.onEvent?.(receipt.events[0] as RunEvent);
        pending.delete(task.key);
        advanced = true;
        continue;
      }
      if (canAllocate(task, capacity, allocation)) {
        allocate(task, allocation, 1);
        const execution = executeTask(task, options).then((receipt) => ({
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

  const taskReceipts = tasks.map((task) => receipts.get(task.key) as TaskReceipt);
  const status: RunStatus = taskReceipts.some(
    (receipt) => receipt.status === "cancelled",
  )
    ? "cancelled"
    : taskReceipts.some((receipt) => receipt.status === "stalled")
      ? "stalled"
      : taskReceipts.every((receipt) => receipt.status === "succeeded")
        ? "succeeded"
        : "failed";
  const receipt: RunReceipt = {
    schema: "tc.sdlc/run-receipt/v1",
    declarationDigest: graph.declarationDigest,
    lockDigest: graph.lockDigest,
    selection: tasks.map((task) => task.identity),
    status,
    tasks: taskReceipts,
  };
  writeRunReceipt(options.receiptPath, receipt);
  return receipt;
}
