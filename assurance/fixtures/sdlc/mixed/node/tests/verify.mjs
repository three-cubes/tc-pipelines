import { readFile } from "node:fs/promises";
import kleur from "kleur";

kleur.enabled = true;
const expected = kleur.bold(await readFile("../python/generated/value.txt", "utf8"));
const actual = await readFile("generated/value.txt", "utf8");
if (actual !== expected) {
  throw new Error("prepared mixed Node service output does not match its input");
}
