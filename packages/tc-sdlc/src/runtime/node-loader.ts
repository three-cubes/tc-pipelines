import { createRequire, registerHooks } from "node:module";
import { realpathSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const nodeModules = process.env.TC_SDLC_NODE_MODULES;

function isBarePackageSpecifier(specifier: string): boolean {
  return !specifier.startsWith("#") && !specifier.startsWith(".") && !specifier.startsWith("/") && !/^[a-zA-Z][a-zA-Z+.-]*:/.test(specifier);
}

function isModuleNotFound(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error && (error.code === "MODULE_NOT_FOUND" || error.code === "ERR_MODULE_NOT_FOUND");
}

function isStateImporter(parentURL: string | undefined, nodeModules: string): boolean {
  if (parentURL === undefined || !parentURL.startsWith("file:")) return false;
  const path = relative(nodeModules, fileURLToPath(parentURL));
  return path === "" || (!path.startsWith("../") && path !== "..");
}

if (nodeModules !== undefined) {
  const canonicalNodeModules = realpathSync(nodeModules);
  const stateEnvironment = dirname(canonicalNodeModules);
  const stateParent = pathToFileURL(join(canonicalNodeModules, ".tc-sdlc-resolver.mjs")).href;
  const stateRequire = createRequire(stateParent);
  const preparedWorkspaceUrl = (resolvedUrl: string): string => {
    if (!resolvedUrl.startsWith("file:")) return resolvedUrl;
    const resolvedPath = fileURLToPath(resolvedUrl);
    const canonicalPath = realpathSync(resolvedPath);
    const stateRelative = relative(stateEnvironment, canonicalPath);
    const modulesRelative = relative(canonicalNodeModules, canonicalPath);
    const insideState = stateRelative !== "" && !stateRelative.startsWith("../") && stateRelative !== "..";
    const insideModules = modulesRelative === "" || (!modulesRelative.startsWith("../") && modulesRelative !== "..");
    return insideState && !insideModules
      ? pathToFileURL(join(process.cwd(), stateRelative)).href
      : resolvedUrl;
  };
  registerHooks({
    resolve(specifier, context, nextResolve) {
      if (!isBarePackageSpecifier(specifier)) {
        return nextResolve(specifier, context);
      }
      if (isStateImporter(context.parentURL, canonicalNodeModules)) {
        return nextResolve(specifier, context);
      }
      if (context.conditions.includes("require")) {
        return {
          url: preparedWorkspaceUrl(pathToFileURL(stateRequire.resolve(specifier)).href),
          shortCircuit: true,
        };
      }
      try {
        const resolved = nextResolve(specifier, { ...context, parentURL: stateParent });
        return { ...resolved, url: preparedWorkspaceUrl(resolved.url), shortCircuit: true };
      } catch (error) {
        if (!isModuleNotFound(error)) throw error;
        return {
          url: preparedWorkspaceUrl(pathToFileURL(stateRequire.resolve(specifier)).href),
          shortCircuit: true,
        };
      }
    },
  });
}
