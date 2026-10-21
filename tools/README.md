# tools/ — `tc-agent-tools`

Trusted host-broker tooling. In agent-platform it is a uv workspace member, so
`uv run --frozen agent-token ...` from the repository root runs it; the public
tc-pipelines export carries it as `tools/`.

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

```bash
uv run --frozen -q agent-token --repo three-cubes/agent-platform
```

**Requires:** a broker or operator `az login` session with **Key Vault Secrets
User** on `kv-tc-agents`. Agent harnesses must not inherit this session. `az` is
resolved from the system prefixes only (never `PATH`) and runs in a broker-owned
environment, as for `queue-pr` below; because this command prints the token to
its caller, it serves from the operator's own (for example Homebrew-owned) `az`
without the caller-writability guard `queue-pr` applies.

### Per-agent Apps (SGO-163)

`--agent builder|shape|consultant|growth` mints as that agent's **own** App
identity, resolving the Key Vault secrets `github-app-<agent>-id` /
`github-app-<agent>-key` and discovering the installation from the App JWT. Omit
`--agent` for the canonical `three-cubes-agent` org App (legacy secret names) —
backward compatible with existing broker deployments. See the canonical
[per-agent App set + SDLC-access standard](../../../assurance/governance/agent-sdlc-access-and-hitl.md).

| Flag | Effect |
|---|---|
| `--agent <name>` | select a per-agent App (`builder`/`shape`/`consultant`/`growth`); default = canonical `three-cubes-agent` |
| `--repo three-cubes/REPO` | **required**; select one repository and include its bare name in the installation-token exchange for both canonical and per-agent Apps |
| `--git-config` | set repository-local author and committer metadata to canonical `three-cubes-agent[bot]`, independent of the selected remote actor; mints and prints no token |

### Broker integration contract

The CLI rejects missing repositories, owners outside `three-cubes`, and
multi-repository values. The broker captures stdout in memory, binds the token
to one repository-scoped subprocess, and discards it when that subprocess exits.
It never returns the token, Key Vault material, or its Azure session to the
calling harness, and it never stores a token in Git configuration, a remote URL,
a file, profile, shell history, or log.

Agent hosts expose the broker's operation interface, not this token-mint CLI.
The canonical boundary and local commit metadata are specified in
[`agent-sdlc-access-and-hitl.md`](../../../assurance/governance/agent-sdlc-access-and-hitl.md).

## Tests

`tests/` runs in the gate. Key Vault is a stand-in `az` on `PATH`, GitHub is a
local HTTP server reached through `main`'s `api` seam, and git is real, so no
test patches the module.

## `queue-pr`

Enrol one pull request in its repository's merge queue, as the canonical
`three-cubes-agent` App, bound to the head a readiness check reviewed. This is
the one bounded GitHub write an agent session may run on its own.

```bash
queue-pr <number> --head <40-hex sha> [--repo three-cubes/agent-platform|three-cubes/tc-agent-zone|three-cubes/kairix]
```

| Argument | Meaning |
|---|---|
| `<number>` | the pull-request number; nothing else is accepted |
| `--head SHA` | required; the reviewed head as a full 40-hex SHA. A pull request at any other head is refused |
| `--repo OWNER/REPO` | one of the two allowlisted repositories; default `three-cubes/agent-platform` |

**What it does.** It mints the App token for that repository (the same path as
`agent-token`), confirms over GraphQL that the pull request is open at `--head`,
then either enqueues it (`enqueuePullRequest` with `expectedHeadOid`) when its
checks already pass, or arms auto-merge bound to that head when they are still
running. Output is one line: `queued: … entered the merge queue` or
`armed: … enters the merge queue when its checks pass`.

