---
type: adr-index
id: ADR-INDEX
title: Cross-repo ADR index (Three Cubes paved road)
status: living
date: 2026-07-02
owner: "@three-cubes/maintainers"
scanned: 2026-07-02
related:
  - governance/decisions/ADR-POLICY.md
linear:
  - SGO-176
  - SGO-179
---

# ADR-INDEX — every ADR across the paved road, in one place

The cross-repo view that [`ADR-POLICY.md`](ADR-0002-adr-policy.md) makes possible. It lists the org-level
register (canonical here) plus every **product** ADR across tc-agent-zone, kairix, and kata by its
org-unique **alias** (`TAZ-ADR-###` / `KAI-ADR-###` / `KATA-ADR-###`), so a decision can be named
unambiguously without any repo renumbering.

**How to read it.** *Home repo / home path* is where the record lives and is owned; the alias is the
stable cross-repo handle (see `ADR-POLICY.md` §Decision). Status is the value declared in the ADR's
own frontmatter/header at the scan date (`—` = the ADR does not declare a status). This index is
**hand-maintained today**; SGO-179 adds a small in-repo walker (`docs/decisions/INDEX.md` per repo)
that generates the per-repo slice mechanically.

> **Scan basis.** Ranges reflect what is on disk in each repo's `record_dir`: tc-agent-zone
> `docs/decisions/` **ADR-001..058** (011–012 unused) at `874bf59dc`, kairix `docs/architecture/`
> **ADR-017..036** (033–034 unused, scanned 2026-07-02), kata `docs/adr/` **ADR-001..018** (016 unused)
> at `68cd395`.

## Org-level register (home: tc-pipelines)

Canonical in this repo, prefixed IDs, **not** `ADR-###`. Full statements + sources of record are in
[`ADR-POLICY.md`](ADR-0002-adr-policy.md#the-org-level-register-canonical-here):

`STD-IDENTITY` · `STD-MERGE` · `RULESET-D1` · `CODEOWNERS-D1` · `GATE-HARDEN` · `QG-CONVERGE` ·
`SONAR-HANDOFF` · `MUT-RATCHET` · `DEP-D1` · `REPO-MERGE` · `VERS-D1` · `WIF-D1..D5` · `COST-D1/2`.

Accepted target decisions under implementation are `SDLC-PRODUCT-D1`,
`SDLC-GRAPH-D1` and `SDLC-CATALOGUE-D1`. Their implementation state is recorded
separately in `ADR-POLICY.md`; they do not redefine the in-force IDs above.

## agent-platform — this log's own records

Decisions made in agent-platform itself, as distinct from the records imported
below.

| Record | Status | Title / notes |
|---|---|---|
| [ADR-0001](ADR-0001-layered-agent-platform.md) | Accepted | Layered agent platform |
| [ADR-0005](ADR-0005-merge-apac-delivery-repository.md) | Accepted | Merge kata by distributing it across the layers |
| [ADR-0046](ADR-0046-runtime-secrets-one-manifest-one-fetcher.md) | Accepted | Runtime secrets: one manifest, one fetcher, one identity per workload · decides the secret delivery and IMDS block of TAZ-ADR-006 (PLA-475) |
| [ADR-0048](ADR-0048-agent-operating-model-enforced-by-tooling.md) | Accepted | The agent operating model, enforced by tooling: stateless coordinator, parallel `pr-lane` agents, `pr-state`, split at Codex round 3, the Bash guard (PLA-581) |
| [ADR-0049](ADR-0049-standard-agentic-delivery-pattern.md) | Accepted | A standard agentic delivery pattern: Spec Kit, test-first with an independent review before every push, DORA delivery evals on Apache DevLake; supersedes PLA-627's design-first checks (PLA-628) |
| [ADR-0050](ADR-0050-tests-do-not-depend-on-host-load.md) | Accepted | Tests do not depend on host load: hang-guard timeouts, events not sleeps, no elapsed-time assertions outside soak, enforced by the `no-load-sensitive-tests` rule (PLA-682) |

## tc-agent-zone — imported into this log (alias `TAZ-ADR-###`)

tc-agent-zone's decision records at `874bf59dc` (`docs/decisions/` ADR-001 to ADR-058, with 011 and 012 unused;
`docs/adr/`; and the `docs/architecture/` pair) are resolved under PLA-437. A live record takes the next free
`ADR-NNNN` number here and keeps its `TAZ-ADR-###` alias in front matter. A superseded or moot record is not
copied and stays readable in tc-agent-zone. A record that governs a host runtime (OpenClaw or Hermes
configuration, the VM, provider policy) or a runtime memory integration moves with that runtime's ledger entry,
`runtimes` or `memory-integrations`. The migration ledger records each outcome in its `decision-records*`
entries.

