import * as sdlc from "../dist/index.js";

import { describe, expect, test } from "vitest";

const release = {
  version: "2.2.0",
  package: {
    name: "@three-cubes/tc-sdlc",
    version: "2.2.0",
  },
  workflowCommit: "1234567890abcdef1234567890abcdef12345678",
  imageDigest:
    "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  declarationSchema: "tc.sdlc/v1",
  lockSchema: "tc.sdlc/lock/v1",
  fitness: {
    package: "three-cubes-fitness",
    version: "0.17.1",
  },
  toolchains: {
    node: "24",
    packageManager: "pnpm@11.22.0",
    python: "3.13",
    uv: "0.12.5",
  },
  bootstrap: sdlc.CANONICAL_SDLC_BOOTSTRAP,
} as const;

const declarationFitness = {
  package: "three-cubes-fitness",
  config: "pyproject.toml",
  profiles: { full: "full" },
} as const;

function declaration(projects: readonly Record<string, unknown>[]) {
  return {
    schema: "tc.sdlc/v1",
    project: "graph-fixture",
    toolchains: release.toolchains,
    fitness: declarationFitness,
    projects,
    targets: {
      check: {
        command: "make check",
        mode: "evaluate",
        trustBoundary: "portable",
        dependsOn: ["prepare"],
        inputs: ["shared/config.json"],
      },
      prepare: {
        command: "make prepare",
        mode: "prepare",
        trustBoundary: "portable",
      },
    },
  } as const;
}

function emptyTaskInputs(input: ReturnType<typeof declaration>) {
  return Object.fromEntries(
    input.projects.flatMap((project) =>
      Object.keys(input.targets).map((target) => [`${project.name}:${target}`, []]),
    ),
  );
}

function lockedGraph(
  input: ReturnType<typeof declaration>,
  inputs: Readonly<Record<string, readonly Record<string, string>[]>> =
    emptyTaskInputs(input),
  options?: Readonly<{ pathCaseSensitivity: "sensitive" | "insensitive" }>,
) {
  const catalogue = sdlc.createReleaseCatalogue(release);
  const lock = sdlc.resolveLock(input as never, catalogue);
  const boundLock = (sdlc as Record<string, any>).bindGraphLock(
    input,
    lock,
    catalogue,
    inputs,
    options,
  );
  return {
    graph: (sdlc as Record<string, any>).buildGraph(input, boundLock),
    serialise: (sdlc as Record<string, any>).serialiseGraph as (value: unknown) => string,
  };
}

