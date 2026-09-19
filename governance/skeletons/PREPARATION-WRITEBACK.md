# Deterministic preparation writeback receipt

The credential-free producer is the SHA-pinnable
`actions/preparation-writeback` composite action. Its `snapshot` mode records
only the path, mode, digest and content-state identity of the checked-out pull
request; it never copies repository contents into the snapshot. After a
deterministic normaliser runs, `produce` emits a bounded JSON patch containing
content only for changed or new files and `tc.sdlc/preparation-receipt/v1`. The
receipt binds repository, pull request, head commit and Git tree, source
workflow run and attempt, pre- and post-preparation content-tree digests, patch
digest, patch byte count and issue time.

`.github/workflows/preparation-writeback.yml` is a reusable trusted consumer.
The existing default-branch `workflow_run` fan-in calls it with the triggering
run identity and pinned tc-pipelines SHA, so no duplicate post-CI workflow is
created. It returns `changed`, `no-artifact`, or `ineligible`; callers continue
to gate only their canonical current fan-in. It no-ops when a completed PR run
does not publish a preparation artifact, while any named but invalid evidence
fails closed.

The consumer selects exactly one non-expired, bounded artifact whose name and
GitHub metadata bind it to that PR run, rejects forks and moved heads, and
checks out the exact head into a fresh detached temporary repository. The ZIP
must contain the two exact member names in either order; duplicates, nesting,
unexpected entries and oversized compressed or extracted streams are rejected.
The immutable validator accepts only regular `0644` or `0755` files and
deletions; it rejects stale receipts, changed bytes, duplicate or unsafe paths,
symlinks, non-regular files and content states that do not reproduce the
receipt's post tree.

The fresh checkout fetches private consumer repositories with the caller's
read-only workflow token in an ephemeral Git extraheader. It is never put in a
remote URL or local Git config. The separate App write token is still minted
only after receipt validation and application.

The consumer does not invoke repository commands or checkout actions from the
pull request. It mints the canonical App token only after validation and local
application, commits as `three-cubes-agent[bot]`, and pushes with a lease bound
to the exact recorded head SHA.

## Producer integration seam

The repository Quality gate must call the pinned composite action's `snapshot`
mode before deterministic preparation and its `produce` mode after it, then
upload the two files under `preparation-receipt-pr<pr>-run<run>-attempt<attempt>`.
Its normal quality evaluation must still fail on a non-empty preparation diff:
the writer is a safe follow-up mechanism, never an admission path for evaluated
bytes that are not the PR head.
