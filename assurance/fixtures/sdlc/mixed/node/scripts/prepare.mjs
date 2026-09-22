import { mkdir, readFile, writeFile } from "node:fs/promises";
import kleur from "kleur";

kleur.enabled = true;
const source = kleur.bold(await readFile("../python/generated/value.txt", "utf8"));
await mkdir("generated", { recursive: true });
try {
  if ((await readFile("generated/value.txt", "utf8")) === source) process.exit(0);
} catch {}
await writeFile("generated/value.txt", source);
