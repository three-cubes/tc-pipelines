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
`test_self_pin_freshness` parametrises over every self-pin and fails any that
does not name the newest release, so the set cannot drift apart silently. Treat
that test as the deduplication mechanism.

The genuinely DRY alternative — a floating `@v1` — is what this exists to
prevent. One moving reference, no repetition, and it froze while a composite
beneath it changed: a destructive deploy advertised a rollback handle that was
the empty string on every run, because the workflow read an output the pinned
revision no longer emitted. `test_uses_ref_pinning` rejects floating refs.

## Self-pins lag by exactly one release

A commit cannot pin itself — writing the pin changes the hash. So the rule
targets the newest release **before** HEAD, and a change to a composite reaches
a consumer only at the release **after** the one carrying it.

Cutting a release is therefore two tags:

1. Tag `vX.Y.Z` from `main`.
2. **Bump every self-pin to `vX.Y.Z` and merge that immediately.**
3. Tag `vX.Y.Z+1`. This is the release consumers should take — the first whose
   workflows load composites containing the change.

Tell consumers which tag carries a composite-level fix. A release note that
describes a change in `actions/**` without saying which tag executes it will be
read as shipped when it is not.

### Bump the pins in the same window as the tag

`test_self_pin_freshness` skips a tag at HEAD, because no commit could satisfy a
rule that targets itself. So immediately after a tag, `main` stands on it and
stale pins still read as current — the suite is green and nothing is wrong yet.

The next commit to land, from anyone, makes that tag the newest release before
HEAD and turns **every** self-pin assertion red, with a message telling that
author to repin someone else's pins. Closing the window is the tagger's job.

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
