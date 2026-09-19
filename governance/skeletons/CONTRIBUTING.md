# Contributing to {{REPO}}

{{REPO}} consumes the released Three Cubes AI SDLC product.

<!-- INCLUDE: _canonical-standards-banner.md -->

## Prepare the current compatibility repository

```bash
make setup
make fix
```

`make setup` installs the repository hooks. `make fix` applies the deterministic
formatting and lock maintenance implemented by the rendered compatibility
Makefile. Commit preparation output with the change that produced it.

The coordinated `tc-sdlc` adoption change replaces these compatibility targets
with `make bootstrap`, `make prepare`, `make check` and `make check-all`. Use the
commands present in the repository Makefile until that change lands.

## Develop and verify

1. Create the Linear-named feature branch from current `main`.
2. Use `make check` for affected feedback while editing.
3. Use `make check` before release admission. After `tc-sdlc` adoption, use
   `make check-all` for the complete graph.
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
