import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";

const scratch = dirname(process.env.TC_SDLC_TASK_EVIDENCE_DIR);
const configuration = join(process.env.XDG_CONFIG_HOME, "pnpm", "config.yaml");
const store = process.env.PNPM_STORE_DIR;
const isolated = Object.fromEntries([
  "HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "COREPACK_HOME",
].map((name) => [name, process.env[name]]));
if (Object.values(isolated).some((path) => typeof path !== "string" || !path.startsWith(scratch))) {
  throw new Error(`task runtime directories are not isolated: ${JSON.stringify(isolated)}`);
}
if (!process.env.XDG_CONFIG_HOME.startsWith(scratch) || !store.startsWith(scratch)) {
  throw new Error("pnpm configuration/cache are not bound to this task scratch");
}

const version = execFileSync("pnpm", ["--version"], { encoding: "utf8" }).trim();
if (version !== "11.22.0") throw new Error(`unexpected state-owned pnpm version: ${version}`);
execFileSync("pnpm", ["config", "set", "store-dir", store, "--location=user"], {
  encoding: "utf8",
});
const observedStore = execFileSync("pnpm", ["config", "get", "store-dir"], {
  encoding: "utf8",
}).trim();
if (observedStore !== store) {
  throw new Error(`pnpm resolved store ${observedStore} instead of task scratch store ${store}`);
}
if (!existsSync(configuration)) {
  throw new Error(`pnpm did not write configuration under task scratch: ${configuration}`);
}
const config = readFileSync(configuration, "utf8");
if (!config.includes(`storeDir: ${store}`)) {
  throw new Error("pnpm task scratch configuration does not bind its store directory");
}
execFileSync("node", ["tests/verify.mjs"], { stdio: "inherit" });
console.log(JSON.stringify({ version, configuration, store, isolated }));