| Alias | Outcome | Record | Title / notes |
|---|---|---|---|
| TAZ-ADR-001 | Planned with `runtimes` | [tc-agent-zone `docs/decisions/ADR-001-shell-cron-migration.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-001-shell-cron-migration.md) | Replace LLM-Wrapped Cron Jobs with Shell Scripts |
| TAZ-ADR-002 | Planned with `runtimes` | [tc-agent-zone `docs/decisions/ADR-002-vm-privileged-access.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-002-vm-privileged-access.md) | VM Privileged Access Management — Defence in Depth |
| TAZ-ADR-003 | Imported | [ADR-0016](ADR-0016-agent-memory-architecture-defaults.md) | Agent memory architecture defaults |
| TAZ-ADR-004 | Planned with `runtimes` | [tc-agent-zone `docs/decisions/ADR-004-openclaw-config-canonical-state.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-004-openclaw-config-canonical-state.md) | OpenClaw config canonical state |
| TAZ-ADR-005 | Imported | [ADR-0017](ADR-0017-llm-as-judge-fitness-function.md) | LLM-as-judge as an architectural fitness function for agent-UX affordance |
| TAZ-ADR-006 | Planned with `runtimes` | [tc-agent-zone `docs/decisions/ADR-006-imds-block-and-per-agent-secret-injection.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-006-imds-block-and-per-agent-secret-injection.md) | Block IMDS from containers + per-agent secret injection · runtime secret delivery and the IMDS block are now decided by [ADR-0046](ADR-0046-runtime-secrets-one-manifest-one-fetcher.md) |
| TAZ-ADR-007 | Planned with `runtimes` | [tc-agent-zone `docs/decisions/ADR-007-workspace-tier-storage-policy.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-007-workspace-tier-storage-policy.md) | Workspace-tier storage policy |
| TAZ-ADR-008 | Planned with `memory-integrations` | [tc-agent-zone `docs/decisions/ADR-008-kairix-context-bridge-plugin.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-008-kairix-context-bridge-plugin.md) | Kairix-context-bridge plugin |
| TAZ-ADR-009 | Imported | [ADR-0018](ADR-0018-policies-as-code-identities-as-text.md) | Policies become code; identities stay text |
| TAZ-ADR-010 | Imported | [ADR-0019](ADR-0019-toolpack-and-capability-pattern.md) | ToolPack manifest + capability pattern + route-test harness |
| TAZ-ADR-013 | Imported | [ADR-0020](ADR-0020-agent-constitution-conformance.md) | Agent constitution + two-tier conformance scoring |
| TAZ-ADR-014 | Superseded by [ADR-0044](ADR-0044-sonarcloud-decommission-and-in-repo-quality-ratchet.md) | [tc-agent-zone `docs/decisions/ADR-014-quality-ratchet.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-014-quality-ratchet.md) | Touch-based quality ratchet |
| TAZ-ADR-015 | Imported | [ADR-0021](ADR-0021-js-ts-tooling-baseline.md) | JS/TS tooling baseline — pnpm workspace + flat-config eslint at repo root |
| TAZ-ADR-016 | Imported | [ADR-0022](ADR-0022-python-dependency-locking-with-uv.md) | Python dependency locking with uv workspace at the repo root |
| TAZ-ADR-017 | Imported | [ADR-0023](ADR-0023-canonical-mcp-tooling.md) | Canonical MCP tooling pattern — TS-first app surface, Python for ML/embedding, shared workspace-local helpers |
| TAZ-ADR-018 | Planned with `runtimes` | [tc-agent-zone `docs/decisions/ADR-018-openclaw-plugin-install-script-policy.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-018-openclaw-plugin-install-script-policy.md) | OpenClaw plugin install-script policy — default ignore-scripts + explicit opt-in |
| TAZ-ADR-019 | Planned with `memory-integrations` | [tc-agent-zone `docs/decisions/ADR-019-kairix-memory-provider.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-019-kairix-memory-provider.md) | openclaw memory CLI surface is Kairix-backed via kairix-memory-provider plugin |
| TAZ-ADR-020 | Imported | [ADR-0024](ADR-0024-agent-identity-and-telemetry-propagation.md) | Agent identity + workload telemetry propagate via W3C Baggage with OTEL semantic conventions |
| TAZ-ADR-021 | Planned with `runtimes` | [tc-agent-zone `docs/decisions/ADR-021-openclaw-baggage-injection-patch.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-021-openclaw-baggage-injection-patch.md) | Patch openclaw locally to inject W3C Baggage on outbound LLM requests, with parallel upstream issue |
| TAZ-ADR-022 | Imported | [ADR-0025](ADR-0025-ppt-skill-stack-composition.md) | PowerPoint skill stack composition — five skills across a research → spec → render seam |
| TAZ-ADR-023 | Superseded by [ADR-0033](ADR-0033-render-from-source-template.md) | [tc-agent-zone `docs/decisions/ADR-023-ppt-rendering-tooling-python-pptx-and-pptxgenjs-hybrid.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-023-ppt-rendering-tooling-python-pptx-and-pptxgenjs-hybrid.md) | PPT rendering tooling — hybrid python-pptx (template authority) + pptxgenjs (renderer) |
| TAZ-ADR-024 | Moot (not imported) | [tc-agent-zone `docs/decisions/ADR-024-two-track-agent-team.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-024-two-track-agent-team.md) | Two-track agent team (consulting + personal) · retired in tc-agent-zone (SGO-111) |
| TAZ-ADR-025 | Imported | [ADR-0026](ADR-0026-llm-judge-ci-strategy.md) | LLM-judge CI strategy - GitHub Models live lane with per-PR cost cap |
| TAZ-ADR-026 | Planned with `runtimes` | [tc-agent-zone `docs/decisions/ADR-026-agent-retry-discipline.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-026-agent-retry-discipline.md) | Subagent retry discipline (embedded runs, transient overload) |
| TAZ-ADR-027 | Imported | [ADR-0027](ADR-0027-toolpack-phase-2-discovery-findability-linkage.md) | ToolPack Phase 2 — discovery, findability, linkage |
| TAZ-ADR-028 | Superseded by [ADR-0031](ADR-0031-sfia-subcategory-skill-ia.md) | [tc-agent-zone `docs/decisions/ADR-028-agentic-mece-reorganisation.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-028-agentic-mece-reorganisation.md) | agentic/ MECE reorganisation by professional specialism |
| TAZ-ADR-029 | Imported | [ADR-0028](ADR-0028-public-names-describe-work-not-language.md) | Public names describe work, not implementation language |
| TAZ-ADR-030 | Imported | [ADR-0029](ADR-0029-contract-coverage-of-workflow-and-config-surfaces.md) | Contract coverage of workflow and configuration surfaces |
| TAZ-ADR-031 | Imported | [ADR-0030](ADR-0030-capability-package-portable-agentic-pattern.md) | Capability Package as the portable agentic pattern |
| TAZ-ADR-032 | Imported | [ADR-0031](ADR-0031-sfia-subcategory-skill-ia.md) | SFIA subcategory-first information architecture for agentic skills |
| TAZ-ADR-033 | Planned with `runtimes` | [tc-agent-zone `docs/decisions/ADR-033-vm-disk-encryption.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-033-vm-disk-encryption.md) | VM disk encryption — platform-managed keys as the baseline for engagement-bundle VMs |
| TAZ-ADR-034 | Imported | [ADR-0032](ADR-0032-capability-runtime-cold-start.md) | Capability runtime cold-start contract |
| TAZ-ADR-035 | Planned with `runtimes` | [tc-agent-zone `docs/decisions/ADR-035-state-tier-architecture.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-035-state-tier-architecture.md) | State-tier architecture — stateful core platform, hydrate/harvest/destroy engagement containers |
| TAZ-ADR-036 | Planned with `runtimes` | [tc-agent-zone `docs/decisions/ADR-036-hermes-configuration-baseline.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-036-hermes-configuration-baseline.md) | Hermes configuration baseline: reviewed policy for generated profiles |
| TAZ-ADR-037 | Imported | [ADR-0033](ADR-0033-render-from-source-template.md) | Render decks from the source brand template (python-pptx) |
| TAZ-ADR-038 | Planned with `runtimes` | [tc-agent-zone `docs/decisions/ADR-038-session-harvest-lifecycle.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-038-session-harvest-lifecycle.md) | Session-harvest lifecycle (the T3/T4 harvest primitive, applied to agent sessions) |
| TAZ-ADR-039 | Planned with `runtimes` | [tc-agent-zone `docs/decisions/ADR-039-autonomous-agent-continuation.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-039-autonomous-agent-continuation.md) | Agent platform architecture: per-team Hermes compute VMs + vm-openclaw as the shared services & measurement plane (and the drive-to-goal operating model) |
| TAZ-ADR-040 | Imported | [ADR-0034](ADR-0034-language-aware-pre-publish-acceptance.md) | Language-aware pre-publish acceptance |
| TAZ-ADR-041 | Imported | [ADR-0035](ADR-0035-claude-capability-bundle-architecture.md) | Claude capability-bundle target architecture (consulting bundle) |
| TAZ-ADR-042 | Imported | [ADR-0036](ADR-0036-delivery-management-operating-model.md) | Delivery-management operating model (operationalising the Shape model) |
| TAZ-ADR-043 | Imported | [ADR-0037](ADR-0037-linear-reference-architecture-agent-primary.md) | Linear reference architecture for an agent-primary org (reshapes ADR-042 Increments 2–3) |
| TAZ-ADR-044 | Planned with `runtimes` | [tc-agent-zone `docs/decisions/ADR-044-operational-code-immutability-and-deploy-control-plane.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-044-operational-code-immutability-and-deploy-control-plane.md) | Operational code immutability + auditable deploy control plane |
| TAZ-ADR-045 | Imported | [ADR-0038](ADR-0038-one-capability-per-job-no-implementation-splits.md) | One capability per job: consolidate agent-facing surfaces, no implementation splits |
| TAZ-ADR-046 | Imported | [ADR-0039](ADR-0039-capability-verification-at-the-rule-layer.md) | Capability verification at the rule layer: validate ≠ runtime, one front door, env-gated live gate |
| TAZ-ADR-047 | Imported | [ADR-0040](ADR-0040-targeted-edit-renderer-adoption.md) | Targeted-edit renderer: re-implement the hands-on-deck mechanics natively, no vendored fork |
| TAZ-ADR-048 | Imported | [ADR-0041](ADR-0041-render-presentation-deck-as-first-class-mcp-capability.md) | Render a presentation deck as a first-class MCP capability (delegating binding over the render engine) |
| TAZ-ADR-049 | Planned with `memory-integrations` | [tc-agent-zone `docs/decisions/ADR-049-kairix-memory-as-a-decoupled-component.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-049-kairix-memory-as-a-decoupled-component.md) | Kairix memory as a decoupled architectural component |
| TAZ-ADR-050 | Planned with `runtimes` | [tc-agent-zone `docs/decisions/ADR-050-openclaw-to-hermes-layer1-harness-migration.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-050-openclaw-to-hermes-layer1-harness-migration.md) | Persistent Hermes cluster topology |
| TAZ-ADR-051 | Imported | [ADR-0042](ADR-0042-portable-skill-runtime-contract.md) | Portable skill runtime contract (canonical `TC_*` env + skill-relative invocation, deploy-owned platform variation) |
| TAZ-ADR-052 | Planned with `runtimes` | [tc-agent-zone `docs/decisions/ADR-052-hermes-provider-resolution-component.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-052-hermes-provider-resolution-component.md) | Deploy-owned hermes provider/connector resolution component |
| TAZ-ADR-053 | Imported | [ADR-0043](ADR-0043-agent-skill-evolution-governance.md) | Governed skill self-improvement (the runtime proposes, the repo disposes) |
| TAZ-ADR-054 | Imported | [ADR-0044](ADR-0044-sonarcloud-decommission-and-in-repo-quality-ratchet.md) | SonarCloud decommission; the quality ratchet runs in-repo |
| TAZ-ADR-055 | Planned with `runtimes` | [tc-agent-zone `docs/decisions/ADR-055-shared-vault-access-model.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-055-shared-vault-access-model.md) | Shared vault access model: group-collaborative by construction, reconciled by enforcement |
| TAZ-ADR-056 | Planned with `runtimes` | [tc-agent-zone `docs/decisions/ADR-056-content-addressed-hermes-release-evidence.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-056-content-addressed-hermes-release-evidence.md) | Content-addressed Hermes release evidence |
| TAZ-ADR-057 | Imported | [ADR-0045](ADR-0045-portable-operating-model-bundle-contracts.md) | Portable operating-model and bundle contracts |
| TAZ-ADR-058 | Superseded by [ADR-0001](ADR-0001-layered-agent-platform.md) | [tc-agent-zone `docs/decisions/ADR-058-migrate-into-agent-platform.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/ADR-058-migrate-into-agent-platform.md) | Migrate into agent-platform and serve production until cutover |
| — | Planned with `memory-integrations` | [tc-agent-zone `docs/adr/2026-04-17-mcp-first-wiring.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/adr/2026-04-17-mcp-first-wiring.md) | MCP-first architecture wiring for Kairix and Dex |
| — | Superseded by [ADR-0001](ADR-0001-layered-agent-platform.md) | [tc-agent-zone `docs/architecture/adr-012-repo-consolidation.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/architecture/adr-012-repo-consolidation.md) | Repository consolidation and layered architecture |
| — | Planned with `runtimes` | [tc-agent-zone `docs/architecture/adr-013-infrastructure-scaling-triggers.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/architecture/adr-013-infrastructure-scaling-triggers.md) | Infrastructure scaling triggers — reverse proxy + second VM |
| — | Superseded by [ADR-0001](ADR-0001-layered-agent-platform.md) | [tc-agent-zone `docs/decisions/test-coverage-decisions.md`](https://github.com/three-cubes/tc-agent-zone/blob/874bf59dc/docs/decisions/test-coverage-decisions.md) | Test coverage decisions for 0% packages · re-decided per package at import under the D1 criteria |

## kairix — `docs/architecture/` (alias `KAI-ADR-###`)

| Alias | Home path | Status | Title / notes |
|---|---|---|---|
| KAI-ADR-017 | `docs/architecture/ADR-017-deployment-architecture.md` | Active | Deployment architecture |
| KAI-ADR-018 | `docs/architecture/ADR-018-dlt-connector-framework.md` | Superseded | Adopt dlt as the connector ingestion framework · superseded by outcome — Wave 1 shipped, Waves 2–3 abandoned; dlt thesis rejected |
| KAI-ADR-019 | `docs/architecture/ADR-019-compose-resource-governance.md` | Accepted | Resource governance at the docker-compose layer |
| KAI-ADR-020 | `docs/architecture/ADR-020-connector-tick-budget-watermark.md` | Accepted | Connector tick budget + disk-watermark gating |
| KAI-ADR-021 | `docs/architecture/ADR-021-per-source-metadata-normalisation.md` | Accepted | Per-source metadata normalisation |
| KAI-ADR-022 | `docs/architecture/ADR-022-container-secret-readiness-gate.md` | Accepted | Container-level secret readiness gate · replaces `kairix.service` unit |
| KAI-ADR-023 | `docs/architecture/ADR-023-vector-index-write-architecture.md` | Accepted | Vector index write architecture (post-#335) |
| KAI-ADR-024 | `docs/architecture/ADR-024-test-pyramid-redesign.md` | Accepted | Test pyramid redesign — coverage % → defect-class coverage |
| KAI-ADR-025 | `docs/architecture/ADR-025-pipeline-observability-and-status-surface.md` | Accepted | Pipeline observability + agent-actionable status surface (Phase 1A validated) |
| KAI-ADR-026 | `docs/architecture/ADR-026-cross-cutting-primitive-abstractions.md` | Proposed | Cross-cutting primitive abstractions |
| KAI-ADR-027 | `docs/architecture/ADR-027-entity-enrichment-worker-stage.md` | Accepted | Entity-enrichment worker stage |
| KAI-ADR-028 | `docs/architecture/ADR-028-per-type-chunking-and-evaluation.md` | Accepted | Per-type chunking strategy + chunking quality evaluation |
| KAI-ADR-029 | `docs/architecture/ADR-029-agent-query-queue-and-carry-along-delivery.md` | Accepted | Agent-facing query queue + carry-along delivery · intends to supersede the ColdStart pattern (not yet effected) |
| KAI-ADR-030 | `docs/architecture/ADR-030-embedding-cache-and-atomic-save.md` | — | Persistent embedding cache + atomic vec-index save |
| KAI-ADR-031 | `docs/architecture/ADR-031-canonical-credential-naming.md` | — | Canonical credential naming + SecretsLoader |
| KAI-ADR-032 | `docs/architecture/ADR-032-oauth2-connect-flow.md` | Accepted | `kairix connect <service>` OAuth2 flow |
| KAI-ADR-035 | `docs/architecture/ADR-035-search-pipeline-async-assessment.md` | Investigation | SearchPipeline async-ification assessment |
| KAI-ADR-036 | `docs/architecture/ADR-036-entity-summary-indexing-surface.md` | Proposed | Entity-summary indexing surface |

*Numbers 033–034 are unused in this series; the record_dir series starts at 017.*

## kata — imported into this log (alias `KATA-ADR-###`)

kata's 17 ADRs at `68cd395` (ADR-001 to ADR-018; 016 unused) were resolved under
[ADR-0005](ADR-0005-merge-apac-delivery-repository.md). A live record took the next free `ADR-NNNN` number here and keeps its
`KATA-ADR-###` alias in front matter. A superseded or moot record was not copied and stays readable in kata.
The migration ledger records each outcome as entry `kata-adr-NNN`.

| Alias | Outcome | Record | Title / notes |
|---|---|---|---|
| KATA-ADR-001 | Imported | [ADR-0006](ADR-0006-portable-core-and-host-adapters.md) | Portable CORE + per-host adapters · amended by ADR-0005 |
| KATA-ADR-002 | Imported | [ADR-0007](ADR-0007-mcp-as-portable-tool-spine.md) | MCP is the portable tool spine |
| KATA-ADR-003 | Imported | [ADR-0008](ADR-0008-bok-default-binding.md) | BOK default binding = NDD .NET MCP / Foundry KS · kairix-optional rule moot (amended by ADR-0005) |
| KATA-ADR-004 | Imported | [ADR-0009](ADR-0009-capability-spec-not-skill-md.md) | The CORE primitive is a capability spec, not a SKILL.md · amended by ADR-0005 |
| KATA-ADR-005 | Superseded by [ADR-0005](ADR-0005-merge-apac-delivery-repository.md) | [kata `docs/adr/ADR-005-provenance-and-ip-boundary.md`](https://github.com/three-cubes/kata/blob/68cd395/docs/adr/ADR-005-provenance-and-ip-boundary.md) | Provenance & IP boundary |
| KATA-ADR-006 | Imported | [ADR-0010](ADR-0010-bok-ingestion-and-licensing.md) | BOK ingestion & licensing policy |
| KATA-ADR-007 | Imported | [ADR-0011](ADR-0011-canonical-artefact-catalogue.md) | Canonical artefact catalogue & operational/backlog status |
| KATA-ADR-008 | Imported | [ADR-0012](ADR-0012-operating-model-roles-and-services.md) | Operating-model role & deployable-service registries |
| KATA-ADR-009 | Imported | [ADR-0013](ADR-0013-sfia-capability-package-baseline.md) | SFIA-9 + Capability-Package pattern as the skills baseline |
| KATA-ADR-010 | Moot (not imported) | [kata `docs/adr/ADR-010-focus-internal-delivery-and-universal-eval.md`](https://github.com/three-cubes/kata/blob/68cd395/docs/adr/ADR-010-focus-internal-delivery-and-universal-eval.md) | Focus — internal agent-human delivery layer + universal eval · build priority tied to a roadmap the merge leaves behind; evals sit in assurance per ADR-0001 D2 |
| KATA-ADR-011 | Superseded by [ADR-0005](ADR-0005-merge-apac-delivery-repository.md) | [kata `docs/adr/ADR-011-kata-as-detachable-apac-delivery-bundle.md`](https://github.com/three-cubes/kata/blob/68cd395/docs/adr/ADR-011-kata-as-detachable-apac-delivery-bundle.md) | kata as a detachable APAC-delivery bundle |
| KATA-ADR-012 | Superseded by [ADR-0001](ADR-0001-layered-agent-platform.md) | [kata `docs/adr/ADR-012-quality-gate-convergence-on-three-cubes-fitness.md`](https://github.com/three-cubes/kata/blob/68cd395/docs/adr/ADR-012-quality-gate-convergence-on-three-cubes-fitness.md) | Converge kata's quality gate onto the three-cubes fitness engine · one agent-platform gate; org `QG-CONVERGE` |
| KATA-ADR-013 | Superseded by [ADR-0003](ADR-0003-merge-queue-for-product-repos.md) | [kata `docs/adr/ADR-013-autonomous-gate-enforced-merge-governance.md`](https://github.com/three-cubes/kata/blob/68cd395/docs/adr/ADR-013-autonomous-gate-enforced-merge-governance.md) | Autonomous, gate-enforced merge governance + dedicated agent identity · identity and merge rules are org `STD-IDENTITY`, `STD-MERGE`, `RULESET-D1` |
| KATA-ADR-014 | Superseded by [ADR-0005](ADR-0005-merge-apac-delivery-repository.md) | [kata `docs/adr/ADR-014-consolidate-into-apac-solutions-kata.md`](https://github.com/three-cubes/kata/blob/68cd395/docs/adr/ADR-014-consolidate-into-apac-solutions-kata.md) | Consolidate canon into a single monorepo: apac-solutions-kata |
| KATA-ADR-015 | Moot (not imported) | [kata `docs/adr/ADR-015-client-deployable-container-security-model.md`](https://github.com/three-cubes/kata/blob/68cd395/docs/adr/ADR-015-client-deployable-container-security-model.md) | Client-deployable container: security model · the apac-solutions-kata container was never built |
| KATA-ADR-016 | — | — | Number unused in kata `docs/adr/` at `68cd395` |
| KATA-ADR-017 | Imported | [ADR-0014](ADR-0014-multilingual-bridging-pipeline.md) | Multilingual bridging pipeline (C3) · not built yet |
| KATA-ADR-018 | Imported | [ADR-0015](ADR-0015-secrets-and-per-developer-endpoint.md) | Secrets & per-developer endpoint configuration |

## Collisions & follow-ups (owned elsewhere)

This index is **additive**; the fixes below are tracked on their own issues and are out of scope for
these new `governance/decisions/` files:

1. **tc-agent-zone `ADR-013` cross-directory collision** — resolved: the `docs/architecture/` pair is not
   copied; `adr-012` is superseded by [ADR-0001](ADR-0001-layered-agent-platform.md) and `adr-013` moves with
   `runtimes` (ledger `decision-records-superseded`, `runtime-decision-records`).
2. **kata `ADR-013` vs `STD-MERGE`** — resolved: [ADR-0003](ADR-0003-merge-queue-for-product-repos.md)
   supersedes kata ADR-013, so it was not imported (ledger `adr-autonomous-gate-enforced-merge-governance`).
3. **Per-repo `INDEX.md` walkers** — SGO-179 adds a small generator so each repo emits its own slice
   of this table mechanically, keeping the hand-maintained view honest.
