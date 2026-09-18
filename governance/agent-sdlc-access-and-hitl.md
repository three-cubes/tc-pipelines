# Agent SDLC access + human-in-the-loop (CANONICAL)

> Promoted into tc-pipelines governance (SGO-163) as the org-canonical
> SDLC-access + HITL standard. The per-agent App manifests it references live at
> [`agent-app-manifests/`](agent-app-manifests/); the enforcement templates
> (`main` ruleset, CODEOWNERS) live alongside in this `governance/` dir. Consuming
> repos (`tc-agent-zone`, `kairix`) converge up to this — do not fork a parallel
> standard.

How agents are granted GitHub access to run the software development lifecycle,
and how a human stays in the loop without becoming the mechanical bottleneck.

## The principle: capability vs. enforcement

Two independent layers. Conflating them is the usual mistake — including the one
that produced this standard.

| Layer | Owned by | Purpose |
|---|---|---|
| **Capability** — what an agent's token *can* do | The agent's GitHub App | Drive the SDLC: plan, branch, commit, PR, read CI, merge, release |
| **Enforcement** — what is *gated* | Repo settings agents cannot change | The human-in-the-loop: branch ruleset, CODEOWNERS, environments |

HITL is **not** achieved by starving capability. It is achieved by **gates an
agent cannot bypass**. So agents get a comprehensive capability set — generous
on reads (no security downside) and on the writes the SDLC needs — and the human
keeps the gates.

## Capability — the GitHub App permission set

Granted comprehensively. Listed alphabetically to map straight to the App /
fine-grained-token settings page. `write` implies `read`. This is the **Full
SDLC (Builder)** tier; the orchestration + contributor tiers are the same table
trimmed — the concrete per-tier encodings are the four
[`agent-app-manifests/*.json`](agent-app-manifests/).

| Permission | Level | Why |
|---|---|---|
| Actions | Read & Write | read runs/logs; re-run flaky jobs, cancel, dispatch |
| Administration | **Read** | *see* branch protection / rulesets / merge-queue config. **Never write** — governance boundary |
| Checks | Read & Write | check-run results; surface Sonar/review as checks |
| Code scanning alerts | Read & Write | triage + dismiss security findings |
| Codespaces (+ lifecycle/metadata/secrets) | No access | unused; secrets boundary |
| Commit statuses | Read & Write | status rollup / merge-queue state |
| Contents | Read & Write | branches, commits, tags, releases, merges |
| Custom properties | Read | repo metadata visibility |
| Dependabot alerts | Read & Write | SCA triage + dismiss |
| Dependabot secrets | No access | secrets boundary |
| Deployments | Read & Write | create/track deploys — gated by Environment reviewers |
| Discussions | Read & Write | if used |
| Environments | **Read** | see env config; protection rules stay human |
| Issues | Read & Write | plan/triage |
| Metadata | Read | mandatory baseline |
| Packages | Read & Write | publish/consume npm packages on release |
| Pages | No access | unused |
| Pull requests | Read & Write | create/update/comment/review/merge |
| Repository security advisories | Read | view advisories |
| Secret scanning alerts | Read | view leaked-secret findings |
| Secrets | **No access** | hard boundary — KV / GitHub-secrets, human-managed |
| Variables | Read & Write | non-secret Actions config |
| Webhooks | No access | integration/admin boundary |
| Workflows | Read & Write | edit `.github/workflows` — **CODEOWNERS-gated** |

**The whole HITL boundary** is five items: `Secrets`/`Dependabot secrets`/
`Codespaces secrets` = none; `Administration` = read-only; `Environments` =
read-only; `Webhooks` = none; `Workflows` = write but CODEOWNERS-gated.
Everything else is granted.

## Enforcement — the gates a human owns

Configured per consuming repo from the templates in this `governance/` dir. These
require `Administration: Write` to apply, which agents do not have — so applying
them is itself a human action.

1. **`main` rulesets** — the org-level [`main-product.json`](rulesets/main-product.json) / [`main-core.json`](rulesets/main-core.json) rulesets:
   - **require CODEOWNERS review** (the core HITL gate) — the required-approval
     count is per-repo posture, not an org-wide constant: **CORE repos**
     (`tc-pipelines`, `tc-fitness`) keep **n+1 human approval** (D3), **product
     repos** run **0-approval auto-merge on green** with CODEOWNERS only on the
     control plane. See [`AUTONOMOUS-DELIVERY-STANDARD.md`](AUTONOMOUS-DELIVERY-STANDARD.md)
     (STD-MERGE) and [`README.md`](README.md).
   - Required status checks: `Quality gate` and `no-attribution`. Private
     Team-plan repos cannot use a GitHub merge queue; where available (public
     repos) a merge queue re-runs checks on the combined commit, else strict
     status checks stand in.
   - No deletion / no force-push; **not strict** (no forced rebase) and **no
     stale-dismiss** (an approval persists through pushes).
   - `bypass_actors`: the human **admin role only** (emergency override). Agent
     Apps are **not** admins.
2. **CODEOWNERS** — [`CODEOWNERS`](CODEOWNERS): routes review to the human owner,
   and pins gate-critical + canon paths (the gate's own definition — CI,
   `[tool.tc_fitness]`, schemas, validators, dep pins, governance) to the human
   team — so an agent can never self-approve a change to the gates that constrain
   it.
3. **Environments** with required reviewers for prod deploys (vm-openclaw /
   hermes) — a human approves the deploy even though the App can create
   deployments.

