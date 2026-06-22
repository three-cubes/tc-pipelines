# scripts/

- **[`agent-token.py`](agent-token.py)** — mint a short-lived `three-cubes-agent` GitHub App
  installation token from `kv-tc-agents` (via `az`), so a **local / MCP agent acts as the App,
  not a human**. The App key never leaves the vault except as a ~9-minute in-memory assertion.

  ```bash
  export GH_TOKEN="$(python3 scripts/agent-token.py)"
  git config user.name  'three-cubes-agent[bot]'
  git config user.email '295831460+three-cubes-agent[bot]@users.noreply.github.com'
  # now git push / gh pr create / gh pr merge act as the App
  ```

  Requires an `az login` session with **Key Vault Secrets User** on `kv-tc-agents`. The CI
  complement (for GitHub Actions) is the
  [`github-app-token`](../.github/actions/github-app-token/action.yml) composite action — both
  mint the same App identity; this one is for off-CI agents.
