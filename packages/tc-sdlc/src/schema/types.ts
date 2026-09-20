import type { ExecutorContract } from "../executors/index.js";

export type ProjectDeclaration = Readonly<{
  name: string;
  root: string;
  dependsOn?: readonly string[];
}>;

export type TargetDeclaration = Readonly<{
  command?: string;
  executor?: string;
  dependsOn?: readonly string[];
  inputs?: readonly string[];
  sharedInputs?: readonly string[];
  outputs?: readonly string[];
  resources?: TaskResources;
  budget?: TaskBudget;
}>;

export type TaskResources = Readonly<{
  cpu: number;
  memoryMiB: number;
  ports: readonly number[];
  exclusive: readonly string[];
}>;

export type TaskBudget = Readonly<{
  phaseMs: number;
  noProgressMs: number;
  heartbeatMs: number;
}>;

export type SdlcToolchains = Readonly<{
  python: "3.13";
  node: "24";
  packageManager: "pnpm@11.22.0";
  uv: "0.12.5";
}>;

export type SdlcFitness = Readonly<{
  package: "three-cubes-fitness";
  version: "0.16.1";
}>;

export type SdlcDeclaration = Readonly<{
  schema: "tc.sdlc/v1";
  project: string;
  toolchains: SdlcToolchains;
  fitness: SdlcFitness;
  projects: readonly ProjectDeclaration[];
  targets: Readonly<Record<string, TargetDeclaration>>;
}>;

export type ReleaseEntry = Readonly<{
  version: string;
  package: Readonly<{
    name: "@three-cubes/tc-sdlc";
    version: string;
  }>;
  workflowCommit: string;
  imageDigest: string;
  declarationSchema: "tc.sdlc/v1";
  lockSchema: "tc.sdlc/lock/v1";
  fitness: SdlcFitness;
  toolchains: SdlcToolchains;
}>;

export type ReleaseCatalogue = Readonly<{
  schema: "tc.sdlc/release-catalogue/v1";
  release: ReleaseEntry;
}>;

export type SdlcLock = Readonly<{
  schema: "tc.sdlc/lock/v1";
  declarationDigest: string;
  catalogueDigest: string;
  release: string;
  package: ReleaseEntry["package"];
  workflowCommit: string;
  imageDigest: string;
  declarationSchema: "tc.sdlc/v1";
  fitness: ReleaseEntry["fitness"];
  toolchains: Readonly<Record<string, string>>;
}>;

export type TaskIdentity = string;

export type InputDigest = Readonly<{
  path: string;
  digest: string;
}>;

export type TaskInputDigests = Readonly<
  Record<string, readonly InputDigest[]>
>;

export type PathCaseSensitivity = "sensitive" | "insensitive";

export type GraphLockBindingOptions = Readonly<{
  pathCaseSensitivity?: PathCaseSensitivity;
}>;

export type TaskDeclaration = Readonly<{
  project: string;
  target: string;
  projectRoot: string;
  command?: string;
  executor?: string;
  dependsOn: readonly string[];
  inputs: readonly string[];
  sharedInputs?: readonly string[];
  outputs: readonly string[];
  resources?: TaskResources;
  budget?: TaskBudget;
}>;

export type GraphTask = Omit<TaskDeclaration, "resources" | "budget"> &
  Readonly<{
    key: string;
    identity: TaskIdentity;
    inputDigests: readonly InputDigest[];
    execution: ExecutorContract;
    resources: TaskResources;
    budget: TaskBudget;
  }>;

export type GraphProject = Readonly<{
  name: string;
  root: string;
  dependsOn: readonly string[];
}>;

export type SdlcGraph = Readonly<{
  schema: "tc.sdlc/graph/v1";
  declarationDigest: string;
  lockDigest: string;
  projects: readonly GraphProject[];
  tasks: readonly GraphTask[];
}>;
