---
type: standard
status: proposed
owner: platform
date: 2026-09-19
related:
  - governance/standards/ai-sdlc-product-architecture.md
  - governance/standards/improving-fitness-gates.md
  - governance/standards/testing-strategy.md
  - governance/standards/ci-release-deployment-architecture.md
---

# CORE SDLC assurance contract

## Outcome

`tc-fitness` proves that every fitness check detects the defect it claims to
detect. `tc-pipelines` proves that every published workflow and action preserves
the declared result when executed through its real adapter boundary. A
coordinated release proves that the candidate engine and candidate pipeline work
together against representative consumers.

The assurance path provides fast local feedback and release-grade evidence
without treating source shape, a mock, process launch or a zero exit code as
proof of behaviour.

## Current gap

At the reviewed revisions:

- `tc-fitness` has 53 registered CORE checks and a matching test module for each
  check, but its own gate does not bind those checks against the repository;
- `tc-fitness` reports coverage without an enforced line or branch floor, has no
  mutation execution, has no installed-wheel test and runs CI only on Ubuntu
  with Python 3.12;
- `tc-pipelines` has 47 workflows and 16 actions, but its required self-CI runs
  structural and hermetic contract tests rather than the reusable workflows
  against a real consumer;
- example workflow callers default to `run-for-real: false`;
- the local fitness-engine canary test substitutes a gate command, and the real
  consumer canary is not part of `tc-fitness` release admission; and
- neither repository emits one release-admission record binding engine,
  pipeline, consumer, commands, findings and produced evidence.

These tests remain useful. The change adds the missing behavioural layers and
stops higher-level claims from being inferred from lower-level evidence.

## Scope

This design changes two canonical repositories:

| Repository | Owns in this design |
|---|---|
| `tc-fitness` | Check contracts, check execution semantics, structured findings, self-application, coverage, changed-code mutation and installed-package proof. |
| `tc-pipelines` | Published-surface inventory, fixture consumers, hosted adapter execution, assurance receipt, candidate composition and release admission. |

Consumer repositories retain product tests, product journeys, runtime values and
PVT. The existing `tc-fitness/runtime-evidence/v1` contract remains the runtime
and PVT evidence format. The new assurance record references that receipt when a
case crosses a runtime boundary; it does not replace or copy it.

This tranche does not create a separate assurance repository, redesign the
production deployment transaction or add another fitness engine.

## Assurance principles

1. **Public surface first.** A check is exercised through `tc-fitness run`. A
   reusable workflow is exercised through `workflow_call` on GitHub when GitHub
   semantics form part of the contract.
2. **Positive and negative controls share the path.** The compliant and
   sabotaged variants use the same candidate code, entrypoint and environment.
3. **Failure is specific.** A negative control names the expected non-zero
   result and finding, denial or missing evidence. Any unrelated failure is a
   failed assurance case.
4. **No grandfathering.** Required contract cases, tier declarations, coverage
   and changed-code mutation have no suppressible baseline. The implementation
   becomes release-admissible only after the current surface meets the rule.
5. **Fakes retain their correct label.** A fake external executable is valid
   protocol-unit evidence. It is not integration, E2E, hosted-adapter or live
   evidence.
6. **Complete terminal evidence.** A launched command, partial log or zero exit
   without its declared output cannot pass.
7. **One definition, several executors.** Local and hosted execution invoke the
   same assurance commands and manifests. GitHub-only semantics and live
   credentials are the only hosted-only work.
8. **Cost follows risk.** Affected cases run locally and on PRs. Complete
   composition runs for release admission. Broad mutation and platform
   compatibility run on schedule and before a release that changes their
   surface.

## tc-fitness check contract

### Contract fixtures

Every ID in `tc_fitness.core_checks.CORE_CHECKS` has one directory under:

```text
tests/check_contracts/<check-name>/
  contract.yaml
  compliant/
  violation/
  unavailable/        # required only when the check invokes an external dependency
```

`contract.yaml` uses `tc.fitness/check-contract/v1`:

```yaml
schema: tc.fitness/check-contract/v1
check: core:example_check
config:
  roots: [src]
cases:
  - id: compliant
    fixture: compliant
    expected:
      status: pass
      exit: zero
      findings: []
  - id: violation
    fixture: violation
    expected:
      status: fail
      exit: nonzero
      findings:
        - rule: example-check
          path: src/broken.py
          message_contains: required behaviour is missing
dependencies: []
```

Checks that invoke Checkov, OSV Scanner, Git or another process declare the
dependency and an `unavailable` case. Once a consumer configures such a check,
an unavailable required dependency is `ERROR`, never `PASS`. A check without an
external dependency declares `dependencies: []` and carries no unavailable
fixture. Every case declares `expected.exit` as `zero` or `nonzero`; an
unavailable-dependency case declares `status: error` and `exit: nonzero`.

