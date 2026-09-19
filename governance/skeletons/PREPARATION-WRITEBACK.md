# Deterministic preparation writeback receipt

The credential-free producer is the SHA-pinnable
`actions/preparation-writeback` composite action. Its `snapshot` mode records
only the path, mode, digest and content-state identity of the checked-out pull
request; the snapshot remains proportional to repository state rather than
file content. After a
deterministic normaliser runs, `produce` emits a bounded JSON patch and
`tc.sdlc/preparation-receipt/v1`. The
receipt binds repository, pull request, head commit and Git tree, source
workflow run and attempt, pre- and post-preparation content-tree digests, patch
digest, patch byte count and issue time.

`.github/workflows/preparation-writeback.yml` is a reusable trusted consumer.
The existing default-branch `workflow_run` fan-in calls it with the triggering
run identity. The reusable pins its trusted validator and token action, uses
the existing post-CI workflow, and returns `changed`, `no-artifact`, or
`ineligible`; callers continue
to gate only their canonical current fan-in. It no-ops when a completed PR run
does not publish a preparation artifact, while any named but invalid evidence
fails closed.

Consumer templates pass their immutable `{{PIPELINES_SHA}}` as the validator
revision. tc-pipelines itself calls the local reusable from its default-branch
`workflow_run` and passes that run's immutable `github.sha`; this avoids a
self-repin cycle without allowing a PR to choose the validator bytes.

The consumer selects exactly one non-expired, bounded artifact whose name and
GitHub metadata bind it to that PR run, rejects forks and moved heads, and
checks out the exact head into a fresh detached temporary repository. The ZIP
must contain the two exact member names in either order; duplicates, nesting,
unexpected entries and oversized compressed or extracted streams are rejected.
The immutable validator admits the `python-ruff-v1` policy: pinned Ruff 0.16.8 runs
with fixed `E,F,I,UP,B,S,RUF` selection, fixed ignores `E501,RUF022`, safe
fixes only, Python 3.12 and 110-column formatting over tracked `.py`/`.pyi`
files. Ruff loads the declarative repository configuration and honours its
excludes with `--force-exclude`; the consumer replays the policy from the
pristine detached head and compares the exact patch and post-tree before
writing. The policy registry, tool version and permitted paths are all owned by
the immutable tc-pipelines revision.

The fresh checkout fetches private consumer repositories with the caller's
read-only workflow token in an ephemeral Git extraheader. A separately scoped
App token reads the pinned private `tc-pipelines` validator, while the consumer
App write token is minted after receipt validation and application.

The consumer validates the receipt and applies it in a detached temporary
checkout, commits as `three-cubes-agent[bot]`, and pushes with a lease bound to
the exact recorded head SHA.

## Producer integration seam

The repository Quality gate calls the pinned composite action's `snapshot`
mode before deterministic preparation and its `produce` mode after it, then
upload the two files under `preparation-receipt-pr<pr>-run<run>-attempt<attempt>`.
A non-empty preparation diff emits an explicit red required context; a skipped
context records that evaluation waits for the prepared head. The writer applies
the prepared head, and the trusted reusable resolves the exact PR-head, merge-group or
push SHA from GitHub event metadata once, then passes that value to every
evaluator; callers cannot override it with a merge ref or another commit.
