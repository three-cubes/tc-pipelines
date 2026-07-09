---
type: standard
status: draft
date: 2026-06-12
owner: platform
applies_to:
  - docs
  - skills
  - tools
  - capability-packages
related:
  - the canonical-patterns index
  - the skill-authoring standard
  - the capability-source-lineage-and-BOM PRD
---

# Documentation Standard

## Purpose

Documentation is a product surface. It must help the intended reader complete a task, understand a concept, make a decision, operate a system, or maintain a capability without guessing.

This standard incorporates the useful patterns from The Good Docs Project without copying its templates into runtime instructions. Use their template taxonomy and deliverable model as a reference pattern, then adapt it to each repo's authoring/runtime boundary.

## Core Rules

1. **Classify the document object first.** Do not start writing until the document type is explicit.
2. **Write for the reader and use case.** State audience, reader state, outcome and assumptions.
3. **Keep one dominant purpose per page.** Split pages that mix concept, procedure, reference and troubleshooting.
4. **Prefer progressive disclosure.** Put essential instructions in the main page; move deep background, examples and source notes into references.
5. **Make maintenance visible.** Include owner, status, last reviewed/date where the document governs behaviour.
6. **Keep lineage out of runtime prose.** Use `lineage.yaml` and source registry sidecars for source/IP traceability.
7. **Validate links and examples.** Local links must resolve; executable instructions need current command evidence where practical.

## Document Types

Use these types when creating or uplifting docs:

| Type | Use When | Required Shape | Avoid |
|---|---|---|---|
| Concept | Reader needs background, context or explanation. | Definition, context, components, relationships, when it matters. | Procedural step lists. |
| How-to | Reader needs to complete one task. | Goal, prerequisites, numbered steps, expected result, recovery. | Multiple unrelated tasks or conceptual digressions. |
| Tutorial | Reader needs guided learning through a safe example. | Learning goal, setup, walkthrough, checkpoints, cleanup. | Production runbooks or reference material. |
| Reference | Reader needs exact facts about an interface or object. | Scope, fields/commands/options, constraints, examples, version notes. | Narrative argument or broad explanation. |
| Troubleshooting | Reader has a symptom or failure. | Symptom, cause, diagnosis, fix, verification, escalation. | Generic advice without observable signals. |
| Quickstart | Reader needs the fastest first success. | Outcome, prerequisites, minimal path, success check, next links. | Complete configuration coverage. |
| Installation Guide | Reader needs to install or bootstrap. | Supported platforms, prerequisites, steps, verification, uninstall/update notes. | Product marketing or advanced operation. |
| README | Reader needs project/package orientation. | What it is, who it is for, why it matters, how to start, support/contribution path. | Full docs site content. |
| Release Notes / Changelog | Reader needs change history. | Version/date, added/changed/fixed/known issues, migration notes. | Unstructured commit dumps. |
| Glossary / Terminology | Reader needs consistent terms. | Term, definition, usage, banned/related terms. | Long concept essays. |
| Style Guide | Contributors need writing rules. | Preferred base guide, local exceptions, terminology, examples, review cadence. | Duplicating every rule from upstream guides. |
| User Persona | Authors need audience context. | Persona, needs, knowledge, tasks, constraints, success signals. | Stereotypes or unsupported assumptions. |
| Support / Escalation | Reader needs help channel clarity. | Support channels, required information, response expectations, escalation path. | Hidden ownership or vague "contact us". |

## Capability Documentation Bundle

For substantial capability packages, use a lean version of the TGDP deliverable model:

- **Template:** reusable output structure, usually under `templates/`.
- **Guide:** runtime or authoring instructions, usually `SKILL.md` or `PRD.md`.
- **Resources:** source and inspiration traceability through `lineage.yaml`, not inline lists.
- **Process:** workflow and quality gates in `SKILL.md`, `quality.yaml`, BDD or evals.
- **Example:** optional, sanitized and package-local; required only when it materially improves agent behaviour.

Do not generate all five files by default. Add each only when it removes ambiguity or supports validation.

## Uplift Workflow

1. Inventory the page or package and identify its document type.
2. Identify the reader, task, prior knowledge and success signal.
3. Split mixed-purpose pages or add cross-links between concept/procedure/reference pages.
4. Normalize headings to the selected type.
5. Remove stale path assumptions and replace host-specific locations with resolver/env-backed references.
6. Add lineage when the structure or method was adapted from source material.
7. Run local link/path checks and relevant package tests.

## Quality Gates

- Document type and reader are explicit.
- The main page has one dominant purpose.
- Headings match the document type.
- Procedure pages have prerequisites, ordered steps, expected result and recovery.
- Reference pages are scannable and field/option oriented.
- Troubleshooting pages start from observable symptoms.
- Local links resolve.
- Private paths are absent from runtime docs.
- Source lineage is sidecar-backed when external or private source material influenced the structure.

## Source Note

This standard is informed by The Good Docs Project's public template taxonomy and deliverable model. Each repo records that source in a provenance source registry (e.g. `docs/provenance/source-registry.yaml`); do not copy TGDP template text into runtime artefacts without explicit review.
