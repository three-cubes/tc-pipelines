# Local surface and consumer assurance

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
rendered compatibility `make fix`; mixed also runs its product generator. The
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
