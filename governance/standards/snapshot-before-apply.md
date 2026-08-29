# Snapshot-before-apply

Every apply script that mutates deployed application, configuration, data, or infrastructure bytes takes a recovery point before its first destructive operation. This document uses an Azure VM OS-disk snapshot as the example. The snapshot provides the last-known-good state for the rollback drill. The reversible pre-snapshot admission path and container-only deployment path define the bounded alternatives.

## Why

A failed apply can leave a VM in a state where:

- The gateway service won't restart cleanly.
- A rendered config rejects subsequent applies (working-tree-uncommitted-changes guard fires on `.clobbered.<timestamp>` files).
- A new systemd unit shadows the canonical one.

A snapshot lets the operator revert to the last-known-good in ~5 minutes. Without it, recovery means rebuilding the VM from `vm-bootstrap.sh` — hours, not minutes.

## How — the canonical pattern

**Snapshots are taken from the CI runner, NOT from the VM itself.** The runner has a WIF-bound identity with `Disk Snapshot Contributor` narrowly scoped to `RG-AGENTS-CORE`; the VM-local managed identities deliberately don't have this role (granting it would also grant snapshot-delete + storage-delete rights per the built-in role definition, which is too broad for a runtime identity that runs untrusted skill code).

The consumer's `deploy-on-merge.yml` calls the tc-pipelines [`azure-vm-deploy.yml`](../../.github/workflows/azure-vm-deploy.yml) reusable. When no remote admission is configured, its [`snapshot-azure-vm-disk`](../../.github/actions/snapshot-azure-vm-disk/action.yml) composite runs the canonical snapshot shape before the apply:

```yaml
- name: Snapshot vm-openclaw + vm-hermes-poc
  run: |
    STAMP=$(date -u +%Y%m%d-%H%M%S)
    CREATED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    EXPIRES_AT=$(date -u -d '+48 hours' +%Y-%m-%dT%H:%M:%SZ)
    for vm in vm-openclaw vm-hermes-poc; do
      OSDISK_ID=$(az vm show -g RG-AGENTS-CORE -n "$vm" \
        --query 'storageProfile.osDisk.managedDisk.id' -o tsv)
      az snapshot create \
        -g RG-AGENTS-CORE \
        -n "${vm}-osdisk-pre-deploy-on-merge-${STAMP}" \
        --source "$OSDISK_ID" \
        --incremental true \
        --tags tc-managed-by=tc-pipelines tc-purpose=pre-deploy-recovery \
          "tc-source-vm=${vm}" "tc-created-at=${CREATED_AT}" \
          "tc-expires-at=${EXPIRES_AT}"
    done
```

After the snapshot succeeds, the workflow invokes the apply scripts with `--no-snapshot` so the in-script attempt below is skipped.

### Reversible pre-snapshot admission path

The reusable may run an explicitly configured remote admission preflight before
the snapshot when the deploy must freeze writers or acquire a lease before it
can prove that runtime-authored state has been captured. It limits the work to
reversible coordination:

- Keep preflight to writer freezes and lease acquisition. Apply, publish,
  service restart, image replacement, and durable data changes begin after the
  recovery point.
- Any freeze or lease must be exactly reversible by the declared
  `failure-cleanup-script`; cleanup must be safe to run on every target.
- The workflow records the cleanup obligation before the first remote
  invocation. A partial preflight or failed later target must therefore run
  cleanup on failure or cancellation, even when aggregate admission never
  passed.
- Admission evidence is published only after every target succeeds and the
  target set agrees on one content-addressed receipt digest.
- The recovery-point snapshot still completes before the first change to
  deployed application, configuration, data, image, service, or infrastructure
  state.

If a preflight cannot meet every condition, take the recovery point before it.

### Container-only deployment path

A production deployment sets `snapshot-policy=forbidden` when its rollback
boundary is wholly inside governed container and configuration paths. The path
uses every condition below:

- Before the first mutation, create and verify a protected path and configuration backup
  that binds the exact restored paths, archive, manifest, and digests without
  exposing secret values.
- Record and retain an immutable predecessor container image that can be
  reactivated with the protected backup during automated rollback.
- Produce and verify an immutable rollback receipt before apply. The receipt
  must bind the exact protected paths, backup archive and manifest digests, and
  predecessor OCI image digest. Pass its content address through the reusable
  workflow's `container-rollback-receipt-digest` input as
  `sha256:<64 lowercase hex>`; admission validates the digest before WIF or
  cloud operations.
