# Surface and consumer assurance

Run `make assurance`. It validates the exact public inventory and executes the
Python, mixed Python/pnpm and freshly bootstrapped consumers. The command prints
the retained evidence directory. Tools required: Python 3.12+, uv, Git, Make,
Bash, Node and pnpm. Dependency installation can use the network; the lab has no
hosted execution, production credentials or remote mutation.

To test a candidate engine wheel:

```sh
make assurance ASSURANCE_ARGS='--fitness-wheel /absolute/candidate.whl --output /absolute/new-evidence-directory'
```

Without a candidate, consumers resolve the explicitly pinned compatibility
engine from their fixture declaration and install with `uv sync --locked`.
Each attempt retains the resolved `uv.lock`, installation/preparation/evaluation
logs, test results and coverage. Existing evidence directories are never reused.
The report declares `evidence_mode: compatibility-terminal`; it is **not** a
`tc.sdlc/assurance/v1` admission receipt or proof of GitHub adapter execution.

## Published inventory

`surfaces.yaml` covers every `workflow_call` workflow and every composite action
in both public action directories. Non-callable CI and example workflows are
outside this published surface. `python assurance/run.py discover` generates the
discovered IDs and paths; `python assurance/run.py inventory` compares both
directions, rejects duplicates and checks evidence declarations and references.

Every public adapter requires structural plus hermetic PR evidence, and
cumulative structural/hermetic/hosted release evidence. Deployment adapters use
the hosted non-mutating qualification boundary; this command performs no live
deployment. Empty evidence reference lists represent evidence still to be
implemented, never an exemption or a passing execution. Existing references
describe tests; their presence alone does not establish their execution level.
The inventory command produces structural inventory validation only. The lab
produces hermetic **consumer** evidence, not hermetic proof for all 54 adapters.
Admission must reject absent required adapter evidence.

## Hosted adapters and receipts

`surfaces.yaml` also classifies execution boundaries. Twelve adapters are safe
to exercise without production credentials: six reusable workflows and six
composites. Twenty-four protected adapters require a consumer-authorised
non-mutating status receipt at release admission. Eighteen callable example
wrappers are structural documentation; two reusable assurance executors are
internal harnesses. All remain in the exact structural inventory, so their
call contracts cannot silently disappear. These classifications describe the
case boundary, not a claim that it has executed.

PR and merge-group CI call `hosted-assurance.yml`, which selects from exact Git
base/head commits and invokes each changed safe adapter through real
`workflow_call`. Dependencies in the versioned inventory select affected
adapters too. The action cases use local candidate action paths inside the
reusable `hosted-actions.yml` executor. Existing immutable nested self-pins
remain subject to the repository's self-pin contract tests.

For local selection or release planning:

```sh
make assurance-hosted ASSURANCE_HOSTED_ARGS='select --base <40-hex> --head <40-hex>'
make assurance-hosted ASSURANCE_HOSTED_ARGS='plan --base <40-hex> --head <40-hex> --complete --output /absolute/new-directory'
```

The complete selector is also available through the hosted workflow's manual
dispatch. `selection.json` includes exact protected probe expectations for the
consumer's protected environment. Cloudflare uses its existing allowlisted
`status` request; Azure status references the existing `systemctl is-active`
boundary. Azure deployment preflight can freeze writers and acquire leases,
so this lane does not invoke it. Endpoints, units and credentials remain owned
by the consumer; the assurance planner does not invent them or call them.

`receipt.schema.json` defines `tc.sdlc/assurance/v1`. `receipt.py write` binds a
declared expectation and a real observation to retained output digests;
`receipt.py validate` checks those identities and outputs again. Every attempt
uses a new execution UUID and a new directory. Non-applicable package/image,
fitness-ledger and runtime fields are explicit nulls. Pipeline adapter cases
qualify the workflow commit, not a new fitness wheel or a not-yet-existing SDLC
package/image. Their task input digest binds the entire candidate Git tree and
resolved case contract. Negative receipts need the exact declared finding in
retained non-log evidence; a matching exit code is insufficient.

Hosted collection reads the real GitHub run-attempt jobs and complete job logs,
requires every named case job and assertion step, and rejects skipped, missing
or duplicate outcomes. Receipts, raw logs, terminal records, failure diagnostics
and the selection are uploaded in attempt-specific artifacts, with receipt
digests in the job summary. Composite consumer outputs and scanner/mutation
artifacts are retained by their actual producer workflows. Local receipts stay
labelled `local`; the writer refuses to label them GitHub evidence outside the
matching Actions run and attempt.

