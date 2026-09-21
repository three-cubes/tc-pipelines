import { chmodSync, cpSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositorySchemas = resolve(packageRoot, "..", "..", "schemas");
const releaseCatalogue = resolve(packageRoot, "..", "..", "release", "catalogue.json");
const output = resolve(packageRoot, "dist", "schemas");

mkdirSync(output, { recursive: true });
cpSync(repositorySchemas, output, { recursive: true });
chmodSync(resolve(packageRoot, "dist", "cli.js"), 0o755);
const releaseOutput = resolve(packageRoot, "dist", "release");
mkdirSync(releaseOutput, { recursive: true });
cpSync(releaseCatalogue, resolve(releaseOutput, "catalogue.json"));
