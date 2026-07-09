# Snapshot-before-apply

Every apply script that mutates live infrastructure MUST take a recovery point before its first destructive op — the concrete example throughout this doc is an Azure VM OS-disk snapshot. The snapshot is the last-known-good the rollback drill reverts to.

## Why

A failed apply can leave a VM in a state where:

- The gateway service won't restart cleanly.
- A rendered config rejects subsequent applies (working-tree-uncommitted-changes guard fires on `.clobbered.<timestamp>` files).
- A new systemd unit shadows the canonical one.

A snapshot lets the operator revert to the last-known-good in ~5 minutes. Without it, recovery means rebuilding the VM from `vm-bootstrap.sh` — hours, not minutes.

## How — the canonical pattern

**Snapshots are taken from the CI runner, NOT from the VM itself.** The runner has a WIF-bound identity with `Disk Snapshot Contributor` narrowly scoped to `RG-AGENTS-CORE`; the VM-local managed identities deliberately don't have this role (granting it would also grant snapshot-delete + storage-delete rights per the built-in role definition, which is too broad for a runtime identity that runs untrusted skill code).

The CI workflow `.github/workflows/deploy-on-merge.yml` does this:

```yaml
- name: Snapshot vm-openclaw + vm-hermes-poc
  run: |
    STAMP=$(date -u +%Y%m%d-%H%M%S)
    for vm in vm-openclaw vm-hermes-poc; do
      OSDISK_ID=$(az vm show -g RG-AGENTS-CORE -n "$vm" \
        --query 'storageProfile.osDisk.managedDisk.id' -o tsv)
      az snapshot create \
        -g RG-AGENTS-CORE \
        -n "${vm}-osdisk-pre-deploy-on-merge-${STAMP}" \
        --source "$OSDISK_ID"
    done
```

After the snapshot succeeds, the workflow invokes the apply scripts with `--no-snapshot` so the in-script attempt below is skipped.

### Apply scripts — best-effort fallback

Each apply script ALSO calls `take_snapshot` from `devsecops/scripts/lib/snapshot.sh` after KV auth and before any state mutation, as a safety net for operator-driven applies:

```bash
source "${REPO_ROOT}/devsecops/scripts/lib/snapshot.sh"
if [[ "$DRY_RUN" != "true" ]]; then
  if ! take_snapshot vm-openclaw apply-openclaw-config; then
    warn "Continuing apply WITHOUT snapshot — rollback will require manual restore from prior snapshot."
  fi
fi
```

The in-script call is **best-effort** — if the current `az` identity lacks rights (the common case for VM-local applies under the system MI), the helper warns loudly and the apply proceeds. Production deploys via CI never hit this path: the workflow takes the snapshot upstream and passes `--no-snapshot`.

The helper:

- Uses `az snapshot create -g $SNAPSHOT_RG -n <vm>-osdisk-pre-<op-tag>-YYYYMMDD-HHMMSS --source <osdisk-id>` — the canonical shape from `devsecops/runbooks/runbook-imds-block-apply.md` §1.
- Authenticates via the existing `az` context first; falls back to system MI if no context exists.
- Differentiates "VM not found" from "AuthorizationFailed" — the latter is the normal case for VM-local MI and emits a specific WARN pointing at the CI-driven snapshot path.
- Honours `SKIP_SNAPSHOT=true` (set by `--no-snapshot`) for explicit acknowledgement.

## How — the override

Two paths to bypass the snapshot:

- **`--no-snapshot`** flag on either apply script. Use during iterative dev when you know the VM is throwaway. The script logs `SKIP_SNAPSHOT=true` to make the override visible.
- **Dry-run**. `--dry-run` skips the snapshot entirely since no state is mutated.

Production apply (operator OR CI-driven) MUST omit `--no-snapshot`.

## Failure modes the helper catches

| Symptom | Cause | Fix |
|---|---|---|
| `az CLI not on PATH` | Apply running on a host without az installed | `apt-get install azure-cli` |
| `no authenticated az context` | System MI not attached, or RBAC missing | Attach MI; grant `Disk Snapshot Contributor` on `RG-AGENTS-CORE` |
| `<vm-name> not found in RG-AGENTS-CORE` | Wrong VM name OR wrong RG (override via `SNAPSHOT_RG`) | `az vm list -g RG-AGENTS-CORE -o table` |
| `az snapshot create failed` | RBAC or quota | Check Disk Snapshot Contributor + storage quota |

Every failure surfaces with `fix:` + `next:` lines so the next agent (human or LLM) has an immediate action.

## Retention

The apply scripts do NOT clean up snapshots. Two reasons:

- An apply that succeeds at T may still need rollback later (e.g. a slow-burn cli-proxy memory leak surfacing 24h after deploy).
- Snapshot deletion is a privileged op that fits better in a dedicated `prune-snapshots.sh` cron than inline in apply.

The current convention is to keep snapshots for 14 days; a dedicated prune cron (bound to a narrowly-scoped `Snapshot Reader + Disk Pool Operator` role) will formalise this.

## CI-driven apply integration

The CI apply workflow (`.github/workflows/deploy-main.yml`) inherits this discipline. The workflow runs the apply script directly — no separate snapshot step is needed in the workflow itself; the script's own `take_snapshot` call fires before any mutation.

For pure infrastructure changes (Bicep applies), the snapshot lives in the runbook — Bicep applies use a different rollback shape (`az deployment ... what-if` + redeploy from prior template), not OS-disk revert.

## Related

- The IMDS-block apply runbook — origin of the canonical `az snapshot create` shape.
- The platform emergency-recovery runbook — uses snapshots for full-platform restore.
- The validation-and-backpressure standard — places snapshot-before-apply in the broader validation ladder.
- The security-framework standard — references snapshot discipline for destructive op gating.
