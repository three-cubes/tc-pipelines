import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterAll, afterEach } from "vitest";

const runRoot = tmpdir();
const workerRoot = mkdtempSync(join(runRoot, "tc-sdlc-worker-"));

function markOwned(): void {
  writeFileSync(
    join(workerRoot, ".tc-sdlc-temporary.json"),
    `${JSON.stringify({
      schema: "tc.sdlc/temporary-owner/v1",
      owner: "@three-cubes/tc-sdlc",
      kind: "test-run",
      pid: process.pid,
    })}\n`,
    { mode: 0o600 },
  );
}

markOwned();
process.env.TMPDIR = workerRoot;
process.env.TMP = workerRoot;
process.env.TEMP = workerRoot;

afterEach(async () => {
  await rm(workerRoot, { recursive: true, force: true });
  mkdirSync(workerRoot, { mode: 0o700 });
  markOwned();
});

afterAll(async () => {
  await rm(workerRoot, { recursive: true, force: true });
});
