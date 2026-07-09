# Repo governance: org-level config + secret wiring

Status: proposed. Canonises which CI config is
shared across three-cubes repos and therefore promoted to org level, and how a
new repo is wired with one command.

## Why org-level

GitHub resolves Actions variables and secrets **repo-over-org**: a repo-level
value shadows the org-level one of the same name; if a repo has no value, it
inherits the org value. So promoting a *shared* value to org level means every
current and future repo inherits it with zero per-repo wiring, and any repo that
genuinely needs a different value still sets a repo-level override safely (the
override wins, the org default is untouched).

The toil this removes: today each repo (tc-agent-zone, kairix, tc-fitness,
tc-pipelines) wires `SONAR_TOKEN` / `CODECOV_TOKEN` /
`AZURE_*` by hand. That is N manual wirings per value and silent drift when one
rotates.

## What is shared (promote to org) vs repo-specific (keep local)

| Name | Type | Shared? | Action |
|---|---|---|---|
| `AZURE_CLIENT_ID` | variable | yes — all repos federate to the same WIF app | promote org-level (value readable from an existing repo) |
| `AZURE_SUBSCRIPTION_ID` | variable | yes | promote org-level |
| `AZURE_TENANT_ID` | variable | yes | promote org-level |
| `SONAR_TOKEN` | secret | yes — one SonarCloud org token | promote org-level (value from KV / the platform owner, NOT readable from the repo) |
| `CODECOV_TOKEN` | secret | yes — one Codecov org | promote org-level (value from KV / the platform owner) |
| `PRIVATE_INFRA_PATTERNS` | var + secret | already org-level | none |
| `ENGINEERING_HUB_TOKEN` | secret | already org-level (visibility private) | none |
| `LLM_JUDGE_API_URL` / `LLM_JUDGE_API_KEY` | secret | no — repo-only (e.g. LLM-judge CI) | keep repo-level |

Variable VALUES are readable via the API, so the AZURE_* trio can be promoted
now by pulling each value from an existing repo. Secret VALUES are write-only, so
`SONAR_TOKEN`/`CODECOV_TOKEN` need the plaintext from Azure Key Vault or the
platform owner before org promotion.

### KV gap to close first

`kv-tc-agents` today holds the SonarCloud **API PATs** (`sonarcloud-pat` —
stale/invalid; `sonarcloud-three-cubes-pat` — valid, used by the FP-marking
scripts) but **not** the CI **analysis** token that CI's `SONAR_TOKEN` carries,
and **no** Codecov upload token at all. Before the org-promotion of these two
secrets, add the canonical KV entries (names the bootstrap script expects):

- `sonarcloud-ci-analysis-token` — the SonarCloud project/global *analysis*
  token used by `SonarSource/sonarqube-scan-action` (distinct from the API PAT).
- `codecov-upload-token` — the Codecov repo/global upload token.

These two values can only come from the platform owner / the SonarCloud + Codecov consoles —
the operator cannot read them from any existing GitHub secret.

## Promote — exact commands

Variables (values pulled from an existing repo — here `tc-agent-zone` — set org-wide, all repos):

```bash
for v in AZURE_CLIENT_ID AZURE_SUBSCRIPTION_ID AZURE_TENANT_ID; do
  val="$(gh api repos/three-cubes/tc-agent-zone/actions/variables/$v --jq .value)"
  gh variable set "$v" --org three-cubes --visibility all --body "$val"
done
```

Secrets (values from KV once the entries above exist):

```bash
sonar="$(az keyvault secret show --vault-name kv-tc-agents --name sonarcloud-ci-analysis-token --query value -o tsv)"
printf '%s' "$sonar" | gh secret set SONAR_TOKEN --org three-cubes --visibility all --body -

codecov="$(az keyvault secret show --vault-name kv-tc-agents --name codecov-upload-token --query value -o tsv)"
printf '%s' "$codecov" | gh secret set CODECOV_TOKEN --org three-cubes --visibility all --body -
```

`--visibility all` scopes to every repo in the org. To scope to a named subset
instead, use `--visibility selected --repos tc-agent-zone,kairix,tc-fitness,...`.

## Safe-promotion checklist (precedence)

1. Promote org-level. Existing repo-level values keep winning (no behaviour
   change on day one).
2. Confirm CI still green on each repo (it reads the still-present repo value).
3. Remove the now-redundant repo-level value **one repo at a time**, confirming
   green after each, so the repo falls back to the org value:
   `gh variable delete AZURE_CLIENT_ID --repo three-cubes/<name>` /
   `gh secret delete SONAR_TOKEN --repo three-cubes/<name>`.
4. Leave repo-specific secrets (e.g. the LLM-judge CI credentials) repo-level.

Do not skip step 3-per-repo: deleting all overrides in one sweep removes the
fallback you are relying on if the org value is wrong.

## One-command onboarding

`scripts/bootstrap-repo-governance.sh --repo three-cubes/<name>` sets the
standard variables (inheriting org where present), wires the standard secrets
from KV, applies the `main` ruleset, and prints the governance-file install
sequence. See the script header for flags.
