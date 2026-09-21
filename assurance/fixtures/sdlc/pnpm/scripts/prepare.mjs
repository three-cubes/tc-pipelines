import { mkdir, readFile, writeFile } from "node:fs/promises";
import kleur from "kleur";

kleur.enabled = true;
const source = kleur.bold((await readFile("src/input.txt", "utf8")).trim());
const rendered = source;
await mkdir("generated", { recursive: true });
try {
if ((await readFile("generated/value.txt", "utf8")) === rendered) process.exit(0);
} catch {}
await writeFile("generated/value.txt", rendered);