- Limit normal apply and rollback to the container workload and its governed
  configuration. The workflow skips the snapshot action and Azure storage
  operations.
- Set `snapshot-policy=forbidden`, `skip-snapshot=true`, and the verified
  `container-rollback-receipt-digest` on the reusable workflow. Admission
  accepts `snapshot-policy=forbidden` with `skip-snapshot=true` and a valid
  receipt digest before WIF or cloud operations. `snapshot-policy=allowed` with
  `skip-snapshot=true` provides the explicit development override.
- Treat host disaster recovery separately. Host disaster recovery runs as a
  separate manual operation; the container rollback receipt records the
  application recovery path.

Host package, kernel, filesystem-layout, disk, VM, network, and other
infrastructure changes use the normal host recovery point before apply.

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

Three paths select an alternative to the default snapshot:

- **`--no-snapshot`** flag on either apply script. Use during iterative dev when you know the VM is throwaway. The script logs `SKIP_SNAPSHOT=true` to make the override visible.
- **Dry-run**. `--dry-run` skips the snapshot entirely since no state is mutated.
- **Governed container-only deployment path**. The reusable workflow admits it
  with `snapshot-policy=forbidden`, `skip-snapshot=true`, and a verified
  `container-rollback-receipt-digest` when the container-only deployment path
  above is satisfied.

Production apply (operator or CI-driven) uses a recovery point. The reusable
admits the container-only deployment path with `snapshot-policy=forbidden`,
`skip-snapshot=true`, and a verified `container-rollback-receipt-digest`.

## Failure modes the helper catches

| Symptom | Cause | Fix |
|---|---|---|
| `az CLI not on PATH` | Apply running on a host without az installed | `apt-get install azure-cli` |
| `no authenticated az context` | System MI not attached, or RBAC missing | Attach MI; grant `Disk Snapshot Contributor` on `RG-AGENTS-CORE` |
| `<vm-name> not found in RG-AGENTS-CORE` | Wrong VM name OR wrong RG (override via `SNAPSHOT_RG`) | `az vm list -g RG-AGENTS-CORE -o table` |
| `az snapshot create failed` | RBAC or quota | Check Disk Snapshot Contributor + storage quota |

Every failure surfaces with `fix:` + `next:` lines so the next agent (human or LLM) has an immediate action.

## Retention

The reusable deploy workflow creates incremental snapshots and writes these tags:

- `tc-managed-by=tc-pipelines`
- `tc-purpose=pre-deploy-recovery`
- `tc-source-vm`, `tc-operation`, and `tc-created-at` identify the deployment.
- `tc-expires-at` defines the recovery window.

The default recovery window is 48 hours. A caller may set
`snapshot-retention-hours` to a positive whole number when its rollback window
requires more time. The consuming repository runs a scheduled privileged
pruner that deletes only snapshots with `tc-managed-by=tc-pipelines` whose
`tc-expires-at` timestamp has passed. An operator extends a specific recovery
point by changing its expiry tag or removing the `tc-managed-by` tag before the
scheduled prune.

## CI-driven apply integration

The consumer's CI apply workflow (`.github/workflows/deploy-on-merge.yml`) calls the tc-pipelines [`azure-vm-deploy.yml`](../../.github/workflows/azure-vm-deploy.yml) reusable. The optional reversible admission preflight runs first. By default, the [`snapshot-azure-vm-disk`](../../.github/actions/snapshot-azure-vm-disk/action.yml) composite takes the recovery point from the pipeline WIF identity before apply and passes `--no-snapshot` to the apply script. The governed container-only deployment path skips that action when `snapshot-policy=forbidden` and `skip-snapshot=true` agree. The in-script `take_snapshot` fallback serves operator-driven runs.

For pure infrastructure changes (Bicep applies), the snapshot lives in the runbook — Bicep applies use a different rollback shape (`az deployment ... what-if` + redeploy from prior template), not OS-disk revert.

## Related

- The IMDS-block apply runbook — origin of the canonical `az snapshot create` shape.
- The platform emergency-recovery runbook — uses snapshots for full-platform restore.
- The validation-and-backpressure standard — places snapshot-before-apply in the broader validation ladder.
- The security-framework standard — references snapshot discipline for destructive op gating.
