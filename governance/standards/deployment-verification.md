# Deployment Verification

Deployment completes when the qualified candidate passes product verification
on the target and the transaction records promotion, rollback and cleanup.

This standard implements the deployment boundary in
[`ai-sdlc-product-architecture.md`](ai-sdlc-product-architecture.md).

## Transaction

1. Verify the candidate digest, SDLC lock and qualification receipt.
2. Acquire the target deployment lock.
3. Capture the recovery artefacts required by the changed state.
4. Converge host prerequisites.
5. Pull and start the qualified candidate digest.
6. Run dependency health checks.
7. Run product verification journeys through the production identity and route.
8. Promote the candidate or restore the predecessor.
9. Record cleanup and release the lock.

Every phase has a typed input, bounded execution time and machine-readable
result. The terminal receipt names the candidate, runtime, probes, recovery
identity and cleanup result.

## Recovery selection

Select recovery artefacts from the state changed by the deployment:

| Changed state | Recovery artefact |
|---|---|
| Application container | Qualified predecessor image digest and Compose configuration |
| Protected application state | Content-addressed archive or store-native backup plus manifest |
| Host packages, users, filesystem or systemd | Ansible state plus host/disk recovery point appropriate to the change |
| Infrastructure resource | Reviewed prior template/state and provider recovery mechanism |
| Database schema or content | Product-defined transactional rollback or backup |

The deployment preflight verifies that the selected recovery set covers every
mutated state class. Recovery artefacts carry an expiry and remain available
through the configured rollback window.

## Verification journeys

Health checks establish process and dependency readiness. Product verification
establishes useful behaviour. Journeys execute through the configured endpoint,
identity, secrets and persistent state used by production.

The receipt records each probe's input identity, bounded output, duration and
verdict. Process exit status is diagnostic evidence; the asserted product
outcome determines the verdict.

## Failure behaviour

A failure before mutation releases the lock and records no-change. A failure
after candidate start restores the predecessor and reruns predecessor health.
An unsuccessful rollback leaves the target held, retains diagnostics and names
the next recovery operation.

The workflow summary indexes the full retained receipt. Console logs remain
bounded and secret-safe.

## Acceptance criteria

- the deployed digest equals the qualified digest;
- required persistent state survives cutover;
- filesystem and access observations satisfy the runtime contract;
- dependency health passes;
- product journeys pass through the production route;
- a forced failed journey restores the predecessor;
- rollback health is observed;
- cleanup retains active and predecessor recovery data and removes expired data;
- the terminal receipt is retained and linked to the candidate.
