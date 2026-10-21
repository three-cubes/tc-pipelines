# Surface assurance

Run `python assurance/run.py inventory`. It validates the exact public inventory. The hosted lane
(`assurance/hosted.py`) selects, plans and collects evidence for changed adapters. The lab has no production
credentials or remote mutation.

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
produces hermetic **consumer** evidence, not hermetic proof for all 63 adapters.
Admission must reject absent required adapter evidence.

## Hosted adapters and receipts

`surfaces.yaml` also classifies execution boundaries. The counts below are held to the inventory by a contract test.

| Boundary | Surfaces | Meaning |
|---|---|---|
| `safe-hosted` | 13 | Safe to exercise without production credentials. |
| `protected-live` | 26 | Needs a consumer-authorised non-mutating status receipt at release admission. |
| `structural-example` | 21 | Callable example wrappers: structural documentation. |
| `assurance-harness` | 3 | Internal reusable assurance executors. |
| Total | 63 | |

All remain in the exact structural inventory, so their call contracts cannot silently disappear. These
classifications describe the case boundary, not a claim that it has executed.

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

Admission accepts a run only if it is a direct `workflow_dispatch` of `hosted-assurance.yml` at the tested
commit. A run of another workflow that merely names `hosted-assurance.yml` in `referenced_workflows` is refused:
the entry appears whether or not the called job ran, and the run's artifacts carry no producer identity, so a
caller could upload imitation evidence beside a skipped call. A successful run of any other workflow, or of this
one at another commit, is refused. Calls are accepted again once the producing workflows attest their artifacts.

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
workflow path, actor ID, the approved producer commit (`producer_commit`: the producer repository's
commit, which is neither pipeline identity) and the artifact name and independently approved artifact
digest.
No endpoint or credential is inferred from these inputs.

The released `tc-fitness-runtime-contract verify-evidence` executable at immutable
v0.16.1 commit `8d39d7e2f5b5d9daae778ec8195e344b0e7cc396` validates the canonical
runtime receipt; the compatibility-engine lock remains unchanged. Producer
provenance must match the declared completed, successful `workflow_dispatch`
run/attempt, actor and approved producer commit; the pipeline candidate is bound by the
runtime receipt's expected source SHA, not by the producer run. The run's artifacts are read
across every page, keeping those created inside the approved attempt's job window (a re-run leaves earlier attempts' artifacts beside it). Its actual GitHub artifact must contain byte-identical
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

## Live scanner qualification

`live-scanner-qualification.yml` is the separate GitHub-hosted admission
boundary for the Task 3 Checkov and OSV Scanner cases. It checks out the exact
40-hex candidate, uses the one canonical `python-gate-body` scanner provisioner
to install the versions declared in
`actions/python-gate-body/scanner-versions.json`, then records compliant and
violation results for each. It retains an attempt-specific artifact named
`live-scanner-receipts-<run>-<attempt>`.

Each `tc.sdlc/live-scanner-qualification/v1` receipt binds the candidate commit,
fixture tree digest, executable digest, scanner version, and retained rule-data
identity. Checkov records the digest of its installed packaged policy tree. OSV
records the canonical digest of the scanner's actual remote response: OSV does
not publish an immutable database revision per request, so this is explicitly a
response identity rather than a claimed database-release version. The validator
rejects a missing receipt, stale attempt, wrong tool pin, fixture replacement,
or any tc-fitness `protocol-unit` ledger. A generic local adapter receipt cannot
be substituted for this schema.

`live_scanners.py admit` also takes `--validator`, the validator revision the release operator
approved. The workflow checks out its own
validator at `github.workflow_sha`, so admission refuses a run of the same file from any other revision.

The workflow is a GitHub-hosted admission boundary and is not included in normal
PR fan-in. The same repo-owned provision command also runs on macOS and Linux:

```sh
make prepare
make scanner-versions
```

`make prepare` provisions both scanners before evaluation and exports their
bin directory through `PATH` for all subsequent Make targets. By default Make
uses `${XDG_CACHE_HOME:-$HOME/.cache}/tc-pipelines/scanners/bin`; set
`TC_SCANNER_BIN_DIR` to an absolute `.../bin` directory to override it in a
sandbox. `make scanner-versions` resolves and runs the provisioned executables
in a later process. For direct scanner commands outside Make, add the same bin
directory to the interactive shell's `PATH`. Set `TC_SCANNER_PATH_FILE` when a
caller needs the provisioner to register that directory for later processes
(GitHub maps this to `GITHUB_PATH`). Local scanner tools live in the versioned
XDG cache, outside the checkout. OSV assets are checked
against the official release hashes pinned in
`scanner-versions.json`. Checkov uses its own
locked uv environment; the consumer `.venv` and lock are never modified, and
the tool lock enforces `asteval>=1.0.9,<1.1` without `ecdsa`.

The required local contract tests install both pinned binaries into the owned
versioned cache, execute each scanner against real compliant and violation
fixtures, and verify clean/finding reports. Those results prove local scanner
behavior only. The workflow remains the authority for a hosted execution
receipt; a local result cannot be relabelled or used as that receipt.

## Disposable consumers

The disposable-consumer lab (`consumers.yaml`, the python, mixed, generated and sdlc fixtures, and the
`run.py` lab, render and prepare commands) is not carried. It exercised the v3 bootstrap renderer and
`sdlc.yaml`. tc-sdlc v4 adopts a consumer with `nx g @three-cubes/tc-sdlc:init`, and its end-to-end
fixtures (`consumers.e2e.test.ts`) run those consumers; see the migration ledger entry
`consumer-lab-superseded`.
