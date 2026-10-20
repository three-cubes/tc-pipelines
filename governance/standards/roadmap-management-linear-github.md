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
>
> Not all work is technical. For non-code work, Linear still owns the work
> contract, but the durable artefact may live in the vault, a Linear document,
> SharePoint, or a client workspace. The issue names that **Artifact Home** so
> agents know where to work and what evidence proves completion.

## 1. One source of truth per stage

| Lifecycle stage | Lives in | Mechanism |
|---|---|---|
| **Idea** | Linear — Triage inbox / `idea` label | Low ceremony. Graduates only when it gets an owner + a project. |
| **Experiment / spike** | Linear issue (`spike`) + a GitHub branch if it is code | Time-boxed; states a hypothesis + "what we'll learn". Outcome → promote to a feature, or kill. |
| **Roadmap / strategic bet** | Linear **Initiative** | The cross-team timeline view. |
| **Stream** | Linear **Project** (+ milestones, target date, lead) | An outcome a team owns. |
| **Epic** | Linear **parent issue** | + sub-issue work breakdown. |
| **Feature / task / bug / research / decision / deliverable** | Linear **issue** | Work contract with a Work Type, Artifact Home and evidence requirement; linked to its GitHub PR when the work is code. |
| **Code execution** | **GitHub** | branch (Linear-named) → PR → CI → review → merge. |
| **Knowledge / research / planning artefact** | **Vault or Linear document** | Durable notes, source ledgers, decisions and project records; linked from the Linear issue. |
| **Client artefact** | **SharePoint / vault / client system** | Deliverable location is named in the Linear issue; review evidence is linked back. |
| **Release / Done** | GitHub tag + Linear auto-Done | PR merge transitions the Linear issue. |

The **vault is knowledge, not a tracker.** Research, vision, methods and
reference material live in the Obsidian vault (or as a Linear *document*); they
do not become a parallel backlog. When a vault note implies work, that work is
captured as a Linear issue and the note is linked, not copied.

## 1a. Linear issue contract for agents

Every substantial or delegated work item carries enough information for an
agent to start from the issue alone, without reconstructing scope from Slack or
chat.

Minimum fields:

| Field | Purpose |
|---|---|
| **Work Type** | Selects the definition of done and lifecycle automation. |
| **Artifact Home** | The durable place where the work product lives: `github://`, `sharepoint://`, `onedrive://`, `vault://`, `linear-doc://`, `workspace://`, `client-system://`, or `none`. |
| **Home URI** | Concrete URL, URI-like path, repo path, document id, workspace path or `none`. |
| **Artifact owner** | Human owner or accountable team for the durable outcome. |
| **Freshness** | Last verified date, version, source timestamp, release tag, or "new artifact". |
| **Verification status** | `missing`, `planned`, `partial`, `verified`, or `not required`. |
| **Safety class** | Highest operation boundary: read-only, local workspace write, remote create/update, remote destructive, or external send/share. |
| **Goal** | The outcome, not the activity. |
| **Non-goals** | Boundaries that stop scope creep. |
| **Inputs / sources** | Links to repo docs, vault notes, client files, Linear docs, Slack threads or source material. |
| **Acceptance criteria** | Observable checks for the work item. |
| **Definition of done** | Work-type-specific completion bar. |
| **Evidence required** | PR/checks/release, vault path, Linear doc, review note, client artefact, PVT result, or rollback note. |
| **Review path** | Human, agent reviewer, CODEOWNERS, client, or no review. |

Agents follow this route:

1. Read the issue, parent project goal/DoD, and linked roadmap/initiative.
2. Follow the Artifact Home; create a GitHub branch only when the issue says
   GitHub evidence is required.
3. Use the Home URI, Artifact owner, Freshness, Verification status and Safety
   class fields before creating a new location or applying a remote change.
4. Record progress and blockers in Linear, the durable record.
5. Harvest decisions, evidence and next steps back to Linear before closing.

## 1b. Work types and default homes