## The merge model

> Agents prepare **everything** — branch, commits, green CI, PR body, self-review
> — and an agent may **merge**, but only a PR that is CI-green **and** (on the
> control plane, or on any CORE repo) human-approved. The approval is the
> human-in-the-loop. The human stops running `git merge` and starts saying "yes"
> to the diff.

This is strictly *more* HITL than a CI-only gate, while removing the human as the
mechanical bottleneck.

## Identity — canonical commits, per-agent remote actors

Each agent's remote writes authenticate as its **own GitHub App**
(`tc-agent-builder`, `tc-agent-shape`, `tc-agent-consultant`,
`tc-agent-growth`) — see
[`agent-app-manifests/`](agent-app-manifests/). Why apps, not a shared PAT:

- **Distinct identity** — the audit log shows *which agent* did what (vs. one
  blurred `quanyeomans`/`openclaw-pat` actor).
- **Short-lived tokens** — installation tokens auto-expire (~1h); no long-lived
  PAT to leak or rotate by hand. Replaces the `*-openclaw-pat` secrets in KV.
- **Per-agent least-privilege** — tiers (full / orchestration / contributor)
  scope each agent to its role; Growth can't edit workflows, only Builder can.
- **Commit metadata is separate** — the App is the authenticated remote actor;
  every agent-authored commit records the canonical `three-cubes-agent[bot]`
  author and committer. GitHub records the pusher separately.

### Local commit boundary: no credential required

Creating a local branch, commit, or test result needs no GitHub credential. Set
the repository-local identity once:

```bash
git config --local user.name 'three-cubes-agent[bot]'
git config --local user.email '295831460+three-cubes-agent[bot]@users.noreply.github.com'
```

This metadata neither authenticates nor authorises a remote write. It stays the
same whichever agent App later pushes the commit, so repository history has one
canonical automation identity while GitHub's audit log retains the distinct
remote actor.

### Off-CI remote-write boundary: trusted host broker

An agent harness does not mint, receive, export, or persist an App token. For
each `git`, `gh`, or API write, it asks a trusted host broker to perform the
operation with the target repository and agent selector. The broker:

1. holds the Azure/Key Vault access needed to read the selected App ID and
   private key;
2. signs a short-lived App JWT and exchanges it for a repository-scoped
   installation token;
3. binds that token to one subprocess (or performs the operation itself); and
4. discards the token when the subprocess exits.

The broker must not return the token to the harness, place it in a remote URL or
Git configuration, write it to a file, profile, shell history, or log, or expose
its Azure session to the harness. There is no fallback to a human PAT. If the
broker is unavailable, local commits and checks continue; the remote write
stops until broker service is restored.

The `agent-token` CLI in [`tools/`](../tools/README.md) is the lower-level mint
implementation for that trusted broker and for restricted platform-operator
diagnosis. Because it prints a token, it is not the agent-harness interface.
It requires exactly one `three-cubes/REPO` scope and includes that repository in
the installation-token exchange, including when the canonical App uses its
fixed installation ID. Its optional `--git-config` helper always sets the same
canonical local commit identity shown above, never the selected remote actor.

### GitHub Actions boundary

In Actions, the
[`.github/actions/github-app-token`](../.github/actions/github-app-token/action.yml)
composite uses the job's WIF identity to mint the same short-lived App token and
passes it only to the authorised workflow steps. An Actions repository secret
is available only inside an explicitly authorised workflow job; GitHub's API
and `gh secret` commands expose names and metadata, not the stored plaintext.
Actions secrets are therefore not a local credential store or retrieval path.

| Context | Credential path | Commit metadata |
|---|---|---|
| Local agent harness | trusted host broker; token remains outside the harness | canonical `three-cubes-agent[bot]` set with repository-local Git config |
| GitHub Actions | WIF-backed `github-app-token` composite; token scoped to authorised steps | canonical `three-cubes-agent[bot]` |
| Platform operator diagnosis | restricted direct use of `agent-token`; one `three-cubes/REPO` is mandatory | canonical metadata remains separate; `--git-config` always writes `three-cubes-agent[bot]` |

The boundary is harness-neutral: terminal agents, MCP-hosted agents, service
agents, and future harnesses all use the same local-metadata and broker contract.

## Setup checklist

**Human / org-owner (one-time) — the `Secrets = No access` boundary means an
agent cannot self-provision these:**
1. Apply the `main` ruleset + add CODEOWNERS from this `governance/` dir.
2. (public repos only) optionally add a merge queue to the ruleset; private
   Team-plan repos cannot, so their strict status checks stand in.
3. Create the 4 Apps from the manifests; generate a private key + install each.
4. Store each `App ID` + `.pem` in `kv-tc-agents` as `github-app-<agent>-id` and
   `github-app-<agent>-key`. Never commit the `.pem`.
5. Put vm-openclaw / hermes deploys behind a GitHub Environment with required
   reviewers.

**Platform:**
6. Provide the trusted host broker and expose only its operation interface to
   local agent harnesses; keep Key Vault and token material behind that boundary.
7. Retire the `*-openclaw-pat` KV secrets once apps are live.

## Scope of this standard

Applies to every repo the agent platform touches — currently
`three-cubes/tc-agent-zone` and `three-cubes/kairix` (which carry the same
ruleset + CODEOWNERS, adapted to their layout), with the canonical templates +
manifests + mint surfaces owned here in `tc-pipelines`.
