"""Trusted off-CI host-broker tooling for Three Cubes repos.

Exposes two console scripts:

- `agent-token`: mint a short-lived per-agent GitHub App installation token from
  Key Vault. The lower-level broker complement to the CI `github-app-token`
  composite action, not a direct agent-harness interface (it prints the token).
- `queue-pr`: enrol one pull request in its repository's merge queue as the App,
  bound to the reviewed head. The one bounded GitHub write an agent session may
  run itself; the token never leaves the process.
"""
