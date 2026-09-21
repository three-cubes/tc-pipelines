import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export default function setup(): () => void {
  const root = mkdtempSync(join(tmpdir(), "tc-sdlc-test-run-"));
  writeFileSync(
    join(root, ".tc-sdlc-temporary.json"),
    `${JSON.stringify({
      schema: "tc.sdlc/temporary-owner/v1",
      owner: "@three-cubes/tc-sdlc",
      kind: "test-run",
      pid: process.pid,
    })}\n`,
    { mode: 0o600 },
  );
  process.env.TMPDIR = root;
  process.env.TMP = root;
  process.env.TEMP = root;
  return () => {
    rmSync(root, { recursive: true, force: true });
  };
}
