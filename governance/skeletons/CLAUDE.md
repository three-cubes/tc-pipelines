# CLAUDE.md — Engineering Entry Point for {{REPO}}

This file routes contributors to the canonical authoring and SDLC contracts.
Product runtime behaviour lives with the product artefact.

<!-- INCLUDE: _canonical-standards-banner.md -->

## Read first

1. [`ETHOS.md`](ETHOS.md) — product principles.
2. [`AGENTS.md`](AGENTS.md) — authoring boundary.
3. [`RESOLVER.md`](RESOLVER.md) — intent-to-location routing.
4. [`CONTRIBUTING.md`](CONTRIBUTING.md) — local and PR workflow.
5. [`SCORECARD.md`](SCORECARD.md) — product health evidence.

## Current compatibility commands

```bash
make setup
make prepare
make check
```

The rendered compatibility Makefile provides these three targets today.
`make setup` installs hooks, `make prepare` performs deterministic preparation
and `make check` prepares then runs the configured `tc-fitness` gate.

After the coordinated `tc-sdlc` adoption change replaces the compatibility
Makefile, the stable product commands remain `make bootstrap`, `make prepare`,
`make check` and `make check-all`.

## Commit and PR identity

Create local commits with canonical `three-cubes-agent[bot]` author and committer
metadata. Send remote writes through the trusted host broker or GitHub Actions
GitHub App path. The agent harness receives no token or Key Vault credential.

Carry no AI or model attribution in commits, PRs or source. The shared
`tc-fitness` checks enforce canonical identity and attribution policy.

Link completed work with `Closes #N` and partial work with `Refs #N` in the PR
body. Use the branch name supplied by Linear.

## Change placement

- environment, task graph, workflow, evidence and governance behaviour belongs
  in `tc-pipelines`;
- shared evaluation behaviour belongs in `tc-fitness`;
- product source, tests, generators, qualification journeys and deployment
  values belong in this repository.

Update `RESOLVER.md` when a new product surface has no clear home.

## Verification evidence

Record the tested commit, exact command, SDLC lock, task identities and complete
terminal result. Preparation output is committed with its input change. A
release or deployment claim includes the candidate digest and retained receipt.

## Trunk workflow

Use one feature branch and one PR for the coherent change. Reconcile with
current `main`, rerun the required graph, push the tested commit and resolve
review conversations. Ordinary changes merge on green. Control-plane changes
receive the configured human code-owner review.
