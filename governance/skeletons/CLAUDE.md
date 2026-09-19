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

## Stable SDLC commands

```bash
make bootstrap
make prepare
make check
make check-all
```

`tc-pipelines` supplies the released environment and task graph. `tc-fitness`
executes the configured fitness profile inside that graph. Local and hosted
runs bind the same `tc-sdlc.lock`, task definitions and input identities.

Repositories still migrating to `tc-sdlc` use the commands implemented by their
current Makefile. Their migration state and removal inventory belong in the
repository roadmap.

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
