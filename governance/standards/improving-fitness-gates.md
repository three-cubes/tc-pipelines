# Improving the Shared SDLC Product

Change shared behaviour in its canonical home, qualify it against reference
consumers, publish one coordinated SDLC release and upgrade consumers through
the generated release lock.

The product boundary is
[`ai-sdlc-product-architecture.md`](ai-sdlc-product-architecture.md). The gate
quality bar is [`../gate-hardening.md`](../gate-hardening.md).

## Canonical homes

- `tc-fitness` owns fitness evaluation, shared checks and structured findings.
- `tc-pipelines` owns the released environment, task graph, workflow entrypoints,
  evidence, release/deployment protocols and governance tooling.
- consumer repositories own product configuration, tests, qualification
  journeys and deployment values.

## Change fitness behaviour

1. Define the expected finding and public check contract in `tc-fitness`.
2. Add behavioural tests for passing, failing and unavailable-dependency paths.
3. Run the candidate engine against the Python-only, mixed-language and
   `tc-agent-zone` reference fixtures through the candidate SDLC graph.
4. Compare the structured fitness ledger with the current released engine.
5. Classify every intended ledger change in the release notes.
6. Publish the engine candidate and bind it into a candidate `tc-pipelines`
   release catalogue.
7. Run the coordinated release fixtures.
8. Publish the SDLC release and let the upgrade service open consumer PRs.

A change to fitness policy is a control-plane change and receives the configured
human code-owner review.

## Change environment or pipeline behaviour

1. Change the `tc-sdlc` package, canonical image, hosted workflow or deployment
   protocol in `tc-pipelines`.
2. Exercise the change locally through its package or image interface.
3. Run reference consumer fixtures through the candidate release catalogue.
4. Verify affected selection, complete graph behaviour and retained evidence.
5. Materialise and validate every immutable workflow/action reference.
6. Publish one coordinated SDLC release.
7. Let generated upgrade PRs update consumers.

Hosted workflow YAML owns GitHub events, credentials, runners and protected
environments. Portable execution behaviour enters the package and task graph.

## Preparation behaviour

Deterministic formatting, generation, manifest and lock maintenance belongs in
the `prepare` task. Local preparation updates the working tree. Hosted
preparation produces the same result before evaluation and reports a patch when
committed content was stale.

Preparation tasks declare inputs and outputs, run without deployment credentials
and reach a clean fixed point on their second execution. Evaluation tasks remain
read-only.

## Candidate qualification

A candidate release is accepted when:

- every reference fixture bootstraps from an empty checkout;
- the same task definitions run natively, in the canonical image and in hosted
  execution;
- fitness ledgers contain only reviewed changes;
- a representative wrong package, image, workflow or fitness identity fails;
- current consumer commands retain their contract during migration;
- release and rollback evidence is complete for changed deployment surfaces.

## Consumer rollout

The upgrade PR records the previous and proposed release catalogues, generated
lock diff, affected tasks and ledger diff. Required checks and code-owner review
apply normally. Consumers upgrade on their selected schedule without hand-editing
individual pins.

## Current compatibility surfaces

The current `fitness-engine-canary.yml`, direct engine pins, direct workflow
pins and consumer-repin dispatcher remain as migration surfaces. Their behaviour
is represented in reference fixtures before removal. New shared capability is
implemented in the coordinated package, image, graph or release catalogue.

## Harness routing

Every repository authoring entrypoint links to
[`../STANDARDS.md`](../STANDARDS.md) and the product architecture. This sends
changes to the canonical implementation rather than a consumer-local copy.
