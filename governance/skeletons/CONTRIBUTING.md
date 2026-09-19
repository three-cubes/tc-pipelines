# Contributing to {{REPO}}

{{REPO}} consumes the released Three Cubes AI SDLC product.

<!-- INCLUDE: _canonical-standards-banner.md -->

## Prepare the repository

```bash
make bootstrap
make prepare
```

Bootstrap materialises the released environment and dependencies. Preparation
applies deterministic formatting, generators, lock and manifest maintenance.
Commit preparation output with the change that produced it.

Repositories still migrating to `tc-sdlc` use the current commands documented
in their Makefile until the coordinated adoption change lands.

## Develop and verify

1. Create the Linear-named feature branch from current `main`.
2. Use `make check` for affected feedback while editing.
3. Use `make check-all` before release admission or where the change surface
   requires the complete graph.
4. Reconcile with current `main` and repeat the required graph.
5. Open one coherent PR through the trusted GitHub App path.
6. Resolve review conversations and retain complete verification evidence.

Evidence names the tested commit, SDLC lock, tasks, terminal result and generated
receipts. Container changes also name the qualified image digest.

## Product boundaries

- `tc-pipelines` owns the released environment, graph, hosted orchestration,
  evidence and governance product.
- `tc-fitness` owns fitness evaluation and the shared check catalogue.
- this repository owns product source, tests, generators, qualification journeys
  and deployment values.

Promote reusable behaviour into its canonical home, release it, then upgrade
the consumer through one coordinated SDLC release.

## Identity and review

Local commits use canonical `three-cubes-agent[bot]` metadata and contain no AI
or model attribution. Remote writes use short-lived GitHub App credentials held
by the trusted broker or hosted workflow. Ordinary product changes merge on
green; control-plane changes receive the configured human code-owner review.