**Privilege boundary.** The token never leaves the process: there is no child
executable, no environment hand-off and no output of it. The Azure CLI it runs
is the one the host's operator pinned as root in `/etc/tc-agent-tools/az` (one
line, the absolute path); without a root-owned, root-only-writable pin naming an
executable there is no Key Vault read. Neither `PATH` nor any search path is
consulted, so a Homebrew-owned `az` is fine once the operator has vouched for it.
`az` runs in a broker-owned environment: a fixed `PATH`, the account's own home
and `.azure` from the account database (never `$HOME` or `$AZURE_CONFIG_DIR`),
and no proxy, CA or verification override. The command refuses to run from an
installation the invoking user can modify. Host setup is therefore three
root-owned files, once per host that runs agent sessions, and survives
restarts: `make bootstrap-host` from the repository root installs this package
from the commit `execution/pipelines/tools/INSTALL_REF` pins (the Makefile reads it as `TC_AGENT_TOOLS_REF`) into `/opt/tc-agent-tools`
with its commands in `/opt/tc-agent-tools/bin`, pins `command -v az` in
`/etc/tc-agent-tools/az`, and adds `Bash(/opt/tc-agent-tools/bin/queue-pr:*)` to the
invoking user's `~/.claude/settings.json`; it asks for sudo once, changes
nothing that is already in place, and verifies with `queue-pr --help`.
`make bootstrap` runs its `--check` and names the target when a host lacks it.

`make bootstrap-host` is agent-platform's wrapper; the public tc-pipelines
layout carries this directory without the Makefile or the script, so there the
same three pieces are put in place by hand, from a verified commit of this
package:

```bash
sudo mkdir -p /opt/tc-agent-tools/bin && sudo chown root /opt/tc-agent-tools /opt/tc-agent-tools/bin && sudo chmod 755 /opt/tc-agent-tools /opt/tc-agent-tools/bin
sudo env HOME=/var/root UV_TOOL_DIR=/opt/tc-agent-tools UV_TOOL_BIN_DIR=/opt/tc-agent-tools/bin UV_CACHE_DIR=/opt/tc-agent-tools/cache UV_PYTHON_INSTALL_DIR=/opt/tc-agent-tools/python UV_PYTHON_PREFERENCE=only-managed uv tool install --force --reinstall --from 'git+https://github.com/three-cubes/agent-platform@<verified commit>#subdirectory=execution/pipelines/tools' tc-agent-tools
az="$(command -v az)" && [ -x "$az" ] || { echo "install the Azure CLI first"; false; }
sudo mkdir -p /etc/tc-agent-tools && printf '%s\n' "$az" | sudo tee /etc/tc-agent-tools/az >/dev/null && sudo chown root /etc/tc-agent-tools /etc/tc-agent-tools/az && sudo chmod 755 /etc/tc-agent-tools && sudo chmod 644 /etc/tc-agent-tools/az
/opt/tc-agent-tools/bin/queue-pr --verify-installation
```

and `Bash(/opt/tc-agent-tools/bin/queue-pr:*)` goes into the invoking user's
`~/.claude/settings.json` under `permissions.allow`. `queue-pr
--verify-installation` runs only the trust check and prints `PASS queue-pr:
trusted installation`; a caller-writable package or interpreter is refused
with the usual envelope.

The operator's existing `az login` (in that account's `~/.azure`) is what `az`
uses; nothing else is configured.

That pins this package's source to one commit; `uv` still resolves its
dependencies (`pyjwt[crypto]`, `hatchling`) from PyPI at install time, so the
operator who installs it owns that resolution. A digest-verified install from the
repository lock, and a launcher that verifies the install before Python imports
anything, are the host broker's work (PLA-533); the in-process checks here are
defence in depth, not that boundary.

The Claude Code permission that allows it (`Bash(/opt/tc-agent-tools/bin/queue-pr:*)`,
the absolute path, so a `queue-pr` placed earlier on PATH is never what runs)
belongs in the host's user-level settings, not in any repository. Every network and
child-process operation has a 60-second bound.

**Failure contract.** A refusal (closed or missing pull request, moved head, a
base other than the queue-protected default branch, an author that is not an
agent App,
GitHub declining the enrolment or answering without its confirmation object, an
unreachable or slow API, an untrusted installation) exits 1 with one line: `FAIL queue-pr: <reason>. fix: <what to do>.
next: <command to verify>`. A credential-provider failure (`az` missing or
failing, Key Vault denied, a malformed token exchange) exits 1 the same way and
names only the exception type, never a value. Bad arguments exit 2 from the
parser.