The contract runner:

1. copies the fixture to a temporary repository;
2. renders only the minimum consumer configuration and catalogue entry;
3. invokes the current candidate through the public `tc-fitness run` entrypoint;
4. parses the structured ledger rather than matching console decoration;
5. compares process-exit classification, status, rule, path and stable message
   fragment with the manifest;
6. verifies the ledger and any declared output exist and bind the executed case;
7. returns non-zero for missing, skipped, stale or unexpected results.

The registry metatest compares `CORE_CHECKS` with the contract directories in
both directions and requires each directory's `contract.yaml` check ID to equal
`core:<directory-name>` and the corresponding registry ID. A new check without
its contract cases, an orphan contract without a check, and a copied manifest
that exercises a different check all fail.

### Test tiers

Each tc-fitness test module declares one primary pytest tier at module level:

| Tier | Meaning |
|---|---|
| `unit` | In-process transformation or predicate with no process boundary. |
| `contract` | Public input/output or protocol contract using controlled local collaborators. |
| `integration` | Real package, filesystem, Git or child-process composition. |
| `e2e` | Installed distribution invoked through its supported user entrypoint. No internal test doubles. |

Parametrised fixture text containing marker names does not classify the test
that contains it. The repository enables its own
`core:every_test_has_tier_marker` check with no baseline.

### Self-application

The tc-fitness self catalogue enables, at minimum:

- `every_test_has_tier_marker`;
- `deterministic_tests`;
- `coverage_includes_branches`;
- `coverage_floor`;
- `new_code_coverage`;
- `behavioural_evidence` for package and CLI surfaces;
- `no_test_doubles_in_runtime_tiers`;
- `osv_scanner_sca`; and
- the existing identity, attribution and branch checks.

The self catalogue runs through the same `tc-fitness run` command used by CI.
It is not duplicated into workflow YAML.

### Coverage and mutation

The engine enforces both absolute floors and a monotonic ratchet:

- at least 95 percent line coverage over `src/tc_fitness`;
- at least 95 percent branch coverage over `src/tc_fitness`;
- 100 percent changed-line coverage; and
- 100 percent branch coverage over the admission predicates in `gate.py`,
  `runner.py`, `gate_config.py` and `runtime_contract.py`.

The latest accepted measurement for the exact base commit is retained as signed
or digest-bound evidence. A candidate must meet the absolute requirements and
must not reduce line or branch coverage from that accepted measurement. The
measurement is not an exemption list: it cannot suppress files, checks or
findings, and a stale or identity-mismatched measurement fails the gate.

Changed production decision logic runs a bounded, PR-blocking mutation task.
The task scopes
mutants to changed functions and their dependency closure, uses the declared
contract/unit tests and fails for every surviving non-equivalent mutant. The
implementation carries no acknowledgement or survivor baseline. Broad package
mutation runs on schedule and retains its report; a release that changes the
mutation runner or test-selection logic must pass the broad task before
admission.

### Distribution and platform proof

Release admission builds the wheel and source distribution once. One clean
environment installs the wheel directly. A second clean environment builds a
wheel from the source distribution with isolated build dependencies, installs
that derived wheel and executes the same proof. Both paths execute:

```text
tc-fitness --help
tc-fitness run <minimal passing fixture>
tc-fitness-runtime-contract --help
tc-fitness-runtime-contract verify <valid fixture>
```

The full Linux suite runs on Python 3.12 and 3.13. A small macOS lane installs
the same wheel and executes the CLI and Git/filesystem integration cases. Any
unsupported operating system is stated explicitly in package and contributor
documentation rather than implied by an untested classifier.

## tc-pipelines published-surface contract

### Surface inventory

`assurance/surfaces.yaml` is the canonical inventory of every public reusable
workflow and composite action. A generator discovers the files and a validator
requires exact bidirectional coverage.

Each entry declares:

```yaml
schema: tc.sdlc/surface-assurance/v1
id: workflow.python-quality-gate
path: .github/workflows/python-quality-gate.yml
risk: control-plane
evidence:
  structural:
    - governance/scripts/tests/test_internal_call_contracts.py
  hermetic:
    - assurance/cases/python-quality-gate/local.yaml
  hosted:
    - assurance/cases/python-quality-gate/hosted.yaml
sabotage:
  - wrong-fitness-identity
  - missing-required-output
```

Evidence levels are cumulative:

