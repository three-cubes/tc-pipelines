# Common AI SDLC Adoption Playbook

Use [`new-repo-bootstrap.md`](new-repo-bootstrap.md) for a new repository and
[`../../docs/MIGRATION.md`](../../docs/MIGRATION.md) for an existing repository.
Both paths adopt the product defined by
[`ai-sdlc-product-architecture.md`](ai-sdlc-product-architecture.md).

## Shared baseline

A converged repository has:

- one `sdlc.yaml` product declaration;
- one generated `tc-sdlc.lock` for the coordinated SDLC release;
- stable Make entrypoints;
- `tc-fitness` profiles integrated into the task graph;
- thin hosted workflow callers;
- protected branch and code-owner configuration;
- immutable release and deployment evidence where applicable;
- product-specific source, tests, qualification and runtime adapters.

## Adoption order

1. Inventory the repository's projects, commands, generators, workflows and
   deployment boundaries.
2. Promote reusable behaviour into `tc-pipelines` or `tc-fitness`.
3. Add the declaration and coordinated lock.
4. Prove local preparation and affected checks.
5. Prove hosted execution of the same graph.
6. Prove immutable candidate qualification.
7. Prove deployment, PVT, rollback and cleanup where the repository deploys.
8. Remove superseded consumer orchestration.

## Canonical homes

| Concern | Home |
|---|---|
| Environment, graph, workflows, evidence and governance | `tc-pipelines` |
| Fitness engine and shared checks | `tc-fitness` |
| Product source, tests, journeys and deployment values | consumer repository |

The consumer resolver records product-specific locations. The tc-pipelines
[`RESOLVER.md`](../../RESOLVER.md) records shared locations.
