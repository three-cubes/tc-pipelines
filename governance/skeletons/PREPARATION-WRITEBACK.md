# Deterministic preparation writeback receipt

The preparation producer is credential-free. It snapshots the checked-out pull
request head before a deterministic normaliser runs, then emits a bounded JSON
patch and `tc.sdlc/preparation-receipt/v1`. The receipt binds the repository,
pull request, head commit and Git tree, source workflow run and attempt, pre- and
post-preparation content-tree digests, patch digest, patch byte count and issue
time.

`workflows/preparation-writeback.yml.tmpl` is a default-branch `workflow_run`
consumer. It selects exactly one non-expired artifact whose name and GitHub
metadata bind it to the successful PR run, rejects forks and moved heads, and
checks out the exact head into a fresh detached temporary repository. The
immutable tc-pipelines validator accepts only regular `0644` or `0755` files
and deletions; it rejects stale receipts, changed bytes, duplicate or unsafe
paths, symlinks, non-regular files and content states that do not reproduce the
receipt's post tree.

The consumer does not invoke repository commands or checkout actions from the
pull request. It mints the canonical App token only after validation and local
application, commits as `three-cubes-agent[bot]`, and pushes with a lease bound
to the exact recorded head SHA.

## Producer integration seam

The repository Quality gate must call `preparation_writeback.py snapshot` before
the deterministic preparation command and `produce` after it, then upload the
two files under `preparation-receipt-pr<pr>-run<run>-attempt<attempt>`. Its normal
quality evaluation must still fail on a non-empty preparation diff: the writer
is a safe follow-up mechanism, never an admission path for evaluated bytes that
are not the PR head.
