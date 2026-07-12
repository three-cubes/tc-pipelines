# require-work-item — the fail-closed "no work without a work item" merge gate

Reusable workflow: [`.github/workflows/require-work-item.yml`](../../.github/workflows/require-work-item.yml)
(`on: workflow_call`).

> **Status (2026-07-12): not a required status check.** Work-item traceability is
> now enforced natively by the org **`org-branch-naming`** ruleset — a branch must
> embed a Linear id (`<user>/<team>-<number>-<slug>`) or be an operational/bot
> branch — so a PR is traceable by construction. This reusable and doc are
> retained as **reference**; the WIF / Key-Vault / Linear require-work-item callers
> are **not** wired as a required gate.

This is **PLA-313 / SP-C-5** of the
[Autonomous Delivery Platform](https://linear.app/three-cubes/initiative/autonomous-delivery-platform-dae678e12c5d)
initiative (Increment-3 "Shape-as-orchestrator + enforcing hooks") — the
**merge-boundary** enforcement of the invariant **NO WORK WITHOUT A WORK ITEM**.

A gateway (`subagent_spawning`) hook can refuse a *spawn* whose brief lacks a
Linear issue id, but a gateway hook **cannot block at the merge boundary** — an
agent PR can still show up with no traceable work item. This reusable closes that
gap: a consumer wires it on `pull_request`, and it **FAILS the PR** unless the PR
is traceable to a **real, open/in-progress** Linear work item. Enforcement is
**structural** — a status check keyed to the PR, **not** prompt-convention. So an
agent PR with no work item cannot merge.

It is the merge-side twin of the close-side
[`verify-and-close`](verify-and-close.md): same Linear GraphQL access, same
secret-free Key Vault (WIF) key path, same injection-safety discipline.

## The decision

On each PR the gate resolves, then decides, in order:

1. **Resolve the linked Linear issue id.** Precedence:
   1. the `issue-id` input, if set;
   2. the PR **head branch**, parsed against the org convention
      `<user>/<team>-<number>-<slug>` (e.g. `dan/pla-313-...` => `PLA-313`);
   3. the PR **body**, scanned for an explicit identifier (e.g. `PLA-313`).
2. **BYPASS 0 — exempt dependency-update bot.** If the PR author is a **Bot**
   **and** its login is in `bot-actors` (default `dependabot[bot]` /
   `renovate[bot]`), the gate passes. These bots open PRs mechanically with no
   Linear work item. The autonomous delivery App is deliberately **not** in
   `bot-actors` — agent PRs are exactly what the invariant targets, so they still
   require a work item.
3. **BYPASS 1 — human maintainer.** If the PR author is a real user (not a
   bot/App) **and** their `author_association` is in `maintainer-associations`
   (default `OWNER` / `MEMBER`), the gate passes. The invariant targets **agent**
   PRs; a human maintainer is trusted to open a PR without a work item.
4. **BYPASS 2 — explicit `no-work-item` escape hatch** (genuine hotfixes). The PR
   passes only if **all** of:
   - it carries the `no-work-item` label; **and**
   - its body has a `no-work-item: <why>` **rationale** line (non-empty text);
     **and**
   - (default) a **code-owner** has left an **approving review** (a
     maintainer-association `APPROVED` review) — the CODEOWNERS gate on the
     escape.

   This makes the escape **CODEOWNERS-gated structurally**: a bot cannot
   self-grant it — a human maintainer must sign off. An **incomplete** escape
   (label but no rationale / no approval) is **not** honoured; it falls back to
   the work-item requirement (never a silent pass) and the run logs exactly
   what is missing.
5. **Otherwise VERIFY via the Linear GraphQL API** that the resolved issue
   **EXISTS** and is **OPEN/IN-PROGRESS** (its workflow-state `type` is in
   `allowed-state-types`, default everything except the terminal `completed` /
   `canceled`). A non-existent, Done, or Cancelled issue **FAILS** — a closed
   issue cannot launder new work.

### Fail-closed

If **no** work item resolves, **or** the work-item source is **unreadable** (Key
Vault, the Linear API, or the network errors), the check **FAILS**. Unreadable
never degrades to "pass" (SP-C-5). Contrast the *close* side
(`verify-and-close`), which **skips** on an unresolved id because a false-close is
worse than a skip; here the safe default is the opposite — a false-**pass** would
defeat the invariant, so we fail closed.

## The stable required-status-check context

The reusable's single job is named **`require-work-item`**, so a **ruleset**
*could* gate `main` on the context **`require-work-item`** — the same discipline
as the `no-attribution` context (`governance/STANDARDS.md` §4). It is **not
currently wired**: the org **`org-branch-naming`** ruleset enforces work-item
traceability natively (the branch embeds the Linear id, or is an operational/bot
branch), so `require-work-item` is retained as reference rather than added to the
org `main` rulesets' required checks.

**Do not rename the job** if a repo ever opts to gate on it — the context name is
the job name.

## The Linear API key — two paths

Identical to [`verify-and-close`](verify-and-close.md#the-linear-api-key--two-paths).
The key needs only **read** access to look the issue up (state + existence). It is
scoped to **only** the Linear step, `::add-mask::`-ed the instant it is read on
the Key Vault path, and **never** written to a job or step output.

- **RECOMMENDED — secret-free (Key Vault via WIF).** Set `linear-key-vault` to an
  Azure Key Vault name; the job federates to Azure via Workload Identity
  Federation (OIDC, no stored credential) and reads `linear-key-secret-name`
  (default `ci-verify-and-close`, reused so one KV secret serves both loop
  workflows) at run time inside the Linear step. The caller job grants
  `id-token: write` and passes the `azure-client-id` / `-tenant-id` /
  `-subscription-id` (typically the repo `vars.AZURE_*`).
- **FALLBACK — GitHub secret.** Leave `linear-key-vault` empty and pass
  `secrets.LINEAR_API_KEY`.

## Wiring it (consumer)

The consumer triggers on `pull_request` so the gate sees the PR, and names the
caller job to publish the stable context.

### Secret-free (recommended) — Key Vault via WIF

```yaml
name: require-work-item
on:
  pull_request:

permissions:
  contents: read
  pull-requests: read # read the PR facts (branch, body, author, labels, reviews)
  id-token: write # federate to Azure for the Key Vault fetch (no stored secret)

jobs:
  require-work-item:
    uses: three-cubes/tc-pipelines/.github/workflows/require-work-item.yml@v1
    with:
      linear-key-vault: ${{ vars.KAIRIX_KV_NAME }} # or any KV name
      azure-client-id: ${{ vars.AZURE_CLIENT_ID }}
      azure-tenant-id: ${{ vars.AZURE_TENANT_ID }}
      azure-subscription-id: ${{ vars.AZURE_SUBSCRIPTION_ID }}
    # no `secrets:` block — the key is fetched from Key Vault at run time
```

### Fallback — GitHub secret

```yaml
name: require-work-item
on:
  pull_request:

permissions:
  contents: read
  pull-requests: read

jobs:
  require-work-item:
    uses: three-cubes/tc-pipelines/.github/workflows/require-work-item.yml@v1
    secrets:
      LINEAR_API_KEY: ${{ secrets.LINEAR_API_KEY }}
```

Common overrides:

| input | default | when to change |
|---|---|---|
| `linear-key-vault` | *(empty)* | **recommended** — a KV name enables the secret-free WIF fetch |
| `linear-key-secret-name` | `ci-verify-and-close` | the KV secret name holding the Linear key |
| `azure-client-id` / `-tenant-id` / `-subscription-id` | *(empty)* | the WIF identity, required with `linear-key-vault` |
| `allowed-state-types` | `triage backlog unstarted started` | tighten (e.g. drop `backlog`) to require an already-started item |
| `maintainer-associations` | `OWNER MEMBER` | add `COLLABORATOR` to trust repo collaborators as human maintainers |
| `bot-actors` | `dependabot[bot] renovate[bot]` | dependency-update bot logins exempt from the work-item requirement (Bot authors only) |
| `no-work-item-label` | `no-work-item` | your escape-hatch label name |
| `rationale-marker` | `no-work-item:` | the body prefix that carries the hotfix rationale |
| `escape-requires-approval` | `true` | `false` to let the label + rationale bypass without a code-owner approval |
| `issue-id` / `branch-name` / `pr-body` | *(auto)* | testing / non-standard triggers |

## Injection-safety

Every caller input and every `github.event.*` field is **env-bound** before it
reaches a shell body — never interpolated into a `run:` string — so no value
(branch name, PR body, label, association) can break out of its string context.
All PR facts are parsed from API JSON via `jq`, and every dynamic value injected
into GraphQL goes through `jq --arg` (JSON-encoded), never string-spliced into a
query. The Linear API key stays a local shell variable inside the single Linear
step. Third-party actions are SHA-pinned; the WIF login uses the same
`wif-azure-login@v1` composite as the rest of the loop.
