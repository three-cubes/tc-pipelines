---
type: standard
status: adopted
date: 2026-06-13
title: Roadmap management — Linear and GitHub
authority:
  - the platform owner
---

# Roadmap management — Linear and GitHub

> **The rule.** Linear owns the *what/why* (idea → roadmap → epic → issue).
> GitHub owns the *how/done* (branch → PR → CI → release). They meet at exactly
> one seam — the **issue ↔ PR link** — and the same backlog is never maintained
> in two tools. Every duplication this platform has hit came from running a
> *second prioritised backlog*; this standard exists to stop that.

## 1. One source of truth per stage

| Lifecycle stage | Lives in | Mechanism |
|---|---|---|
| **Idea** | Linear — Triage inbox / `idea` label | Low ceremony. Graduates only when it gets an owner + a project. |
| **Experiment / spike** | Linear issue (`spike`) + a GitHub branch if it is code | Time-boxed; states a hypothesis + "what we'll learn". Outcome → promote to a feature, or kill. |
| **Roadmap / strategic bet** | Linear **Initiative** | The cross-team timeline view. |
| **Stream** | Linear **Project** (+ milestones, target date, lead) | An outcome a team owns. |
| **Epic** | Linear **parent issue** | + sub-issue work breakdown. |
| **Feature / task / bug** | Linear **issue** | linked to its GitHub PR. |
| **Code execution** | **GitHub** | branch (Linear-named) → PR → CI → review → merge. |
| **Release / Done** | GitHub tag + Linear auto-Done | PR merge transitions the Linear issue. |

The **vault is knowledge, not a tracker.** Research, vision, methods and
reference material live in the Obsidian vault (or as a Linear *document*); they
do not become a parallel backlog. When a vault note implies work, that work is
captured as a Linear issue and the note is linked, not copied.

## 2. The Linear object model, in the team-as-ownership frame

Teams are the **ownership unit** (one per platform/product area). The crucial
asymmetry that governs everything else:

| Object | Team-scoped? | Role |
|---|---|---|
| **Issue** | **Yes — exactly one team.** | The work item. Hard ownership. |
| **Project** | **Yes — one (may be shared).** | An outcome the team owns, on a timeline. A team's *roadmap* is its set of projects. |
| **Cycle** | **Yes.** | The team's execution cadence (sprint). |
| **Milestone** | Project-scoped. | A checkpoint inside a project. |
| **Initiative** | **No — team-agnostic.** | A cross-team strategic bet that groups *projects* across ownership boundaries. The only object that is **not** owned by a team. |

So initiatives do **not** map to a team — they map to *projects* (which map to
teams). Use them only for genuine cross-cutting outcomes; do not make an
initiative mirror a team.

### Three Cubes structure (current)

- **Teams** = the ownership areas: Core Platform (Kairix), Knowledge Primitives,
  Execution Containers & Runtime, Governance & Ops Control Plane,
  GTM & Commercial Readiness, Other Work.
- **Projects** = the outcome streams each team owns (each with a lead + target date).
- **Initiatives** (cross-team bets): *Kairix Engine GA*, *First Commercial
  Engagement Live*, *Capability Product Library*. A project rolls into an
  initiative only when it is part of that bet; peripheral projects carry none.

## 3. The seam — Linear ↔ GitHub

The GitHub integration is the **single bridge**. There is no manual re-keying.

- Linear generates the branch name (`<user>/<id>-<slug>`); using it links the PR to
  the issue automatically. `Closes`/`Fixes` in the PR also works.
- PR open → issue moves to *In Progress*; PR merge → issue moves to *Done*.
- A single Linear issue may link to PRs in **any** repo — e.g. `kairix` or
  `kairix-pro-platform`. The repo is where code lands, not where the
  plan lives.
- Assign each repo to its owning team in Linear's GitHub integration settings, so
  "the team owns its tech assets" is concrete, not just narrative.

**Bugs:** CI/agent/dev-discovered bugs originate in GitHub and sync into Linear
Triage; usage/feedback bugs are created in Linear directly. One triage queue
either way.

## 4. Multi-repo

Linear is the **portfolio + planning** layer across every repo. Each GitHub repo
is the **execution** layer for its product. A repo's own GitHub issues exist only
as the dev-side handle of a Linear item that is in active development — never as
an independent prioritised list. **GitHub Projects (boards) are not used for
roadmap.**

## 5. Anti-patterns (these caused real duplication)

- **A GitHub Project board used as the roadmap.** (Retired: org projects
  *Agent-Platform* and *Kairix-Pro-Roadmap*.) → roadmap is Linear.
- **The vault used as a tracker.** → vault is knowledge; work is a Linear issue.
- **Two prioritised backlogs for the same work** (vault waves + GitHub board +
  Linear). → one source of truth per stage; link, don't mirror.
- **An initiative that mirrors a team.** → initiatives are cross-team only.

## 6. The one-line operating rule

> Deciding *whether/when* to build → **Linear**. Writing, reviewing or shipping
> code → **GitHub**. The two touch only through the issue ↔ PR link.