| Level | Proves |
|---|---|
| `structural` | Syntax, pins, declared inputs, output names and call shape. |
| `hermetic` | Portable implementation logic produces the expected observable result with controlled local collaborators. |
| `hosted` | GitHub resolves and executes the reusable adapter with real Actions contexts, permissions, matrix and artifact semantics. |
| `live` | A non-mutating or isolated real external boundary returns the required receipt. |

A control-plane workflow or action cannot stop at structural evidence. The
required level follows the boundary it controls. Deployment surfaces require
structural and hermetic evidence on each PR and a hosted non-mutating admission
probe before release. A live mutation belongs only in the separately protected
deployment qualification path.

### Disposable consumer lab

`assurance/fixtures/` contains three small consumers:

1. `python` — Python package, tc-fitness configuration and coverage;
2. `mixed` — Python plus pnpm workspace and generated output; and
3. `generated` — the exact output of the current repository bootstrap skeleton.

The lab creates an empty checkout, installs the candidate SDLC/fitness inputs,
renders the generated consumer from the current bootstrap skeleton, and fails
if that fresh render differs from the checked-in fixture. It then runs
preparation to a fixed point followed by affected and complete evaluation. The
second preparation run must produce no diff. Each fixture has a compliant
variant and a sabotage variant that must fail for its declared reason.

Until the `tc-sdlc` package and canonical image exist, the lab exercises the
current compatibility commands and records that mode. The same fixtures move to
`bootstrap`, `prepare`, `check` and `check-all` when those interfaces land; no
parallel fixture suite is created.

### Hosted adapter execution

Safe reusable workflows run for real in tc-pipelines PR CI when their surface or
dependency changes. The hosted cases use fixture repositories or checked-in
fixture content, no production environment and no production credential.

Examples with `run-for-real: false` remain syntax examples and are labelled
`structural`. They cannot satisfy hosted evidence.

Azure, Cloudflare and deployment actions retain their fast fake-process
contracts. Candidate release admission additionally runs the real non-mutating
status/preflight operation through the approved boundary and validates its
receipt. Apply, cutover and rollback remain part of protected deployment
qualification, not ordinary PR CI.

## Candidate composition

The composition matrix binds exact immutable inputs:

- candidate tc-fitness wheel digest;
- candidate tc-pipelines commit and, once available, package/image digest;
- fixture or consumer commit;
- generated SDLC lock digest;
- invoked task identities; and
- expected compliant or sabotaged outcome.

Every candidate engine release runs the fixture matrix and at least one current
protected consumer gate. Engine-semantics changes run both `tc-agent-zone` and
`kairix` consumer gates. Documentation-only changes do not.

Every candidate pipeline release runs the disposable consumer lab. Changes to a
reusable adapter also run that adapter's hosted case. A coordinated SDLC release
runs the complete fixture matrix with one wrong-engine, wrong-pipeline or
missing-output sabotage case.

The candidate release cannot tag or publish until the required composition
cases pass. The existing compatibility canary remains until this admission path
has replaced its behaviour and passed both protected consumers.

## Assurance receipt

`tc-pipelines` owns the JSON Schema for `tc.sdlc/assurance/v1`.

Required fields are:

```json
{
  "schema": "tc.sdlc/assurance/v1",
  "subject": "engine|pipeline-adapter|consumer-composition",
  "case_id": "stable-case-id",
  "expected": "pass|fail|deny|error",
  "actual": "pass|fail|deny|error",
  "candidate": {
    "fitness_digest": "sha256:...",
    "pipeline_commit": "<40-hex>",
    "pipeline_package_digest": "sha256:...",
    "pipeline_image_digest": "sha256:..."
  },
  "consumer": {
    "repository": "owner/name",
    "commit": "<40-hex>",
    "sdlc_lock_digest": "sha256:..."
  },
  "execution": {
    "execution_id": "uuid",
    "workflow_run_id": "github-run-id-or-null",
    "attempt": 1,
    "command": ["make", "check-all"],
    "tasks": [
      {"id": "check-all", "input_digest": "sha256:..."}
    ],
    "executor": "local|github-actions|live-boundary",
    "started_at": "RFC3339",
    "finished_at": "RFC3339",
    "exit_code": 0
  },
  "evidence": {
    "fitness_ledger_digest": "sha256:...",
    "outputs": [
      {
        "id": "fitness-ledger",
        "path": "artifacts/fitness-ledger.json",
        "digest": "sha256:..."
      }
    ],
    "runtime_receipt_digest": "sha256:..."
  }
}
```

Fields that do not apply use JSON `null`; they are not omitted. `execution_id`
and `attempt` always apply; `workflow_run_id` is null outside GitHub Actions.
Every resolved task carries its stable task ID and the digest of its declared
inputs. Every retained output carries its stable output ID, repository-relative
or artifact-relative path and digest. The validator
fails a missing, skipped, stale, identity-mismatched, exit-code-only or
output-free receipt. A negative control passes only when `expected` and `actual`
match and the expected finding or denial evidence is present.

