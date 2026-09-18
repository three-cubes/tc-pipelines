# tools/ — `tc-agent-tools`

Trusted host-broker tooling, installable by import (no per-repo copy). The single
source of truth lives here; broker deployments pin a release tag.

## `agent-token`

Mint a short-lived GitHub App **installation token** from `kv-tc-agents` (via
`az`). This is a lower-level backend for the trusted off-CI host broker and a
restricted platform-operator diagnostic; it is **not** a direct agent-harness
interface because it prints the token on stdout. The private key, App JWT, and
installation token stay inside the trusted broker process boundary; the printed
token lasts about an hour.
This is the off-CI complement to the CI
[`github-app-token`](../.github/actions/github-app-token/action.yml) composite action —
both mint the same App identities.

**Requires:** a broker or operator `az login` session with **Key Vault Secrets
User** on `kv-tc-agents`. Agent harnesses must not inherit this session.

### Per-agent Apps (SGO-163)

`--agent builder|shape|consultant|growth` mints as that agent's **own** App
identity, resolving the Key Vault secrets `github-app-<agent>-id` /
`github-app-<agent>-key` and discovering the installation from the App JWT. Omit
`--agent` for the canonical `three-cubes-agent` org App (legacy secret names) —
backward compatible with existing broker deployments. See the canonical
[per-agent App set + SDLC-access standard](../governance/agent-sdlc-access-and-hitl.md).

| Flag | Effect |
|---|---|
| `--agent <name>` | select a per-agent App (`builder`/`shape`/`consultant`/`growth`); default = canonical `three-cubes-agent` |
| `--repo three-cubes/REPO` | **required**; select one repository and include its bare name in the installation-token exchange for both canonical and per-agent Apps |
| `--git-config` | set repository-local author and committer metadata to canonical `three-cubes-agent[bot]`, independent of the selected remote actor |

### Broker integration contract

The CLI rejects missing repositories, owners outside `three-cubes`, and
multi-repository values. The broker captures stdout in memory, binds the token
to one repository-scoped subprocess, and discards it when that subprocess exits.
It never returns the token, Key Vault material, or its Azure session to the
calling harness, and it never stores a token in Git configuration, a remote URL,
a file, profile, shell history, or log.

Agent hosts expose the broker's operation interface, not this token-mint CLI.
The canonical boundary and local commit metadata are specified in
[`governance/agent-sdlc-access-and-hitl.md`](../governance/agent-sdlc-access-and-hitl.md).
