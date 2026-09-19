# Recovery Point Before Apply

Every state-changing deployment selects and verifies a recovery point before its
first mutation. The recovery mechanism matches the state being changed.

The full transaction and verification contract is
[`deployment-verification.md`](deployment-verification.md).

## Recovery policy

The deployment request declares changed state classes and the matching recovery
artefacts. Preflight validates complete coverage.

Container-only deployment normally uses:

- the qualified predecessor image digest;
- the previous Compose configuration;
- a protected-state manifest and archive where container state is external;
- the product's knowledge-harvest receipt where learned state is promoted.

Host or infrastructure mutation adds the recovery mechanism appropriate to that
surface. A VM disk snapshot is one host-level mechanism; it is used when host or
disk state changes and the rollback objective requires it.

## Identity and permissions

The hosted deployment identity creates cloud recovery resources through
short-lived workload identity. The target deployment account reads the approved
candidate and applies allowlisted operations. Product runtime identities receive
only the filesystem and service permissions declared in the runtime contract.

## Retention and cleanup

Every recovery artefact records:

- target and candidate identity;
- predecessor identity;
- creation and expiry time;
- state classes covered;
- content digest or provider resource identity;
- verification result.

The default operational window is 48 hours. Named incident evidence and product
policy may extend retention. Cleanup records deleted and retained artefacts and
their byte or provider identities.

## Current Azure compatibility path

The existing `azure-vm-deploy.yml` workflow and snapshot composite remain the
host-recovery compatibility implementation. Container deployments may use the
existing protected-path archive and predecessor-image receipt when their
preflight proves complete coverage.

During migration, these operations become implementations of the typed recovery
interface. Consumer-specific snapshot selection and shell payloads are removed
after the equivalent Ansible, Compose and receipt journeys pass.

### Reversible pre-snapshot admission path

The current reusable may acquire reversible coordination before the host
snapshot. Keep preflight to writer freezes and lease acquisition. Any partial preflight
records its cleanup obligation before the first remote invocation, so
the declared cleanup runs on failure or cancellation. Application, service,
image, configuration and durable-data mutation begins after the recovery point.

### Container-only deployment path

The current workflow supports the governed container recovery contract while it
migrates to the typed recovery interface:

- Create and verify a protected path and configuration backup before mutation.
- Record an immutable predecessor container image.
- Bind the protected paths, archive and manifest digests, and predecessor OCI
  digest in the rollback receipt.
- Pass its digest through `container-rollback-receipt-digest`.
- Set `snapshot-policy=forbidden` and `skip-snapshot=true`.
- The workflow skips the snapshot action and Azure storage operations.
- Admission accepts `snapshot-policy=forbidden` with `skip-snapshot=true` and a
  valid rollback receipt.
- `snapshot-policy=allowed` with `skip-snapshot=true` provides the explicit
  development compatibility override.
- Host disaster recovery runs as a separate manual operation.

## Acceptance criteria

- preflight identifies every mutated state class;
- each state class has a verified recovery artefact;
- the predecessor is runnable before mutation;
- recovery artefacts remain available through the rollback window;
- an exercised failure restores the predecessor and its protected state;
- cleanup removes expired artefacts and retains the active recovery set.
