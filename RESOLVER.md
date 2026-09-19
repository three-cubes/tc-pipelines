---
title: tc-pipelines resolver
audience: contributors and agents
authority: canonical location map
last_reviewed: 2026-09-19
---

# tc-pipelines Resolver

Use this map to place work in the canonical home. The product architecture is
[`governance/standards/ai-sdlc-product-architecture.md`](governance/standards/ai-sdlc-product-architecture.md).

## Product map

| Intent | Canonical home | Owns |
|---|---|---|
| Define the AI SDLC product and boundaries | `governance/standards/ai-sdlc-product-architecture.md` | Environment, task graph, fitness integration, evidence and deployment architecture. |
| Implement the shared SDLC package | `packages/tc-sdlc/` | Nx preset, executors, generators, schemas and CLI. Added during the executable-foundation tranche. |
| Build the canonical development image | `images/sdlc/` | Dev Container and OCI build inputs. Added during the executable-foundation tranche. |
| Define hosted CI orchestration | `.github/workflows/` | Credentials, protected environments, runner allocation and calls into `tc-sdlc`. |
| Define a reusable workflow step | `actions/` or `.github/actions/` | Typed GitHub composite actions retained at a hosted boundary. |
| Define release and deployment protocols | `governance/standards/ci-release-deployment-architecture.md` | Candidate, evidence, publish, deployment and PVT contracts. |
| Define shared engineering policy | `governance/standards/` | Canonical standards referenced by every repository. |
| Define executable fitness behaviour | `three-cubes/tc-fitness` | Check catalogue, evaluation semantics and structured findings. |
| Define repository adoption | `governance/standards/new-repo-bootstrap.md` and `governance/skeletons/` | Thin declarations, local commands and workflow callers. |
| Define rollout work | `docs/IMPLEMENTATION.md` | Ordered tranches, status and exit criteria. |
| Explain consumer migration | `docs/MIGRATION.md` | Adoption states, compatibility and removal conditions. |
| Explain cost controls | `docs/COST-OPTIMIZATION.md` | Measurement, caching, workflow and infrastructure cost decisions. |
| Explain a public interface | `README.md` | Concise product entrypoint and supported usage. |

## Boundary routing

Place product-specific source, tests, runtime configuration, qualification
journeys and deployment values in the consumer repository. Place reusable
execution, environment, evidence and governance behaviour here. Place shared
fitness evaluation in `tc-fitness`.

Historical release facts remain in `CHANGELOG.md`. Current architecture and
instructions come from the files in the table above.

When this map lacks a destination, update this resolver and the canonical
architecture in the same change that introduces the new surface.
