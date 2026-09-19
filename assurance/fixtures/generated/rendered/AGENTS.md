# AGENTS.md — three-cubes/assurance-generated

This file governs contributors editing the repository. Runtime agent behaviour
lives in the runtime artefact.

## 🛑 Canonical standards — read before touching CI, gates, fitness functions, coverage, mutation, or governance

These already exist and are detailed. **Do NOT re-derive them.** Converge *up* to them; if something
is missing or weak, propose the change *into* the canonical home — never fork a parallel standard.

- **Product architecture:** [`tc-pipelines/governance/standards/ai-sdlc-product-architecture.md`](https://github.com/three-cubes/tc-pipelines/blob/main/governance/standards/ai-sdlc-product-architecture.md)
- **Canonical index:** [`tc-pipelines/governance/STANDARDS.md`](https://github.com/three-cubes/tc-pipelines/blob/main/governance/STANDARDS.md)
- **Requirements / OKRs / Waves:** Build & Release Health initiative (Linear) — incl. the `<60s` local loop
- **Fitness-function spec (F-series, tiered execution):** [tc-fitness](https://github.com/three-cubes/tc-fitness)
- **Canonical homes:** `tc-pipelines` (SDLC environment, orchestration, evidence and governance) · `tc-fitness` (fitness engine and check catalogue) · consumer repository (product behaviour)

## Work here

- Read [`RESOLVER.md`](RESOLVER.md) before adding a file.
- Use the stable Make commands documented in [`CONTRIBUTING.md`](CONTRIBUTING.md).
- Keep shared SDLC behaviour in `tc-pipelines` and shared fitness evaluation in
  `tc-fitness`.
- Keep product source, tests, qualification and deployment values in this repo.
- Record complete terminal evidence for verification, release and deployment.

Create commits with canonical `three-cubes-agent[bot]` metadata and no AI or
model attribution. Use the trusted GitHub App path for remote writes.