describe("tc-sdlc graph", () => {
  test("expands the repository-scoped fitness executor exactly once", () => {
    const input = {
      ...declaration([
        { name: "api", root: "services/api" },
        { name: "web", root: "apps/web" },
      ]),
      targets: {
        ...declaration([{ name: "api", root: "services/api" }]).targets,
        fitness: {
          executor: "tc-sdlc:fitness",
          profile: "full",
          scope: "repository",
          mode: "evaluate",
          trustBoundary: "portable",
          evidence: [{ path: "fitness.json", mediaType: "application/json" }],
          inputs: ["pyproject.toml"],
        },
      },
    } as const;

    const { graph } = lockedGraph(input as never, {
      "api:check": [],
      "api:prepare": [],
      "web:check": [],
      "web:prepare": [],
      "graph-fixture:fitness": [],
    });

    expect(graph.tasks.filter((task) => task.target === "fitness").map((task) => task.key)).toEqual([
      "graph-fixture:fitness",
    ]);
  });

  test("requires task mode and trust boundary and binds both into identity", () => {
    const input = {
      ...declaration([{ name: "api", root: "services/api" }]),
      targets: {
        prepare: {
          command: "make prepare",
          mode: "prepare",
          trustBoundary: "portable",
        },
        check: {
          command: "make check",
          mode: "evaluate",
          trustBoundary: "hosted",
        },
      },
    } as const;
    const portable = lockedGraph(input as never).graph;
    const changed = lockedGraph({
      ...input,
      targets: {
        ...input.targets,
        check: { ...input.targets.check, trustBoundary: "live" },
      },
    } as never).graph;

    expect(portable.tasks.map((task: Record<string, unknown>) => [
      task.key,
      task.mode,
      task.trustBoundary,
    ])).toEqual([
      ["api:check", "evaluate", "hosted"],
      ["api:prepare", "prepare", "portable"],
    ]);
    expect(portable.tasks[0]?.identity).not.toBe(changed.tasks[0]?.identity);

    const missing = structuredClone(input) as Record<string, any>;
    delete missing.targets.check.mode;
    expect(() => lockedGraph(missing as never)).toThrowError(
      expect.objectContaining({ code: "SCHEMA_INVALID" }),
    );
  });

  test("serialises equivalent project order and path syntax to identical canonical bytes", () => {
    const first = lockedGraph(
      declaration([
        { name: "web", root: "apps/web", dependsOn: ["api"] },
        { name: "api", root: "services/api" },
      ]),
    );
    const second = lockedGraph(
      declaration([
        { name: "api", root: "services\\api" },
        { name: "web", root: "apps\\web", dependsOn: ["api"] },
      ]),
    );

    const firstBytes = first.serialise(first.graph);
    const secondBytes = second.serialise(second.graph);

    expect(firstBytes).toBe(secondBytes);
    expect(firstBytes.endsWith("\n")).toBe(true);
    expect(firstBytes.endsWith("\n\n")).toBe(false);
    expect(first.graph.tasks.map((task: { key: string }) => task.key)).toEqual([
      "api:check",
      "api:prepare",
      "web:check",
      "web:prepare",
    ]);
  });

  test("task identity ignores path syntax, input order and operational metadata", () => {
    const identify = (sdlc as Record<string, any>).taskIdentity as (
      task: Record<string, unknown>,
      inputs: readonly Record<string, string>[],
      lockDigest: string,
    ) => string;
    const lockDigest =
      "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    const first = identify(
      {
        project: "api",
        target: "check",
        projectRoot: "services/api",
        command: "make check",
        dependsOn: ["api:prepare", "schema:check"],
        inputs: ["shared/config.json", "services/api/src"],
        outputs: ["services/api/report.json"],
        checkoutRoot: "/private/tmp/first",
        workerCount: 2,
        traversalOrder: 1,
      },
      [
        {
          path: "services/api/src/main.ts",
          digest:
            "sha256:2222222222222222222222222222222222222222222222222222222222222222",
        },
        {
          path: "shared/config.json",
          digest:
            "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        },
      ],
      lockDigest,
    );
    const second = identify(
      {
        project: "api",
        target: "check",
        projectRoot: "services\\api",
        command: "make check",
        dependsOn: ["schema:check", "api:prepare"],
        inputs: ["services\\api\\src", "shared\\config.json"],
        outputs: ["services\\api\\report.json"],
        checkoutRoot: "D:\\second",
        workerCount: 64,
        traversalOrder: 99,
      },
      [
        {
          path: "shared\\config.json",
          digest:
            "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        },
        {
          path: "services\\api\\src\\main.ts",
          digest:
            "sha256:2222222222222222222222222222222222222222222222222222222222222222",
        },
      ],
      lockDigest,
    );

    expect(first).toMatch(/^sha256:[a-f0-9]{64}$/);
    expect(first).toBe(second);
  });

  test("task identity binds semantic declaration, input digests and lock digest", () => {
    const identify = (sdlc as Record<string, any>).taskIdentity as (
      task: Record<string, unknown>,
      inputs: readonly Record<string, string>[],
      lockDigest: string,
    ) => string;
    const task = {
      project: "api",
      target: "check",
      projectRoot: "services/api",
      command: "make check",
      dependsOn: [],
      inputs: ["src/**"],
      outputs: [],
    };
    const lockDigest =
      "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    const identity = identify(
      task,
      [{
        path: "services/api/src/main.ts",
        digest:
          "sha256:1111111111111111111111111111111111111111111111111111111111111111",
      }],
      lockDigest,
    );

    expect(
      new Set([
        identity,
        identify(
          { ...task, command: "make check-all" },
          [{
            path: "services/api/src/main.ts",
            digest:
              "sha256:1111111111111111111111111111111111111111111111111111111111111111",
          }],
          lockDigest,
        ),
        identify(
          task,
          [{
            path: "services/api/src/main.ts",
            digest:
              "sha256:2222222222222222222222222222222222222222222222222222222222222222",
          }],
          lockDigest,
        ),
        identify(
          task,
          [{
            path: "services/api/src/main.ts",
            digest:
              "sha256:1111111111111111111111111111111111111111111111111111111111111111",
          }],
          "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        ),
      ]).size,
    ).toBe(4);
  });

  test.each([
    ["absolute project root", { projectRoot: "/tmp/api" }, []],
    ["traversing declared input", { inputs: ["../outside"] }, []],
    [
      "traversing digested input",
      {},
      [{
        path: "../outside",
        digest:
          "sha256:1111111111111111111111111111111111111111111111111111111111111111",
      }],
    ],
  ])("rejects %s when computing task identity", (_name, taskChange, inputs) => {
    const task = {
      project: "api",
      target: "check",
      projectRoot: "services/api",
      command: "make check",
      dependsOn: [],
      inputs: ["src/**"],
      outputs: [],
      ...taskChange,
    };

    expect(() =>
      (sdlc as Record<string, any>).taskIdentity(
        task,
        inputs,
        "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      ),
    ).toThrowError(expect.objectContaining({ code: "GRAPH_PATH_INVALID" }));
  });

  test.each([
    [
      "duplicate project identity",
      declaration([
        { name: "api", root: "services/api" },
        { name: "api", root: "services/other" },
      ]),
      "GRAPH_DUPLICATE_IDENTITY",
    ],
    [
      "case-ambiguous project identity",
      declaration([
        { name: "api", root: "services/api" },
        { name: "API", root: "services/other" },
      ]),
      "GRAPH_PLATFORM_AMBIGUITY",
    ],
    [
      "case-ambiguous target identity",
      {
        ...declaration([{ name: "api", root: "services/api" }]),
        targets: {
          check: { command: "make check", mode: "evaluate", trustBoundary: "portable" },
          CHECK: { command: "make other-check", mode: "evaluate", trustBoundary: "portable" },
        },
      },
      "GRAPH_PLATFORM_AMBIGUITY",
    ],
    [
      "unknown project dependency",
      declaration([{ name: "api", root: "services/api", dependsOn: ["missing"] }]),
      "GRAPH_UNKNOWN_DEPENDENCY",
    ],
    [
      "unknown target dependency",
      {
        ...declaration([{ name: "api", root: "services/api" }]),
        targets: { check: { command: "make check", mode: "evaluate", trustBoundary: "portable", dependsOn: ["missing"] } },
      },
      "GRAPH_UNKNOWN_DEPENDENCY",
    ],
    [
      "project dependency cycle",
      declaration([
        { name: "api", root: "services/api", dependsOn: ["web"] },
        { name: "web", root: "apps/web", dependsOn: ["api"] },
      ]),
      "GRAPH_CYCLE",
    ],
    [
      "target dependency cycle",
      {
        ...declaration([{ name: "api", root: "services/api" }]),
        targets: {
          check: { command: "make check", mode: "evaluate", trustBoundary: "portable", dependsOn: ["prepare"] },
          prepare: { command: "make prepare", mode: "prepare", trustBoundary: "portable", dependsOn: ["check"] },
        },
      },
      "GRAPH_CYCLE",
    ],
    [
      "absolute POSIX path",
      declaration([{ name: "api", root: "/services/api" }]),
      "GRAPH_PATH_INVALID",
    ],
    [
      "absolute Windows path",
      declaration([{ name: "api", root: "C:\\services\\api" }]),
      "GRAPH_PATH_INVALID",
    ],
    [
      "parent traversal",
      declaration([{ name: "api", root: "services/../api" }]),
      "GRAPH_PATH_INVALID",
    ],
    [
      "target input traversal",
      {
        ...declaration([{ name: "api", root: "services/api" }]),
        targets: {
          check: { command: "make check", mode: "evaluate", trustBoundary: "portable", inputs: ["../../outside"] },
        },
      },
      "GRAPH_PATH_INVALID",
    ],
    [
      "case-ambiguous project roots",
      declaration([
        { name: "api", root: "services/API" },
        { name: "web", root: "services/api" },
      ]),
      "GRAPH_PLATFORM_AMBIGUITY",
    ],
    [
      "platform-equivalent target input paths",
      {
        ...declaration([{ name: "api", root: "services/api" }]),
        targets: {
          check: {
            command: "make check",
            mode: "evaluate",
            trustBoundary: "portable",
            inputs: ["src/config.json", "src\\config.json"],
          },
        },
      },
      "GRAPH_PLATFORM_AMBIGUITY",
    ],
  ])("rejects %s before graph execution", (_name, input, code) => {
    expect(() => lockedGraph(input as ReturnType<typeof declaration>)).toThrowError(
      expect.objectContaining({ code }),
    );
  });

  test("rejects a lock from a different declaration before graph planning", () => {
    const initial = declaration([{ name: "api", root: "services/api" }]);
    const catalogue = sdlc.createReleaseCatalogue(release);
    const staleLock = sdlc.resolveLock(initial as never, catalogue);
    const boundLock = (sdlc as Record<string, any>).bindGraphLock(
      initial,
      staleLock,
      catalogue,
      emptyTaskInputs(initial),
    );
    const changed = declaration([{ name: "api", root: "services/renamed-api" }]);

    expect(() =>
      (sdlc as Record<string, any>).buildGraph(changed, boundLock),
    ).toThrowError(expect.objectContaining({ code: "LOCK_STALE" }));
  });

  test("emitted graph task identity binds canonical content input digests", () => {
    const input = {
      ...declaration([{ name: "api", root: "services/api" }]),
      targets: {
        check: { command: "make check", mode: "evaluate", trustBoundary: "portable", inputs: ["src/**"] },
      },
    } as const;
    const firstInputs = {
      "api:check": [
        {
          path: "services/api/src/main.ts",
          digest:
            "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        },
      ],
    };
    const secondInputs = {
      "api:check": [
        {
          path: "services\\api\\src\\main.ts",
          digest:
            "sha256:2222222222222222222222222222222222222222222222222222222222222222",
        },
      ],
    };
    const equivalentInputs = {
      "api:check": [
        {
          path: "services\\api\\src\\main.ts",
          digest:
            "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        },
      ],
    };

    const first = lockedGraph(input as never, firstInputs).graph.tasks[0];
    const second = lockedGraph(input as never, secondInputs).graph.tasks[0];
    const equivalent = lockedGraph(
      input as never,
      equivalentInputs,
    ).graph.tasks[0];

    expect(first.identity).not.toBe(second.identity);
    expect(first.identity).toBe(equivalent.identity);
    expect(first.inputDigests).toEqual([
      {
        path: "services/api/src/main.ts",
        digest:
          "sha256:1111111111111111111111111111111111111111111111111111111111111111",
      },
    ]);
    expect(second.inputDigests).toEqual([
      {
        path: "services/api/src/main.ts",
        digest:
          "sha256:2222222222222222222222222222222222222222222222222222222222222222",
      },
    ]);
  });

  test.each([
    ["missing task inventory", {}],
    ["unknown task inventory", { "api:check": [], "ghost:check": [] }],
    [
      "non-canonical content digest",
      {
        "api:check": [
          { path: "services/api/src/main.ts", digest: "sha256:not-canonical" },
        ],
      },
    ],
    [
      "unconsumed content path",
      {
        "api:check": [
          {
            path: "services/api/other.txt",
            digest:
              "sha256:1111111111111111111111111111111111111111111111111111111111111111",
          },
        ],
      },
    ],
  ])("rejects %s at the pre-execution digest boundary", (_name, inputs) => {
    const input = {
      ...declaration([{ name: "api", root: "services/api" }]),
      targets: {
        check: { command: "make check", mode: "evaluate", trustBoundary: "portable", inputs: ["src/**"] },
      },
    } as const;

    expect(() => lockedGraph(input as never, inputs)).toThrowError(
      expect.objectContaining({ code: "GRAPH_INPUT_DIGEST_INVALID" }),
    );
  });

  test("requires explicit lock authority and content inputs for graph planning", () => {
    const input = declaration([{ name: "api", root: "services/api" }]);
    const catalogue = sdlc.createReleaseCatalogue(release);
    const lock = sdlc.resolveLock(input as never, catalogue);

    expect(() =>
      (sdlc as Record<string, any>).buildGraph(input, lock),
    ).toThrowError(expect.objectContaining({ code: "GRAPH_CONTEXT_INVALID" }));
  });

  test("builds through the public two-argument graph API after binding planning authority", () => {
    const input = declaration([{ name: "api", root: "services/api" }]);
    const catalogue = sdlc.createReleaseCatalogue(release);
    const lock = sdlc.resolveLock(input as never, catalogue);
    const boundLock = (sdlc as Record<string, any>).bindGraphLock(
      input,
      lock,
      catalogue,
      emptyTaskInputs(input),
    );

    const graph = (sdlc as Record<string, any>).buildGraph(input, boundLock);

    expect(graph.tasks.map((task: { key: string }) => task.key)).toEqual([
      "api:check",
      "api:prepare",
    ]);
  });

  test.each([
    ["catalogue digest", (lock: Record<string, any>) => {
      lock.catalogueDigest =
        "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    }],
    ["release", (lock: Record<string, any>) => {
      lock.release = "9.9.9";
    }],
    ["package version", (lock: Record<string, any>) => {
      lock.package.version = "9.9.9";
    }],
    ["workflow commit", (lock: Record<string, any>) => {
      lock.workflowCommit = "abcdef1234567890abcdef1234567890abcdef12";
    }],
    ["image digest", (lock: Record<string, any>) => {
      lock.imageDigest =
        "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    }],
  ])("rejects a schema-valid hand edit to lock %s", (_name, sabotage) => {
    const input = declaration([{ name: "api", root: "services/api" }]);
    const catalogue = sdlc.createReleaseCatalogue(release);
    const lock = (sdlc as Record<string, any>).bindGraphLock(
      input,
      sdlc.resolveLock(input as never, catalogue),
      catalogue,
      emptyTaskInputs(input),
    ) as Record<
      string,
      any
    >;
    sabotage(lock);

    expect(() =>
      (sdlc as Record<string, any>).buildGraph(input, lock),
    ).toThrowError(expect.objectContaining({ code: "LOCK_STALE" }));
  });

  test.each([
    [
      "direct change, prerequisites and downstream consumers",
      ["services/api/src/main.ts"],
      ["api:test", "schema:test", "web:test"],
    ],
    [
      "Windows path syntax",
      ["services\\api\\src\\main.ts"],
      ["api:test", "schema:test", "web:test"],
    ],
    [
      "generated-output propagation",
      ["packages/schema/spec.yaml"],
      [
        "api:check",
        "api:generate",
        "schema:check",
        "schema:generate",
        "web:check",
        "web:generate",
      ],
    ],
    [
      "declared shared input",
      ["shared/config.json"],
      ["api:check", "docs:check", "schema:check", "web:check"],
    ],
    ["declaration invalidation", ["sdlc.yaml"], "all"],
    ["lock invalidation", ["tc-sdlc.lock"], "all"],
    ["unrelated change", ["unrelated/notes.txt"], []],
  ])("selects affected tasks for %s", (_name, changedPaths, expected) => {
    const input = {
      ...declaration([
        { name: "web", root: "apps/web", dependsOn: ["api"] },
        { name: "docs", root: "docs" },
        { name: "schema", root: "packages/schema" },
        { name: "api", root: "services/api", dependsOn: ["schema"] },
      ]),
      targets: {
        check: {
          command: "make check",
          mode: "evaluate",
          trustBoundary: "portable",
          inputs: ["generated.ts"],
          sharedInputs: ["shared/config.json"],
        },
        generate: {
          command: "make generate",
          mode: "prepare",
          trustBoundary: "portable",
          inputs: ["spec.yaml"],
          outputs: ["generated.ts"],
        },
        test: {
          command: "make test",
          mode: "evaluate",
          trustBoundary: "portable",
          inputs: ["src/**"],
        },
      },
    } as const;
    const { graph } = lockedGraph(input as never);
    const identities = (sdlc as Record<string, any>).selectAffected(
      graph,
      changedPaths,
    ) as readonly string[];
    const selectedKeys = graph.tasks
      .filter((task: { identity: string }) => identities.includes(task.identity))
      .map((task: { key: string }) => task.key);
    const allKeys = graph.tasks.map((task: { key: string }) => task.key);

    expect(selectedKeys).toEqual(expected === "all" ? allKeys : expected);
  });

  test("closes affected selection over transitive target and project prerequisites", () => {
    const input = {
      ...declaration([
        { name: "web", root: "apps/web", dependsOn: ["api"] },
        { name: "docs", root: "docs" },
        { name: "api", root: "services/api", dependsOn: ["schema"] },
        { name: "schema", root: "packages/schema" },
      ]),
      targets: {
        prepare: { command: "make prepare", mode: "prepare", trustBoundary: "portable", inputs: ["prepare.trigger"] },
        build: {
          command: "make build",
          mode: "evaluate",
          trustBoundary: "portable",
          dependsOn: ["prepare"],
          inputs: ["build.trigger"],
        },
        check: {
          command: "make check",
          mode: "evaluate",
          trustBoundary: "portable",
          dependsOn: ["build"],
          inputs: ["check.trigger"],
        },
      },
    } as const;
    const { graph } = lockedGraph(input as never);

    const identities = (sdlc as Record<string, any>).selectAffected(graph, [
      "apps/web/check.trigger",
    ]) as readonly string[];
    const selectedKeys = graph.tasks
      .filter((task: { identity: string }) => identities.includes(task.identity))
      .map((task: { key: string }) => task.key);

    expect(selectedKeys).toEqual([
      "api:build",
      "api:check",
      "api:prepare",
      "schema:build",
      "schema:check",
      "schema:prepare",
      "web:build",
      "web:check",
      "web:prepare",
    ]);
  });

  test("uses Linux-sensitive and macOS/Windows-insensitive changed-path matching", () => {
    const input = {
      ...declaration([{ name: "api", root: "services/api" }]),
      targets: {
        test: { command: "make test", mode: "evaluate", trustBoundary: "portable", inputs: ["src/**"] },
      },
    } as const;
    const sensitive = lockedGraph(
      input as never,
      emptyTaskInputs(input as never),
      { pathCaseSensitivity: "sensitive" },
    ).graph;
    const insensitive = lockedGraph(
      input as never,
      emptyTaskInputs(input as never),
      { pathCaseSensitivity: "insensitive" },
    ).graph;
    const native = lockedGraph(input as never).graph;
    const select = (graph: typeof sensitive, path: string) =>
      (sdlc as Record<string, any>).selectAffected(graph, [path]) as readonly string[];

    expect(select(sensitive, "services/api/src/main.ts")).toEqual([
      sensitive.tasks[0]?.identity,
    ]);
    expect(select(sensitive, "Services/API/SRC/main.ts")).toEqual([]);
    expect(select(sensitive, "SDLC.YAML")).toEqual([]);
    expect(select(insensitive, "Services/API/SRC/main.ts")).toEqual([
      insensitive.tasks[0]?.identity,
    ]);
    expect(select(insensitive, "SDLC.YAML")).toEqual([
      insensitive.tasks[0]?.identity,
    ]);
    expect(select(native, "Services/API/SRC/main.ts")).toEqual(
      process.platform === "darwin" || process.platform === "win32"
        ? [native.tasks[0]?.identity]
        : [],
    );
    expect((sdlc as Record<string, any>).serialiseGraph(sensitive)).toBe(
      (sdlc as Record<string, any>).serialiseGraph(insensitive),
    );
  });

  test.each([
    ["wildcard output to literal input", "generated/**", "generated/client.ts"],
    ["literal output to wildcard input", "generated/client.ts", "generated/**"],
  ])("propagates generated %s", (_name, output, consumerInput) => {
    const input = {
      ...declaration([{ name: "api", root: "services/api" }]),
      targets: {
        check: { command: "make check", mode: "evaluate", trustBoundary: "portable", inputs: [consumerInput] },
        generate: {
          command: "make generate",
          mode: "prepare",
          trustBoundary: "portable",
          inputs: ["spec.yaml"],
          outputs: [output],
        },
      },
    } as const;
    const { graph } = lockedGraph(input as never);
    const identities = (sdlc as Record<string, any>).selectAffected(graph, [
      "services/api/spec.yaml",
    ]) as readonly string[];

    expect(
      graph.tasks
        .filter((task: { identity: string }) => identities.includes(task.identity))
        .map((task: { key: string }) => task.key),
    ).toEqual(["api:check", "api:generate"]);
  });

  test.each(["/outside/file.ts", "C:\\outside\\file.ts", "src/../../outside.ts"])(
    "rejects unsafe changed path %s",
    (changedPath) => {
      const { graph } = lockedGraph(
        declaration([{ name: "api", root: "services/api" }]),
      );

      expect(() =>
        (sdlc as Record<string, any>).selectAffected(graph, [changedPath]),
      ).toThrowError(expect.objectContaining({ code: "GRAPH_PATH_INVALID" }));
    },
  );

  test("carries one unambiguous executor contract into every graph task", () => {
    const input = {
      ...declaration([{ name: "api", root: "services/api" }]),
      targets: {
        check: { executor: "tc-sdlc:affected-check", mode: "evaluate", trustBoundary: "portable" },
        prepare: { command: "make prepare", mode: "prepare", trustBoundary: "portable" },
      },
    } as const;
    const { graph } = lockedGraph(input as never);

    expect(
      graph.tasks.map((task: { key: string; execution: unknown }) => [
        task.key,
        task.execution,
      ]),
    ).toEqual([
      ["api:check", { kind: "executor", executor: "tc-sdlc:affected-check" }],
      ["api:prepare", { kind: "command", command: "make prepare" }],
    ]);

    const ambiguous = {
      ...input,
      targets: {
        check: {
          command: "make check",
          executor: "tc-sdlc:affected-check",
          mode: "evaluate",
          trustBoundary: "portable",
        },
      },
    } as const;
    expect(() => lockedGraph(ambiguous as never)).toThrowError(
      expect.objectContaining({ code: "GRAPH_EXECUTOR_INVALID" }),
    );
  });
});