| Work Type | Default Artifact Home | GitHub required? | Done means |
|---|---|---:|---|
| Technical change | `github://<org>/<repo>` | Yes | PR merged, required checks green, release/deploy evidence attached if needed. |
| Runtime / deployment | `github://` + release evidence | Yes | Released from a tag, smoke passed, PVT/rollback result linked. |
| Capability / skill / MCP / ToolPack | `github://` | Yes | Capability contract updated, tests pass, capability verification evidence recorded when applicable. |
| Bug / incident | Work-type dependent | Usually | Repro/root cause captured, fix verified, regression guard added or a clear exception recorded. |
| Research brief | `vault://...` or `linear-doc://...` | No | Source ledger, synthesis, confidence/open questions and recommendation captured. |
| Strategy / decision | `linear-doc://...` or `vault://...` | No | Options, decision, consequences and review trigger documented. |
| Client deliverable | `sharepoint://...`, `onedrive://...`, `vault://...` or client system | No by default | Artefact produced in the named home, reviewed, and evidence linked. |
| Commercial / GTM | `vault://...` or `linear-doc://...` | No by default | Target outcome, asset/path, owner, next action and review state clear. |
| Meeting / workshop | `vault://...` or `linear-doc://...` | No | Agenda/pre-read/actions/decisions captured and linked. |
| Governance / operating model | `linear-doc://...`, `vault://...`, and `github://` if canon changes | Sometimes | Standard/decision updated in the canonical home; affected issues/projects linked. |
| Deprecation / cleanup | Work-type dependent | Sometimes | Replacement/retirement decision recorded, references updated, evidence shows no live dependency remains. |

Rank non-technical work by value tier: customer-critical, value-proven,
strategic-future, speculative. A high-priority item without evidence becomes a
spike or research task first, ahead of any delivery commitment.

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

### Agent-facing tool mapping

Agents reach the Linear work layer through the `delivery-management` ToolPack:

| Linear object | Agent action |
|---|---|
| Team / portfolio | `list_portfolios` before choosing a `portfolio` key. |
| Existing issue backlog | `search_items` / `list_items` before creating new work. |
| Existing issue detail | `get_item` before updating, decomposing, attaching, harvesting, or closing. Paste a shared Linear issue URL here when one appears in Slack/chat/docs. |
| Project | `list_projects` to find the project id, or `create_project` for a new stream. |
| Issue → Project placement | `attach_item_to_project` using the returned issue id/identifier and project id. |
| Roadmap view | `list_roadmap` before claiming initiative/project status or sequencing. |
| Parent/child issue tree | `specify` for the parent, `decompose` for child items. |
| Lifecycle | `delegate`, `update`, `harvest`, `close`; call the `_validate` companion before writes. |

Resolve follow-up actions by the concrete ids/identifiers the tools return.
Titles are not unique, and title-based repair creates orphaned or duplicated
work.

When a collaborator shares a Linear link, pass the shared issue URL to
`get_item` first, then use the returned identifier/id for follow-up writes.
Lifecycle tools that take an `item` also accept shared issue URLs and normalize
them to the issue identifier. Read project links through `list_projects` /
`list_roadmap` to recover a concrete project id before attachment.

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

### GitHub evidence is conditional, not universal

GitHub is mandatory when the work changes code, config, tests, repo docs,
automation, release artefacts or deployable assets. For a research, planning,
commercial, meeting or client-deliverable issue, the agent attaches the durable
artefact link and review evidence to Linear instead of opening a PR.

When GitHub is required:

- branch from current `main` using Linear's generated branch name;
- include the Linear issue in the PR body;
- let GitHub checks/release/deploy evidence prove the technical DoD;
- close only after the release/PVT evidence exists when `release_required=true`.

When GitHub is not required:

- the work proceeds without a branch;
- the Linear issue links the vault, Linear document, SharePoint, OneDrive,
  workspace evidence or client-system artefact;
- closure requires the work-type evidence in the issue.

### Artifact-home evidence is mandatory for material outputs

For every material output, the Linear issue records `Artifact Home`, `Home URI`,
`Artifact owner`, `Freshness`, and `Verification status`. `workspace://` is valid
for local scratch or generated evidence; substantial outputs are published to a
durable home or explicitly archived before closure. `none` is valid only for
coordination/comment-only work with no material artifact.

Run remote destructive and external send/share operations only once approval,
rollback/restoration, and review evidence are named on the issue; until then,
stop at a dry-run or plan.

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
- **A GitHub PR opened for non-technical work just to show progress.** → use the
  Artifact Home and Linear evidence instead.
- **Slack as the work record.** → Slack notifies; plans, decisions, outputs
  and evidence live in Linear, GitHub, the vault or the client artefact home.
- **An issue closed because a document exists.** → close when the work-type
  DoD and evidence requirements are satisfied.

## 6. The one-line operating rule

> Deciding *whether/when* to build or act → **Linear**. Durable knowledge and
> non-technical artefacts → **vault / Linear documents / SharePoint / client
> systems**. Writing, reviewing or shipping code → **GitHub**. The tools touch
> only through explicit links on the Linear issue.
