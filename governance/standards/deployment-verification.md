# Deployment Verification — recovery point before, proof after

> Every apply that mutates live state MUST be bracketed: a **recovery point before** the first
> destructive op, and a **verification probe after** it. "The apply script exited 0" is not proof
> the system works — drive the real surface and observe it. This generalises the
> [snapshot-before-apply](snapshot-before-apply.md) pattern beyond any one cloud.

## Why

An apply that half-succeeds can leave a service that won't restart, a config that rejects the next
apply, or a silently-degraded runtime. Without a recovery point, recovery means a rebuild — hours,
not minutes. Without a post-apply probe, a broken deploy is discovered by a user, not by the
pipeline. The bracket turns both into a fast, bounded, observable operation.

## Before — take a recovery point

Before the first state mutation, capture a revert target:

- **The mechanism is per-substrate** — an OS-disk/volume snapshot for a VM; the prior image tag /
  previous revision for a container or serverless service; the previous template/plan for
  infra-as-code; a dump for a stateful store. The **rule is substrate-agnostic**: a fast revert
  target exists before you mutate.
- **Take it from the pipeline identity, not the host.** The CI runner holds the narrowly-scoped,
  short-lived credential (e.g. OIDC/WIF) with exactly the snapshot/rollback right; the runtime
  identity deliberately does not (granting it would over-grant delete rights on a surface that runs
  untrusted code). Apply scripts MAY keep a **best-effort** in-script fallback for operator-driven
  runs — warn loudly and proceed when the identity lacks the right.
- **Overrides are explicit and visible.** `--dry-run` skips it (nothing is mutated). `--no-snapshot`
  (or equivalent) is for a throwaway target only and MUST log the override. A production apply omits
  the override.
- **Retention is bounded, not inline.** A succeeded apply may still need rollback hours later (a
  slow-burn leak), so scripts do not delete recovery points inline; a dedicated prune cron enforces
  a bounded retention (the org default is **14 days** — `COST-D1`) so they don't accumulate cost.

## After — verify against the real surface

An apply is not done until a probe drives the deployed surface with the **real runtime identity and
config** and observes healthy behaviour:

- **Probe the configured path, not a repo heuristic.** Hit the actual endpoint / invoke the actual
  tool / read the actual health signal the way a client would — through the gateway/env/user the
  runtime uses, not a local approximation that can pass while production fails.
- **Assert on behaviour, not exit codes.** A 200, a valid tool response, a fresh heartbeat, an
  expected log line — a concrete signal, checked. Exit 0 is necessary, never sufficient.
- **Fail loud and actionable.** A failed probe surfaces `fix:` + `next:` and, where progressive
  delivery is wired, triggers auto-revert to the recovery point.

## Pure-infra changes use a matching shape

An infra-as-code apply (e.g. template deploys) verifies with a plan/what-if diff before and a
resource-state assertion after; its rollback is a redeploy from the prior template, not a disk
revert. The bracket still holds — recovery target before, proof after — the mechanism just matches
the substrate.

## How to apply

1. Identify the substrate; choose the matching recovery-point mechanism and the matching rollback.
2. Take the recovery point from the pipeline identity before the first mutation; keep a best-effort
   in-script fallback for operator runs; make `--dry-run` / `--no-snapshot` explicit and logged.
3. Wire a bounded-retention prune cron (14-day default) so recovery points don't accumulate.
4. After apply, run a probe that drives the real surface with the real identity and asserts on
   behaviour; on failure, surface `fix:`/`next:` and auto-revert where available.
5. Never call a deploy done on exit code alone; name the verification evidence in the handoff/PR.
