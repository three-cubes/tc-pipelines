import { readFileSync } from "node:fs";

import {
  Ajv2020,
  type AnySchema,
  type ErrorObject,
  type ValidateFunction,
} from "ajv/dist/2020.js";

import { SdlcError } from "../errors.js";

const ajv = new Ajv2020({ allErrors: true, strict: true });

function readSchema(name: string): AnySchema {
  return JSON.parse(
    readFileSync(new URL(`../schemas/${name}`, import.meta.url), "utf8"),
  ) as AnySchema;
}

const validators = new Map<string, ValidateFunction>();

function validator(name: string): ValidateFunction {
  const existing = validators.get(name);
  if (existing !== undefined) {
    return existing;
  }
  const compiled = ajv.compile(readSchema(name));
  validators.set(name, compiled);
  return compiled;
}

function describe(errors: ErrorObject[] | null | undefined): string {
  return (errors ?? [])
    .map((error) => `${error.instancePath || "/"} ${error.message ?? "is invalid"}`)
    .join("; ");
}

export function assertSchema<T>(name: string, value: unknown, kind: string): asserts value is T {
  const validate = validator(name);
  if (!validate(value)) {
    throw new SdlcError("SCHEMA_INVALID", `${kind} schema validation failed: ${describe(validate.errors)}`);
  }
}
