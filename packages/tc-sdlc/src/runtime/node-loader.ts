import { createRequire, registerHooks } from "node:module";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const nodeModules = process.env.TC_SDLC_NODE_MODULES;

function isBarePackageSpecifier(specifier: string): boolean {
  return !specifier.startsWith("#") && !specifier.startsWith(".") && !specifier.startsWith("/") && !/^[a-zA-Z][a-zA-Z+.-]*:/.test(specifier);
}

function isModuleNotFound(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error && (error.code === "MODULE_NOT_FOUND" || error.code === "ERR_MODULE_NOT_FOUND");
}

if (nodeModules !== undefined) {
  const stateParent = pathToFileURL(join(nodeModules, ".tc-sdlc-resolver.mjs")).href;
  const stateRequire = createRequire(stateParent);
  registerHooks({
    resolve(specifier, context, nextResolve) {
      if (!isBarePackageSpecifier(specifier)) {
        return nextResolve(specifier, context);
      }
      try {
        return nextResolve(specifier, context);
      } catch (error) {
        if (!isModuleNotFound(error)) {
          throw error;
        }
        if (context.parentURL !== undefined) {
          try {
            return nextResolve(specifier, { ...context, parentURL: stateParent });
          } catch (stateError) {
            if (!isModuleNotFound(stateError)) {
              throw stateError;
            }
            // CJS resolution does not honour the replacement parent URL.
          }
        }
        return {
          url: pathToFileURL(stateRequire.resolve(specifier)).href,
          shortCircuit: true,
        };
      }
    },
  });
}
