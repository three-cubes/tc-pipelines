# Environment & Config Management — one source of truth for every identifier

> Every deploy-target identifier — resource names, endpoints, region, environment names, target
> ids — lives in **one committed registry per repo**. Code, scripts, and CI read it; nothing
> hardcodes a second copy. Secrets are referenced **by name** from a secret store, never valued in
> the registry. This is the anti-drift rule for the layer below
> [repo-governance-secret-wiring](repo-governance-secret-wiring.md).

## Why

The same environment identifier copied into a script, a workflow, a Bicep param, and a doc drifts
the moment one copy changes — and the drift is invisible until an apply hits the wrong target or a
rebuild orphans a role assignment. A single registry makes the identifier set greppable, reviewable,
and diffable: one edit, one place, every consumer follows. It also draws the bright line every
config system needs — **identifiers are committed; secrets are referenced, never committed.**

## The registry (single source of truth)

Keep one committed file per repo — e.g. `deployment-targets.yaml` (name is per repo; the pattern is
the contract) — that enumerates each environment and its stable identifiers:

```yaml
# deployment-targets.yaml (example shape)
environments:
  prod:
    resource_group: <rg-name>          # committed identifier
    hosts: [<host-a>, <host-b>]        # committed identifier
    region: <region>
    secret_store: <kv-or-vault-ref>    # a REFERENCE to the store, not a secret
    secret_names:                      # names only — values live in the store
      gateway_token: <secret-name>
```

Rules:

- **Identifiers are committed; secrets are referenced by name.** A value that is sensitive (token,
  key, connection string) never appears here — only the store reference + the secret's name. The
  runtime resolves the name against the store (e.g. a key vault) at apply/run time.
- **One writer, many readers.** Scripts, CI workflows, and IaC params READ the registry; none keep
  a parallel hardcoded copy. A change to a target is one edit here.
- **Deterministic identity provisioning.** Where identifiers derive deterministically (e.g. a
  GUID-derived role assignment), a rebuild MUST reconcile orphaned prior grants against the registry
  — a stale deterministic id collides with the new identity and blocks redeploy. The registry is the
  reconciliation source.

## Config is rendered, never hand-edited live

Live/runtime config is **rendered from a template + the registry**, then applied by the canonical
apply script — never edited directly on the target. Edit the template or the registry, replay,
apply. A rejected render is preserved (a `.clobbered.<timestamp>` safety artifact) rather than
silently overwriting good config; that is a validation rollback, not an incident.

## One identity per consumer, least privilege

Each consumer repo/environment authenticates with its **own** identity (blast-radius isolation) via
a short-lived, runtime-minted credential (OIDC/WIF), not a stored long-lived secret. A leaked
identity is one rotation away, not an org-wide drill. The registry records which identity maps to
which target so the mapping is auditable.

## How to apply

1. Create the per-repo registry; move every duplicated environment identifier into it; delete the
   copies (no "deprecated — see X" stubs — remove them outright).
2. Point every script / workflow / IaC param at the registry as the single reader source.
3. Store secrets in the secret store; put only the store reference + secret **names** in the
   registry; resolve by name at run time.
4. Render live config from template + registry; apply via the canonical script; never hand-edit the
   target.
5. Use one least-privilege identity per consumer; reconcile deterministic-id grants against the
   registry on any rebuild.