Receipts are retained as workflow artifacts and indexed in the job summary.
Release metadata records the complete receipt digest, not a mutable URL alone.

## Execution lanes

| Lane | Trigger | Work | Budget and authority |
|---|---|---|---|
| Local affected | Developer command | Changed contract cases, changed surface cases, self gate | Warm target under 60 seconds. |
| Local pre-push mutation | Developer command for changed decision logic | Bounded changed-function mutation | Target 2–3 minutes; required before push when applicable. |
| PR affected | Pull request | Same affected command in canonical Linux environment, bounded changed-code mutation and changed hosted adapters | Merge-blocking; mutation may run in parallel. |
| Release admission | Candidate preparation | Full contracts, distributions, fixture composition, required hosted/live probes and the exact accepted mutation receipt for changed decision logic | Tag/publish-blocking; rerun mutation when the receipt does not bind the exact candidate. |
| Scheduled broad | Nightly or weekly | Broad mutation, platform compatibility, all hosted adapters and external tools | Retained and actionable; a failing affected surface blocks its next release. |
| Post-merge | Successful admitted merge | Publish/promote existing exact-commit evidence | No duplicate full evaluation. |

Local and hosted jobs invoke the same manifest-driven commands. Workflow YAML
selects runner, credentials and retention only.

## Failure handling

Each failed case records:

- stage and case ID;
- expected and actual outcome;
- exact candidate and consumer identities;
- complete terminal status;
- bounded sanitised diagnostics;
- ledger and output locations; and
- whether no external mutation occurred.

An unavailable dependency is an error, not a skip, when its case is required.
An unrelated setup failure does not satisfy a sabotage expectation. Retrying a
case increments `attempt`, assigns a new `execution_id`, retains the workflow
run identity when GitHub performs an in-run retry and does not overwrite the
failed receipt.

## Implementation sequence

### Tranche 1 — tc-fitness self-proof

- add check-contract schema, fixtures, public runner and registry completeness;
- classify all existing tests by tier;
- bind the self-applicable CORE checks;
- enforce branch and changed-code coverage; and
- add installed-wheel Linux and macOS proof.

### Tranche 2 — tc-fitness sensitivity

- add bounded changed-code mutation with no survivor baseline;
- add real pinned OSV and Checkov integration cases; and
- require fixture and protected-consumer qualification before tag admission.

### Tranche 3 — tc-pipelines surface proof

- add surface inventory, discovery and evidence-level validator;
- add disposable Python, mixed and generated consumers;
- add compliant and sabotage execution through one local command; and
- add coverage for Python orchestration and decision helpers.

### Tranche 4 — hosted and composition proof

- execute changed safe adapters on GitHub runners;
- add non-mutating external-boundary admission probes;
- emit and validate `tc.sdlc/assurance/v1` receipts; and
- block pipeline and coordinated releases on the composition matrix.

Two coherent feature PRs carry the implementation: one in `tc-fitness` and one
in `tc-pipelines`. The branches may develop in parallel, but tc-fitness releases
first and tc-pipelines binds the reviewed engine release before its final gate.

## Acceptance criteria

The assurance tranche is complete when:

1. every registered CORE check has compliant and violation contracts and every
   dependency-backed check has an unavailable-dependency contract;
2. every contract runs through the candidate public engine and validates the
   structured ledger;
3. tc-fitness self-applies its relevant CORE rules with no baseline or
   suppression;
4. tc-fitness meets the absolute line, branch, changed-code and critical-path
   coverage requirements without regressing from the exact base commit's
   accepted measurement;
5. changed decision logic has no surviving mutation;
6. the built tc-fitness wheel passes clean Linux 3.12/3.13 and macOS CLI proof;
7. every published tc-pipelines surface is present in the assurance inventory;
8. every control-plane surface has executable evidence at its required level;
9. the generated consumer reaches a clean preparation fixed point and passes
   affected and complete evaluation;
10. candidate engine and pipeline revisions pass compliant fixtures and fail
    sabotage fixtures for the expected reason;
11. candidate releases are blocked when required assurance is missing or red;
12. retained receipts bind exact candidate artifacts, attempt and workflow
    identities, resolved task input hashes, terminal outcomes and named
    produced evidence; and
13. local and PR execution use the same commands, with no duplicated full
    post-merge test run.

## Rollback

The current compatibility gates and canary remain in place until the new path
passes the complete acceptance set. If the assurance runner itself is defective,
revert its feature merge and continue using the previous released engine and
pipeline pins. Do not bypass a red assurance result or publish an unqualified
candidate.
