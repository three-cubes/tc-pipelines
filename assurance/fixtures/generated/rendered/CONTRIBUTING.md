# Contributing to three-cubes/assurance-generated

three-cubes/assurance-generated consumes the released Three Cubes AI SDLC product.

## 🛑 Canonical standards — read before touching CI, gates, fitness functions, coverage, mutation, or governance

These already exist and are detailed. **Do NOT re-derive them.** Converge *up* to them; if something
is missing or weak, propose the change *into* the canonical home — never fork a parallel standard.

- **Product architecture:** [`tc-pipelines/governance/standards/ai-sdlc-product-architecture.md`](https://github.com/three-cubes/tc-pipelines/blob/main/governance/standards/ai-sdlc-product-architecture.md)
- **Canonical index:** [`tc-pipelines/governance/STANDARDS.md`](https://github.com/three-cubes/tc-pipelines/blob/main/governance/STANDARDS.md)
- **Requirements / OKRs / Waves:** Build & Release Health initiative (Linear) — incl. the `<60s` local loop
- **Fitness-function spec (F-series, tiered execution):** [tc-fitness](https://github.com/three-cubes/tc-fitness)
- **Canonical homes:** `tc-pipelines` (SDLC environment, orchestration, evidence and governance) · `tc-fitness` (fitness engine and check catalogue) · consumer repository (product behaviour)

## Prepare the current compatibility repository

```bash
make setup
make prepare
```

`make setup` installs the repository hooks. `make prepare` applies deterministic
formatting and lock maintenance. `make check` runs preparation before evaluation.
Commit preparation output with the change that produced it.

The coordinated `tc-sdlc` adoption adds `make bootstrap` and `make check-all`
while retaining `make prepare` and `make check`.

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
