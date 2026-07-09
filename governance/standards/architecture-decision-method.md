# Architecture Decision Method — how a decision is made, not just how it is filed

> This standard governs the **method**: how a design or architecture decision is researched,
> shaped, and justified before it is recorded. The **mechanics** — where an ADR lives, its id,
> filename, frontmatter, and namespacing — are the [ADR-POLICY](../decisions/ADR-POLICY.md), not
> here. A well-formatted ADR that skips the method is still a bad decision.

## When a decision needs a record

Write a decision record when a choice is **hard to reverse** or **affects more than one area**:
a data model, an external or cross-repo contract, a security or trust boundary, a new runtime
dependency, a layering/ownership rule, or anything a future agent would otherwise re-litigate.
A two-way door with a local blast radius does not need an ADR — just do it and let the diff
carry the history.

## The method (in order)

1. **Verify the real state first.** Read the live system / the actual runtime / the current
   config before encoding a design. Do not design against an assumed stack — spike or interrogate
   the real one. Encoding an invented default (a model id, a config shape, a limit) that live
   state contradicts is the canonical failure mode; a design grounded in "what I assumed" is a
   defect waiting to ship.
2. **Research the open questions before deciding.** For each unknown, do the research, form a
   recommendation with trade-offs, and present the options — do not surface a bare question you
   could have answered. Cite every source.
3. **State the context and the forces.** What problem, what constraints, what is in tension.
4. **List the options — at least two, honestly.** A one-option ADR is a rationalisation. For each,
   the trade-off in plain terms.
5. **Cover the NFRs.** Walk the [engineering-NFR checklist](engineering-nfr-standard.md) —
   cost/licensing, security, performance/scalability, reliability, operability, privacy — for the
   chosen option and name why the rejected options lose. This is non-optional for a one-way door.
6. **Decide, and state the consequences.** What becomes true, what becomes harder, what is now
   foreclosed. Name the fitness function or gate that will keep the decision true (a decision with
   no enforcement drifts back).
7. **File it** per [ADR-POLICY](../decisions/ADR-POLICY.md): product decisions in the repo's
   `record_dir` with per-repo `ADR-###` numbering + a namespaced `alias:` (`TAZ-ADR-###`,
   `KAI-ADR-###`, `KATA-ADR-###`); org-wide cross-cutting decisions as a prefixed-id row in the
   central register.

## Forward-only, never rewrite

Decisions are appended, never deleted or renumbered. Supersede an old record with a
`superseded_by:` banner pointing at the new one; reconcile a product ADR against an org decision
with an amendment banner, never by moving or rewriting history (guard-forward-only).

## Design docs describe the target, not the journey

An ADR or design doc states the pattern that IS — not "this used to be", not a PR number, not a
detection date. History lives in commits and the supersession chain. No narration of how the
decision was reached beyond the options + rationale the reader needs to trust it.

## How to apply

1. Decide whether the change needs a record (hard-to-reverse OR cross-area → yes).
2. Run the method top to bottom; the NFR checklist is a required step, not a footnote.
3. Ground every claim: live-state check for assumptions, a citation for every number, a named
   source for every "typical".
4. File per ADR-POLICY; pair the decision with the gate that enforces it.
5. Reviewer: reject a record that has one option, an uncovered NFR dimension, an unsourced number,
   or a design written against an unverified stack — ask for the missing step, not a rewrite.
