import { SdlcError } from "../errors.js";

export function normalisePath(value: string): string {
  const parts = value
    .replaceAll("\\", "/")
    .split("/")
    .filter((part) => part !== "" && part !== ".");
  return parts.length === 0 ? "." : parts.join("/");
}

export function assertRelativePath(value: string, context: string): void {
  const slashPath = value.replaceAll("\\", "/");
  if (
    slashPath.startsWith("/") ||
    /^[A-Za-z]:/.test(slashPath) ||
    slashPath.split("/").includes("..") ||
    slashPath.includes("\0")
  ) {
    throw new SdlcError(
      "GRAPH_PATH_INVALID",
      `${context} must be an unambiguous repository-relative path: ${value}`,
    );
  }
}
