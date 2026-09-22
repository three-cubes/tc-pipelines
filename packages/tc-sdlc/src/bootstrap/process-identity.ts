import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

export type ProcessOwnerState = "live" | "dead" | "ambiguous";

const currentDarwinStartEpochSeconds = Math.floor(
  (Date.now() - process.uptime() * 1_000) / 1_000,
);

export function processStartIdentity(pid: number): string | undefined {
  try {
    if (process.platform === "linux") {
      const value = readFileSync(`/proc/${pid}/stat`, "utf8");
      const suffix = value.slice(value.lastIndexOf(")") + 2).trim().split(/\s+/);
      const startedAtClockTick = suffix[19];
      return startedAtClockTick === undefined ? undefined : `linux:${startedAtClockTick}`;
    }
    if (process.platform === "darwin") {
      if (pid === process.pid) return `darwin:${currentDarwinStartEpochSeconds}`;
      const value = execFileSync(
        "/bin/ps",
        ["-p", `${pid}`, "-o", "lstart="],
        {
          encoding: "utf8",
          env: { LC_ALL: "C", PATH: "/usr/bin:/bin" },
          stdio: ["ignore", "pipe", "ignore"],
        },
      ).trim();
      const epochMilliseconds = Date.parse(value);
      return value === "" || !Number.isFinite(epochMilliseconds)
        ? undefined
        : `darwin:${Math.floor(epochMilliseconds / 1_000)}`;
    }
  } catch {
    return undefined;
  }
  return undefined;
}

export function processOwnerState(pid: number, expectedStartIdentity: string): ProcessOwnerState {
  try {
    process.kill(pid, 0);
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code === "ESRCH") return "dead";
    return "ambiguous";
  }
  const currentStartIdentity = processStartIdentity(pid);
  if (currentStartIdentity === undefined) return "ambiguous";
  return currentStartIdentity === expectedStartIdentity ? "live" : "dead";
}
