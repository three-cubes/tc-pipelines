# Supply-chain pinning

Every `uses:` resolves to a full commit SHA — including a reference to a file
sitting beside it in this repo. A pinned step runs whatever that commit held, not
what a reviewer reads locally, so the pin IS the contract about which revision
executes.

## Why the SHAs are repeated rather than named once

`uses:` accepts **no context of any kind**. Not `env`, not `inputs`, not `vars`,
in a reusable-workflow call or an action step:

```
uses: org/repo/.github/workflows/gate.yml@${{ inputs.pin }}
→ context "inputs" is not allowed here. no context is available here.
```

So a ref is a literal or it is nothing. There is no variable to extract, and the
repetition is the platform's floor rather than a design choice.

Nor is it one fact written many times. Each pin is an independent assertion that
*this* caller loads *that* revision of *that* target — this repo carries pins
across a dozen distinct targets, and they share a SHA only because they share a
release. The single authoritative representation is the release; each pin is a
local claim about it.

**What keeps them consistent is a checker, not a variable.**
`test_self_pin_freshness` resolves every self-pin from git history and compares
the complete executed target graph with the current graph. It normalises each
pin coordinate only for that file's content comparison, then follows the pinned
coordinate and checks the nested target recursively. It fails when a pin is not
an ancestor of HEAD or any target in its executed graph contains stale content.

The genuinely DRY alternative — a floating `@v1` — is what this exists to
prevent. One moving reference, no repetition, and it froze while a composite
beneath it changed: a destructive deploy advertised a rollback handle that was
the empty string on every run, because the workflow read an output the pinned
revision no longer emitted. `test_uses_ref_pinning` rejects floating refs.

## Self-pins execute reviewed current content

A commit cannot pin itself because writing the pin changes the hash. Commit the
target first, then update its callers to that immutable commit. An unchanged
target may retain an older immutable ancestor only when its complete recursive
target graph is content-equivalent to the current graph. A changed target uses
the reviewed commit that first contains that target and its current dependencies.

This removes the former two-tag bootstrap. The release commit contains callers
that already execute the reviewed target content, and consumers pin that single
release.

This topology requires merge commits. Configure each repository with
`allow_merge_commit=true`, `allow_squash_merge=false`, and
`allow_rebase_merge=false`; run `governance/scripts/check-repository-merge-settings.sh`
to verify those settings before releasing.

## Consumer repins

A consumer's pin is rarely one line. Beyond the `uses:` ref, count anything that
independently asserts the same revision: an admission check that greps the
materialized commit, a deploy adapter carrying its own copy, a test fixture
naming the expected value. Search unfiltered — `grep -rn <sha> .` with only
`.git` and vendor directories excluded — because a filtered search that misses a
site returns a confident wrong answer. Extensionless executables are the usual
casualty of an `--include=*.sh`.

Repeated values in a **trust root** are deliberate. A script that decides whether
the code it is about to execute is the reviewed code must not read its expected
values from a file an attacker could influence — that would make the file an
input to the check it is performing. Such a script hardcodes its `PATH`, its
binary paths, and its expected revisions for the same reason. Do not deduplicate
these into a shared source. The same holds for a test fixture: a test that
imported the expected value could not detect a wrong one.

Match on the SHA. A guard that also matches a human-readable version comment
couples two files on a string that carries no control, and fails confusingly when
only one is updated.

## Automated consumer repins

`dispatch-consumer-repins.yml` runs when a tc-pipelines release is published.
It checks out the release tag, resolves that tag to its commit SHA, and sends the
tag/SHA pair to each enrolled consumer as a `repository_dispatch` event using the
`three-cubes-agent` App.

Each consumer validates that the tag still resolves to the dispatched SHA through
the GitHub API. It then runs its repository-local pin updater, runs the updater
in check mode, creates one App-authored PR, and enables auto-merge. The consumer
PR remains subject to its existing required checks and CODEOWNERS review.

The dispatch carries the tag and its resolved commit as an immutable release
coordinate. Consumers keep full-SHA pins, required checks, CODEOWNERS review,
and deployment controls.
