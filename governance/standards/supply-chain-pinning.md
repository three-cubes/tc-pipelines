# Supply-Chain Pinning

The coordinated SDLC release catalogue is the authored source for executable
identities. It binds:

- the `@three-cubes/tc-sdlc` package version;
- the canonical OCI image digest;
- the GitHub workflow commit;
- the schema version;
- the compatible `tc-fitness` version.

The generated consumer `tc-sdlc.lock` records that release. `tc-sdlc upgrade`
materialises every required reference in one reviewable change.

## GitHub workflow references

GitHub requires `uses:` references to contain a literal ref. Expressions and
variables cannot supply that coordinate. Every workflow and action reference
therefore resolves to a full commit SHA.

Repeated workflow SHAs are generated projections of the coordinated release,
rather than independent values maintained by a contributor. The generator
updates all call sites and validates the complete referenced action graph.

## Internal action references

A commit cannot contain a reference to its own future hash. The release builder:

1. identifies the reviewed commit containing the target content;
2. resolves every referenced action and reusable workflow recursively;
3. materialises immutable references to reviewed content;
4. verifies the resulting graph in a release fixture;
5. publishes the workflow commit in the release catalogue.

An unchanged action may retain an older immutable ancestor when its complete
executed target graph is content-equivalent. The verifier reports each retained
coordinate and its content identity.

Merge commits preserve reviewed target commits in repository ancestry. Repository
merge settings use merge commits and protect release tags from update or deletion.

## Consumer upgrades

The release event opens one App-authored upgrade PR in each enrolled consumer.
The PR updates:

- the SDLC package version;
- the canonical image digest;
- literal workflow and action SHAs;
- the compatible `tc-fitness` dependency;
- the schema and generated lock;
- any generated compatibility material still required during migration.

The consumer validates the release catalogue, regenerates the lock, executes
preparation and the affected graph, then enables auto-merge subject to required
checks and code-owner review.

## Independent trust roots

A verifier may carry an independent expected digest or identity when reading it
from the evaluated input would make the check circular. These values are named
as trust roots, generated from the reviewed release and covered by tests that
exercise a wrong value.

The materialiser distinguishes generated projections from independent trust
roots. Generated projections update automatically. Trust-root changes are
listed separately in the review summary.

## Current compatibility path

Existing workflows contain direct SHA references and use
`test_self_pin_freshness`, `test_uses_ref_pinning` and the current consumer-repin
dispatcher. These remain enforced until the release-catalogue materialiser has
passed the equivalent nested-reference and consumer-upgrade fixtures.

After parity, the materialiser replaces manual self-pin and consumer-repin
procedures. Literal immutable references remain because GitHub requires them;
their maintenance becomes generated SDLC work.
