import { createRequire, registerHooks } from "node:module";
import { join, relative } from "node:path";
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
  const stateParent = pathToFileURL(join(nodeModules, ".tc-sdlc-resolver.mjs")).href;
  const stateRequire = createRequire(stateParent);
  registerHooks({
    resolve(specifier, context, nextResolve) {
      if (!isBarePackageSpecifier(specifier)) {
        return nextResolve(specifier, context);
      }
      if (isStateImporter(context.parentURL, nodeModules)) {
        return nextResolve(specifier, context);
      }
      if (context.conditions.includes("require")) {
        return {
          url: pathToFileURL(stateRequire.resolve(specifier)).href,
          shortCircuit: true,
        };
      }
      try {
        return nextResolve(specifier, { ...context, parentURL: stateParent });
      } catch (error) {
        if (!isModuleNotFound(error)) throw error;
        return {
          url: pathToFileURL(stateRequire.resolve(specifier)).href,
          shortCircuit: true,
        };
      }
    },
  });
}
