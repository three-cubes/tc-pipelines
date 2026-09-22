import { createServer, type Server } from "node:net";
import { realpathSync } from "node:fs";

import { digest } from "../canonical.js";

const PORT_BASE = 10_000;
const PORT_COUNT = 20_000;
const WAIT_MILLISECONDS = 5_000;
const RETRY_MILLISECONDS = 25;

export type BootstrapKernelBoundaryDomain =
  | "bootstrap-reference-recovery"
  | "bootstrap-state-materialization"
  | "image-production";

export type BootstrapKernelBoundary = Readonly<{
  server: Server;
  domain: BootstrapKernelBoundaryDomain;
  identity: Readonly<Record<string, string>>;
  stateRoot: string;
  port: number;
}>;

export class BootstrapKernelBoundaryError extends Error {
  readonly kind: "busy" | "invalid";

  constructor(kind: "busy" | "invalid", message: string) {
    super(message);
    this.kind = kind;
  }
}

export function bootstrapKernelBoundaryPort(
  stateRoot: string,
  domain: BootstrapKernelBoundaryDomain,
  identity: Readonly<Record<string, string>>,
): number {
  const canonicalRoot = realpathSync(stateRoot);
  const hexadecimal = digest({
    boundary: domain,
    ...(domain === "image-production" ? {} : { stateRoot: canonicalRoot }),
    identity,
  }).slice("sha256:".length, "sha256:".length + 8);
  return PORT_BASE + Number.parseInt(hexadecimal, 16) % PORT_COUNT;
}

async function bind(port: number): Promise<Server> {
  const server = createServer((socket) => socket.destroy());
  return await new Promise<Server>((resolve, reject) => {
    const failed = (error: Error): void => {
      server.removeListener("listening", listening);
      reject(error);
    };
    const listening = (): void => {
      server.removeListener("error", failed);
      resolve(server);
    };
    server.once("error", failed);
    server.once("listening", listening);
    server.listen({ host: "127.0.0.1", port, exclusive: true });
  });
}

/** Hold a deterministic loopback listener as the kernel-owned lock for one authority key. */
export async function acquireBootstrapKernelBoundary(
  stateRoot: string,
  domain: BootstrapKernelBoundaryDomain,
  identity: Readonly<Record<string, string>>,
  waitMilliseconds = WAIT_MILLISECONDS,
): Promise<BootstrapKernelBoundary> {
  let canonicalRoot: string;
  let port: number;
  try {
    canonicalRoot = realpathSync(stateRoot);
    port = bootstrapKernelBoundaryPort(canonicalRoot, domain, identity);
  } catch (error) {
    throw new BootstrapKernelBoundaryError(
      "invalid",
      `bootstrap kernel boundary root is unavailable: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
  const deadline = Date.now() + waitMilliseconds;
  while (true) {
    try {
      return {
        server: await bind(port),
        domain,
        identity,
        stateRoot: canonicalRoot,
        port,
      };
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EADDRINUSE") {
        throw new BootstrapKernelBoundaryError(
          "invalid",
          `bootstrap kernel boundary could not be acquired: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
      if (Date.now() >= deadline) {
        throw new BootstrapKernelBoundaryError(
          "busy",
          `bootstrap kernel boundary is occupied for ${domain}`,
        );
      }
      await new Promise((resolve) => setTimeout(resolve, RETRY_MILLISECONDS));
    }
  }
}

export function assertBootstrapKernelBoundary(boundary: BootstrapKernelBoundary): void {
  const address = boundary.server.address();
  if (!boundary.server.listening || address === null || typeof address === "string" ||
      address.port !== boundary.port) {
    throw new BootstrapKernelBoundaryError(
      "invalid",
      `bootstrap kernel boundary changed while held for ${boundary.domain}`,
    );
  }
}

export function releaseBootstrapKernelBoundary(boundary: BootstrapKernelBoundary): void {
  if (!boundary.server.listening) {
    throw new BootstrapKernelBoundaryError(
      "invalid",
      `bootstrap kernel boundary is no longer held for ${boundary.domain}`,
    );
  }
  boundary.server.close();
}
