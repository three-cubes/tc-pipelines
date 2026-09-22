import { existsSync, lstatSync, readdirSync } from "node:fs";
import { join, posix } from "node:path";

import { canonicalJson } from "../canonical.js";

export const BOOTSTRAP_ADAPTER_NAMES = ["node", "pnpm", "python", "uv"] as const;

export type BootstrapStateShape = Readonly<{
  platform: "darwin" | "linux";
  adapters: readonly Readonly<{ name: string; launcher: string }>[];
  dependencies: readonly Readonly<{ manager: string; environment: string }>[];
}>;

export class BootstrapStateShapeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BootstrapStateShapeError";
  }
}

function assertDirectoryEntries(
  directory: string,
  expectedNames: ReadonlySet<string>,
  description: string,
): void {
  const metadata = lstatSync(directory);
  if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
    throw new BootstrapStateShapeError(`${description} is not a real directory`);
  }
  const observed = readdirSync(directory).sort();
  const expected = [...expectedNames].sort();
  if (canonicalJson(observed) !== canonicalJson(expected)) {
    throw new BootstrapStateShapeError(`${description} contains undeclared entries`);
  }
}

/** Validate only the materializer-owned filesystem shape, shared by both trust boundaries. */
export function assertBootstrapStateShape(
  stateDirectory: string,
  stateKey: string,
  state: BootstrapStateShape,
): void {
  if (
    state.adapters.length !== BOOTSTRAP_ADAPTER_NAMES.length ||
    canonicalJson(state.adapters.map((adapter) => adapter.name)) !==
      canonicalJson(BOOTSTRAP_ADAPTER_NAMES)
  ) {
    throw new BootstrapStateShapeError("bootstrap adapter inventory does not match the release contract");
  }
  const expectedTopLevel = new Set(["state.json", "bin"]);
  const expectedDependencyRoots = new Set<string>();
  for (const dependency of state.dependencies) {
    const parts = dependency.environment.split("/");
    const expectedEnvironment = dependency.manager === "pnpm"
      ? "dependencies/node"
      : dependency.manager === "uv"
        ? "dependencies/python"
        : "";
    if (
      (dependency.manager !== "pnpm" && dependency.manager !== "uv") ||
      dependency.environment !== expectedEnvironment ||
      parts.length !== 2 || parts[0] !== "dependencies" ||
      !/^[a-z0-9-]+$/.test(parts[1]!) || expectedDependencyRoots.has(parts[1]!)
    ) {
      throw new BootstrapStateShapeError("bootstrap dependency environment path is invalid");
    }
    expectedTopLevel.add("dependencies");
    expectedDependencyRoots.add(parts[1]!);
  }
  if (state.platform === "darwin") {
    for (const directory of ["home", "corepack", "downloads", "toolchains"]) {
      expectedTopLevel.add(directory);
    }
  } else if (state.dependencies.length > 0) {
    expectedTopLevel.add("home");
  }

  assertDirectoryEntries(stateDirectory, expectedTopLevel, "bootstrap release state");
  const stateFileMetadata = lstatSync(join(stateDirectory, "state.json"));
  if (!stateFileMetadata.isFile() || stateFileMetadata.isSymbolicLink()) {
    throw new BootstrapStateShapeError("bootstrap state manifest is not a regular file");
  }
  const binDirectory = join(stateDirectory, "bin");
  const expectedLaunchers = new Set<string>(BOOTSTRAP_ADAPTER_NAMES);
  assertDirectoryEntries(binDirectory, expectedLaunchers, "bootstrap adapter directory");
  for (const launcher of expectedLaunchers) {
    const metadata = lstatSync(join(binDirectory, launcher));
    if (!metadata.isFile() || metadata.isSymbolicLink()) {
      throw new BootstrapStateShapeError("bootstrap adapter launcher is not a regular file");
    }
  }
  for (const dependency of state.dependencies) {
    const dependencyRoot = join(stateDirectory, dependency.environment);
    const metadata = lstatSync(dependencyRoot);
    if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
      throw new BootstrapStateShapeError("bootstrap dependency environment is not a real directory");
    }
  }
  if (expectedDependencyRoots.size > 0) {
    assertDirectoryEntries(
      join(stateDirectory, "dependencies"),
      expectedDependencyRoots,
      "bootstrap dependency environment directory",
    );
  }
  for (const directory of expectedTopLevel) {
    if (directory === "state.json" || directory === "bin" || directory === "dependencies") continue;
    const path = join(stateDirectory, directory);
    if (!existsSync(path)) {
      throw new BootstrapStateShapeError(`bootstrap release directory is missing: ${directory}`);
    }
    const metadata = lstatSync(path);
    if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
      throw new BootstrapStateShapeError(`bootstrap release directory is not a real directory: ${directory}`);
    }
  }
  if (state.adapters.some((adapter) => adapter.launcher !== posix.join(stateKey, "bin", adapter.name))) {
    throw new BootstrapStateShapeError("bootstrap adapter launcher path is invalid");
  }
}