For PRs, `head` / `candidate.pipeline_commit` is the tested merge commit and
`candidate_head` / `candidate.pipeline_head_commit` is the branch head reported
by the Actions API. The selector verifies the merge parents; merge-group and
manual runs use the same commit for both identities. Admission compares the
selection against the actual run/attempt's uploaded plan, not an editable local
claim. Job logs use bounded raw HTTP downloads (16 MiB, 30-second socket timeout),
retaining original bytes and transport diagnostics alongside sanitised text.
Cross-host redirects drop authorisation headers.

Mutation assurance additionally downloads its attempt-specific native artifact,
checks the GitHub artifact digest, requires `mutation.json` with the real passing
original/killed-mutant result, and binds both ZIP and JSON digests in the receipt.
Admission downloads it again and compares bytes. A green non-blocking wrapper
with a missing or failed native result cannot certify the case.

`make assurance-hosted ASSURANCE_HOSTED_ARGS='admit --output /absolute/evidence-directory'`
consumes retained evidence without repeating evaluations. It reselects the
immutable candidate, recomputes receipt expectations and compares hosted
terminal records with GitHub again. Protected cases require external
`live-boundary` receipts with bound runtime receipts and the declared status
operation. Supply `admit --protected-policy /absolute/release-authority.json` for
protected admission. This is explicit trusted admission input, **not** a file
chosen by or copied from the runtime payload. It is keyed by protected case ID;
`selection.json` enumerates all required policy fields. The operator supplies the
canonical contract path, environment/target, expected image/host/user/deployment/
configuration/run/attempt/checks/freshness, plus authorised producer repository,
workflow path, actor ID, artifact name and independently approved artifact digest.
No endpoint or credential is inferred from these inputs.

The released `tc-fitness-runtime-contract verify-evidence` executable at immutable
v0.16.1 commit `8d39d7e2f5b5d9daae778ec8195e344b0e7cc396` validates the canonical
runtime receipt; the compatibility-engine lock remains unchanged. Producer
provenance must match the declared completed, successful `workflow_dispatch`
run/attempt and actor. Its actual GitHub artifact must contain byte-identical
`runtime-evidence.json`, `status.json` (canonical `{valid: true, findings: []}`),
and `execution.log`. Canonical deployment IDs retain their existing semantics;
they are not assumed to be GitHub deployment object IDs. Policy digest and both
candidate identities are recorded in admission output. Missing external proof
blocks admission while ordinary PR CI remains
limited to safe adapters and the existing hermetic gate. The resulting
`admission.json` records complete receipt digests for coordinated release
composition. Tag/publish composition is the subsequent coordinated-release
task; this change does not publish or deploy anything.

The exact `Quality gate` fan-in now includes hosted assurance;
`no-attribution` retains its protected name. The full self-gate runs on PR and
merge-group candidates, with no duplicate full `push: main` evaluation.

Local tests and lint validate the implementation, not GitHub execution. Actual
hosted resolution, permissions, image builds, downloads and artifact retention
remain unverified until the reviewed branch is pushed and these cases run.

## Disposable consumers

`consumers.yaml` is the command and expected-result manifest. It runs the real
bootstrap renderer, compares all 16 rendered files (content and executable
modes) with `fixtures/generated/rendered`, and only then executes that output.
The render context fixes the consumer identity and released pins; the current
checkout supplies the actual renderer and skeleton. The bootstrap command's
`--render-only` mode performs no credential/API lookup and deterministically
selects the skeleton's shipped empty secret configuration. No scanner result or
executable is replaced.

Consumers share the minimal Python product fixture. The mixed consumer adds an
actual pnpm workspace and Node-generated output. The generated consumer merges
its product declaration with the entire unmodified rendered fitness fragment,
including all five CORE rules and the secret scan. All consumers run the
rendered `make prepare`; mixed also runs its product generator. The
second preparation must change no source, lock or generated file. The candidate
wheel, when supplied, is installed through an explicit uv source override.

Affected and complete evaluation invoke the same declared `tc-fitness run`
entrypoint; affected evaluation adds `--changed-files-from`. The small fixture's
entire source set is affected. Each compliant/sabotage variant uses identical
commands and installed inputs. Sabotage changes arithmetic, corrupts the pnpm
generated value, or removes a required generated harness entrypoint.

The runner requires all declared terminal step and CORE results, rejects skips
and unrelated failures, and checks fresh non-empty JUnit/coverage and mixed
workspace TAP output. Every evaluation starts without the preceding evaluation's
output directory. Missing outputs and wrong sabotage diagnostics fail the lab.

Refresh the generated reference deliberately when changing the skeleton:

```sh
uv run python assurance/run.py render --output /absolute/new-render-directory
```

Review and replace the checked-in rendered files with that exact output; do not
hand-edit the rendered fixture. Preparation does not update the reference.
The existing compatibility commands will move to `bootstrap`, `prepare`,
`check` and `check-all` when tc-sdlc lands; this fixture suite remains the same.
