import { readFile } from "node:fs/promises";
import kleur from "kleur";

kleur.enabled = true;
const expected = "\u001b[1m3.10:xn--fa-hia.de\n\u001b[22m";
const actual = await readFile("generated/value.txt", "utf8");
if (actual !== expected) {
  throw new Error("prepared mixed Node service output does not match its input");
}
