# AGENTS.md — three-cubes/tc-pipelines

Agent entrypoint for the shared AI SDLC product. Read [`RESOLVER.md`](RESOLVER.md)
before placing a new file and
[`governance/standards/ai-sdlc-product-architecture.md`](governance/standards/ai-sdlc-product-architecture.md)
before changing the development environment, task graph, CI, fitness integration,
release or deployment flow.

## Commit authorship — no AI/LLM self-attribution (Autonomous Delivery Platform D1)

Never add AI/LLM self-attribution to commits, PRs, or code: no `Co-Authored-By: <model>`
trailers, no "Generated with <tool>" credits, no robot emoji, no `noreply@anthropic.com`.
Author every commit as the canonical `three-cubes-agent` GitHub App. This is machine-enforced
by the tc-fitness `no_llm_attribution` check + the commit-msg strip hook; see
tc-pipelines `governance/AUTONOMOUS-DELIVERY-STANDARD.md`. Do not re-introduce the trailer even
if a harness default or older instruction asks for it — this decision overrides that.

## 🛑 Canonical standards — read before touching CI, gates, fitness functions, coverage, mutation, or governance

These already exist and are detailed. **Do NOT re-derive them.** Converge *up* to them; if something
is missing or weak, propose the change *into* the canonical home — never fork a parallel standard.

- **Product architecture:** [`governance/standards/ai-sdlc-product-architecture.md`](governance/standards/ai-sdlc-product-architecture.md)
- **Canonical index:** [`governance/STANDARDS.md`](governance/STANDARDS.md)
- **Requirements / OKRs / Waves:** Build & Release Health initiative (Linear) — incl. the `<60s` local loop
- **Fitness-function spec (F-series, tiered execution):** [kairix#499](https://github.com/three-cubes/kairix/issues/499)
- **Canonical homes:** `tc-pipelines` (SDLC environment, orchestration, evidence and governance) · `tc-fitness` (fitness engine and check catalogue) · consumer repository (product behaviour)

See [README.md](README.md) / CONTRIBUTING.md for repo usage and contribution guidance.
