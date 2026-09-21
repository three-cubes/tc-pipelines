import { readFile } from "node:fs/promises";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import kleur from "kleur";

const require = createRequire(import.meta.url);
if (JSON.parse(readFileSync(join(dirname(require.resolve("kleur")), "package.json"))).version !== "4.1.5") {
  throw new Error("expected locked kleur 4.1.5");
}
kleur.enabled = true;
if (kleur.bold("locked") !== "\u001b[1mlocked\u001b[22m") {
  throw new Error("locked kleur did not produce the expected ANSI output");
}
const expected = "\u001b[1mpnpm-only consumer payload\u001b[22m";
const actual = await readFile("generated/value.txt", "utf8");
if (actual !== expected) {
  throw new Error("prepared pnpm consumer output does not match its input");
}
