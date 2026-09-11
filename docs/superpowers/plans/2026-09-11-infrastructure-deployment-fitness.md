# Infrastructure and Deployment Fitness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Catch runtime path, permission, deployment-transaction and evidence defects locally, then prove the same contract against the deployed target.

**Architecture:** `tc-fitness` owns four opt-in validators over one versioned runtime-contract protocol and canonicalises selected YAML or JSON targets for hashing. `tc-pipelines` validates and transports that contract through its existing Azure VM deployment reusable and returns a digest-bound receipt. `tc-agent-zone` authors one `deployment-targets.yaml`, binds the checks directly to it, and retains its product PVT as the final acceptance layer.

**Tech Stack:** Python 3.12+, canonical JSON, optional PyYAML for strict YAML input, GitHub Actions reusable workflows, Azure WIF and Run Command, Docker/Linux filesystem integration tests.

**Spec:** `governance/standards/infrastructure-deployment-fitness.md`

## Global Constraints

- Canonical standards live in `tc-pipelines`; executable CORE checks live in `tc-fitness`; product values and PVTs live in the consumer.
- Every CORE check is repository-agnostic, opt-in and a vacuous pass when its configuration block is absent.
- A configured contract, evidence or required field fails when missing, malformed, stale or contradictory.
- Contract and evidence schema identifiers are `tc-fitness/runtime-contract/v1` and `tc-fitness/runtime-evidence/v1`.
- Selected contract and receipt bytes use UTF-8 canonical JSON with sorted keys and compact separators.
- Contract and artifact identities use `sha256:` followed by 64 lowercase hexadecimal characters.
- Baselines cannot suppress runtime-contract or evidence violations.
- The consumer supplies expected commit, image, host and runtime-user values independently of the receipt.
- The Hermes recovery retention value is `172800` seconds.
- Product probes execute as the declared runtime user with the declared runtime configuration and path namespace.
- Successful rollback records recovery while preserving the failed candidate verdict.
- Tests use public entrypoints, real temporary files and real subprocess/container boundaries; internal monkeypatching and test-only production parameters remain prohibited.
- Local fast checks remain below 60 seconds; live VM qualification runs in the deployment tier.
- Shared repository changes use the canonical `three-cubes-agent` GitHub App and immutable release tags.

---

## Delivery graph and ownership

| Task | Repository | Owner | Depends on | Merge result |
|---|---|---|---|---|
| 1 | `tc-pipelines` | standards owner | none | Canonical standard and implementation plan |
| 1A | `tc-pipelines` | local-CI parity implementer | Task 1 | One executable self-gate used locally and in CI |
| 2 | `tc-fitness` | contract-foundation implementer | Task 1 | Strict loader, data model and evidence check |
| 3 | `tc-fitness` | filesystem-contract implementer | Task 2 | Filesystem validator |
| 4 | `tc-fitness` | access-contract implementer | Task 2 | Access validator |
| 5 | `tc-fitness` | transaction-contract implementer | Task 2 | Transaction validator and integrated dispatch |
| 6 | `tc-agent-zone` + `tc-fitness` | release integrator | Tasks 2–5 | Candidate qualification and immutable engine tag |
| 7 | `tc-pipelines` | pipeline-contract implementer | Tasks 1A and 5 | Deployment-contract action and receipt validation |
| 8 | `tc-pipelines` | pipeline integrator | Task 7 | Azure reusable integration and immutable pipeline tag |
| 9 | `tc-agent-zone` | consumer-contract implementer | Tasks 6 and 8 | Canonical target registry and bindings |
| 10 | `tc-agent-zone` | runtime-evidence implementer | Task 9 | Linux/container collectors and sabotage journeys |
| 11 | `tc-agent-zone` | release owner | Task 10 | Exact-candidate production receipt and PVT |
| 12 | all three | migration owner | Task 11 | Proven duplicate checks retired and documentation current |

Agents may research Tasks 2, 7 and 9 in parallel. Task 1A can run beside Task 2 because it changes
the tc-pipelines self-gate while Task 2 changes the tc-fitness protocol. Implementation follows the
remaining dependency order so shared interfaces land before consumers. Each task receives a fresh
implementation agent and a separate task reviewer. The primary agent owns cross-repository
sequencing, releases, PR conversations, production deployment and final evidence.

### Task 1: Publish the canonical standard and executable plan

**Files:**
- Create: `tc-pipelines/governance/standards/infrastructure-deployment-fitness.md`
- Create: `tc-pipelines/docs/superpowers/plans/2026-09-11-infrastructure-deployment-fitness.md`
- Modify: `tc-pipelines/governance/STANDARDS.md`
- Modify: `tc-pipelines/governance/standards/deployment-verification.md`

**Interfaces:**
- Consumes: existing deployment verification, environment registry and fitness-gate release standards.
- Produces: the contract ownership, schema identifiers, four check names, receipt semantics and ordered delivery graph used by every later task.

- [ ] **Step 1: Add the standard and index entry**

Write the approved design into the files above and add this index row:

```markdown
| Deploy & ops | [`infrastructure-deployment-fitness.md`](standards/infrastructure-deployment-fitness.md) | Structured runtime filesystem, access, transaction and evidence contracts. |
```

- [ ] **Step 2: Align recovery retention wording**

Set the paved Azure VM default to 48 hours in `deployment-verification.md`, matching the implemented snapshot action and `snapshot-before-apply.md`.

- [ ] **Step 3: Run documentation and repository checks**

Run:

```bash
uv run pytest -q
git diff --check
```

Expected: all commands exit 0 and the full pytest suite reports at least 1,355 passing tests. The
repository's documented `uv run tc-fitness run` command currently exits 2 because `pyproject.toml`
has no `[tool.tc_fitness]` table. Task 1A removes that local/CI parity defect in a separate executable
change.

- [ ] **Step 4: Commit the standard**

```bash
git add governance/STANDARDS.md governance/standards/deployment-verification.md \
  governance/standards/infrastructure-deployment-fitness.md \
  docs/superpowers/plans/2026-09-11-infrastructure-deployment-fitness.md
git commit -m "docs: define infrastructure deployment fitness"
```

### Task 1A: Restore tc-pipelines local and CI gate parity

**Files:**
- Create: `tc-pipelines/Makefile`
- Modify: `tc-pipelines/pyproject.toml`
- Modify: `tc-pipelines/.github/workflows/ci.yml`
- Modify: `tc-pipelines/README.md`
- Create: `tc-pipelines/governance/scripts/tests/test_self_gate_parity.py`

**Interfaces:**
- Consumes: the repository's existing pytest contract suite and pinned `three-cubes-fitness` engine.
- Produces: one configured `tc-fitness` gate, invoked through the literal `make check` command both
  locally and by the CI contract-test job.

- [ ] **Step 1: Write a failing parity contract**

Assert that `pyproject.toml` contains a `contract-tests` fitness step whose argv is exactly
`pytest -q`, the Makefile `check` target invokes `uv run tc-fitness run`, and the CI contract-test
job invokes `make check` rather than a second pytest command.

- [ ] **Step 2: Prove the existing drift**

```bash
uv run pytest -q governance/scripts/tests/test_self_gate_parity.py
uv run tc-fitness run
```

Expected: the parity test fails because the three call sites disagree, and `tc-fitness` exits 2
because its root configuration is absent.

- [ ] **Step 3: Configure the single self-gate**

Add this root configuration, using the current qualified immutable tc-fitness tag:

```toml
[tool.tc_fitness]
name = "tc-pipelines self gate"

[[tool.tc_fitness.steps]]
id = "contract-tests"
summary = "workflow and action contract tests"
run = ["pytest", "-q"]
```

Add a Makefile whose `check` target runs `uv sync --locked` followed by
`uv run --no-sync tc-fitness run`. Change the CI contract-test step to `make check`; keep the
workflow-specific meta gate as its separate actionlint, yamllint, licence and branch-policy lane.
Update the lockfile if the engine pin changes.

- [ ] **Step 4: Verify success and sabotage resistance**

```bash
make check
uv run pytest -q governance/scripts/tests/test_self_gate_parity.py
git diff --check
```

Expected: all commands exit 0. Then temporarily change the configured pytest argv and the CI
command independently; each mutation must make `test_self_gate_parity.py` fail. Restore both and
re-run the commands green.

- [ ] **Step 5: Commit**

```bash
git add Makefile pyproject.toml uv.lock .github/workflows/ci.yml README.md \
  governance/scripts/tests/test_self_gate_parity.py
git commit -m "ci: unify tc-pipelines local and CI checks"
```

### Task 2: Build the strict contract foundation and evidence check

**Files:**
- Create: `tc-fitness/src/tc_fitness/core_checks/_runtime_contracts.py`
- Create: `tc-fitness/src/tc_fitness/core_checks/runtime_evidence_contract.py`
- Create: `tc-fitness/src/tc_fitness/runtime_contract.py`
- Create: `tc-fitness/tests/test_runtime_contracts.py`
- Create: `tc-fitness/tests/test_core_runtime_evidence_contract.py`
- Create: `tc-fitness/tests/test_runtime_contract_cli.py`
- Modify: `tc-fitness/src/tc_fitness/core_checks/__init__.py`
- Modify: `tc-fitness/pyproject.toml`

**Interfaces:**
- Consumes: `FitnessRule`, `run_core_check`, `[tool.tc_fitness.core_checks.*]` configuration.
- Produces: `RuntimeContractRule`, `ContractFinding`, `ContractDocuments`, strict JSON loading, canonical hashing, `RuntimeEvidenceContract`, `validate_runtime_evidence()` and the `tc-fitness-runtime-contract` executable for Tasks 3–10.

- [ ] **Step 1: Write strict-loader failures**

Add public-behaviour tests covering duplicate keys, NaN, wrong schema, booleans used as integer IDs, unsafe artifact references, configured missing files and empty configuration. The core assertion shape is:

```python
rule = build({"contract_file": "contract.json", "evidence_file": "evidence.json"}, repo_root=tmp_path)
assert rule.run() == 1
assert "fix:" in capsys.readouterr().err
```

- [ ] **Step 2: Prove the failures**

```bash
uv run pytest -q tests/test_runtime_contracts.py tests/test_core_runtime_evidence_contract.py
```

Expected: tests fail because the helper and evidence module are absent.

- [ ] **Step 3: Implement the shared protocol types**

Implement these immutable types and public functions:

```python
@dataclass(frozen=True)
class ContractFinding:
    source: Path
    pointer: str
    code: str
    message: str
    fix: str

@dataclass(frozen=True)
class ContractDocuments:
    contract_path: Path
    contract: Mapping[str, object]
    contract_bytes: bytes
    evidence_path: Path | None
    evidence: Mapping[str, object] | None
    evidence_bytes: bytes | None

def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
```

Reject duplicate keys through `json.loads(..., object_pairs_hook=...)`. Resolve configured files beneath `repo_root`, read exact bytes, validate document shape, and render sorted actionable findings.

- [ ] **Step 4: Implement evidence validation**

Expose:

```python
def validate_runtime_evidence(
    documents: ContractDocuments,
    *,
    expected_identity: Mapping[str, object],
    required_checks: tuple[str, ...],
    now: datetime,
    max_age_seconds: int,
) -> tuple[ContractFinding, ...]:
    ...
```

Validate exact contract digest, source SHA, image digest, host ID, runtime user, freshness, required non-skipped checks and referenced artifact bytes. Treat an exit-code-only observation as incomplete evidence.

- [ ] **Step 5: Prove hard adoption**

Create a baseline naming the bad evidence path and assert the configured rule still returns 1. Assert empty configuration returns 0 without opening files.

- [ ] **Step 6: Add the shared command-line boundary**

Expose `tc-fitness-runtime-contract` from `pyproject.toml`. Implement `resolve`, `digest` and `verify-evidence` subcommands in `tc_fitness.runtime_contract`. Each command accepts a registry path, environment, target and independent expected identity values as argv, writes a canonical secret-safe result to `--output`, and returns 1 for findings. Support strict JSON without optional dependencies and strict YAML through the existing optional PyYAML extra; a configured YAML contract with PyYAML absent returns an actionable failure.

- [ ] **Step 7: Register and verify**

Add `core:runtime_evidence_contract` to sorted `CORE_CHECKS`, add both new files to the formatter surface, then run:

```bash
uv run pytest -q tests/test_runtime_contracts.py tests/test_core_runtime_evidence_contract.py \
  tests/test_runtime_contract_cli.py tests/test_core_registry_consistency.py
uv run ruff check src/tc_fitness/core_checks tests/test_runtime_contracts.py tests/test_core_runtime_evidence_contract.py
uv run mypy src/tc_fitness
```

Expected: all commands exit 0.

- [ ] **Step 8: Commit**

```bash
git add src/tc_fitness/core_checks tests pyproject.toml
git commit -m "feat: validate runtime deployment evidence"
```

### Task 3: Add the runtime filesystem contract

**Files:**
- Create: `tc-fitness/src/tc_fitness/core_checks/runtime_filesystem_contract.py`
- Create: `tc-fitness/tests/test_core_runtime_filesystem_contract.py`
- Modify: `tc-fitness/src/tc_fitness/core_checks/__init__.py`
- Modify: `tc-fitness/pyproject.toml`

**Interfaces:**
- Consumes: `ContractDocuments` and path-component helpers from `_runtime_contracts.py`.
- Produces: `RuntimeFilesystemContract` and `validate_filesystem_contract(documents) -> tuple[ContractFinding, ...]`.

- [ ] **Step 1: Write filesystem sabotage cases**

Create one valid host-to-container-to-profile contract and mutations for undefined roots, wrong namespace, sibling-prefix false matches, nested physical overlap, alias disagreement, symlink cycle, symlink escape and missing target observation.

The regression fixture must include:

```json
{
  "cluster": "/hermes-home/profiles/",
  "profile": "/hermes-home/profiles/consultant-delivery-consultant/USER.md"
}
```

and assert the physical prefix overlap is reported even though the logical namespace kinds differ.

- [ ] **Step 2: Prove the failures**

```bash
uv run pytest -q tests/test_core_runtime_filesystem_contract.py
```

Expected: failures identify the absent validator.

- [ ] **Step 3: Implement component-aware resolution**

Resolve POSIX paths as tuples of components. Treat wildcard identity segments explicitly, distinguish files from directories, and require a named reason for each allowed nested root pair. Resolve symlinks inside their declared namespace and detect repeated nodes.

- [ ] **Step 4: Register and verify**

```bash
uv run pytest -q tests/test_core_runtime_filesystem_contract.py tests/test_runtime_contracts.py tests/test_core_registry_consistency.py
uv run ruff check src/tc_fitness/core_checks/runtime_filesystem_contract.py tests/test_core_runtime_filesystem_contract.py
uv run mypy src/tc_fitness
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/tc_fitness/core_checks/runtime_filesystem_contract.py \
  src/tc_fitness/core_checks/__init__.py tests/test_core_runtime_filesystem_contract.py pyproject.toml
git commit -m "feat: validate runtime filesystem contracts"
```

### Task 4: Add the runtime access matrix

**Files:**
- Create: `tc-fitness/src/tc_fitness/core_checks/runtime_access_matrix.py`
- Create: `tc-fitness/tests/test_core_runtime_access_matrix.py`
- Modify: `tc-fitness/src/tc_fitness/core_checks/__init__.py`
- Modify: `tc-fitness/pyproject.toml`

**Interfaces:**
- Consumes: identities, roots and observed filesystem evidence through `ContractDocuments`.
- Produces: `RuntimeAccessMatrix` and `validate_access_matrix(documents) -> tuple[ContractFinding, ...]`.

- [ ] **Step 1: Write access sabotage cases**

Cover parent traversal, read/write, create/delete/rename parent semantics, sticky directories, supplementary groups, setgid, default ACL, umask, created-object metadata and explicit secret denial. Include the production regression where a runtime identity cannot update `pairing/slack-approved.json` because its parent or file is root-owned.

- [ ] **Step 2: Prove the failures**

```bash
uv run pytest -q tests/test_core_runtime_access_matrix.py
```

Expected: failures identify the absent validator.

- [ ] **Step 3: Implement matrix completeness and verdict comparison**

Require exactly one observation per declared `(identity, namespace, root, path, operation)` tuple. Compare actual allow/deny outcomes and metadata with the contract. Require real created-file and directory evidence for ACL/setgid/umask inheritance.

- [ ] **Step 4: Register and verify**

```bash
uv run pytest -q tests/test_core_runtime_access_matrix.py tests/test_runtime_contracts.py tests/test_core_registry_consistency.py
uv run ruff check src/tc_fitness/core_checks/runtime_access_matrix.py tests/test_core_runtime_access_matrix.py
uv run mypy src/tc_fitness
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/tc_fitness/core_checks/runtime_access_matrix.py \
  src/tc_fitness/core_checks/__init__.py tests/test_core_runtime_access_matrix.py pyproject.toml
git commit -m "feat: validate runtime access matrices"
```

### Task 5: Add deployment transaction validation and integrated dispatch

**Files:**
- Create: `tc-fitness/src/tc_fitness/core_checks/deployment_transaction_contract.py`
- Create: `tc-fitness/tests/test_core_deployment_transaction_contract.py`
- Create: `tc-fitness/tests/test_core_runtime_contract_dispatch.py`
- Create: `tc-fitness/docs/runtime-contracts.md`
- Modify: `tc-fitness/src/tc_fitness/core_checks/__init__.py`
- Modify: `tc-fitness/pyproject.toml`
- Modify: `tc-fitness/README.md`
- Modify: `tc-fitness/CHANGELOG.md`
- Modify: `tc-fitness/docs/STANDARDS.md`

**Interfaces:**
- Consumes: ordered transaction events and identity helpers from `_runtime_contracts.py`.
- Produces: `DeploymentTransactionContract`, `validate_deployment_transaction(documents) -> tuple[ContractFinding, ...]` and four complete registered CORE checks.

- [ ] **Step 1: Write transaction sabotage cases**

Exercise the successful event order and mutations for preflight failure followed by mutation, mutation before recovery, candidate identity change, probe before apply, wrong probe identity, cutover before probe, absent diagnostics, rollback without verification, rollback converted to candidate success, and cleanup deleting recovery before 172800 seconds.

- [ ] **Step 2: Prove the failures**

```bash
uv run pytest -q tests/test_core_deployment_transaction_contract.py tests/test_core_runtime_contract_dispatch.py
```

Expected: failures identify the absent validator and registrations.

- [ ] **Step 3: Implement the state machine**

Use explicit states and accepted transitions:

```python
SUCCESS_PHASES = ("preflight", "recovery", "apply", "probe", "cutover", "cleanup")
FAILURE_PHASES = ("diagnostics", "rollback", "rollback_probe", "cleanup")
```

Require strictly increasing sequence numbers, one immutable transaction/candidate identity and a retained recovery reference. Keep candidate verdict and recovery verdict as separate fields.

- [ ] **Step 4: Prove catalogue dispatch and unchanged adoption**

Run all four checks through the real catalogue path. Assert a consumer with no blocks has byte-identical verdict output before and after the engine change. Assert subprocess dispatch configuration still resolves CORE checks in-process.

Add the `validate` subcommand to `tc-fitness-runtime-contract`. It runs the selected filesystem, access and deployment validators against one contract and writes their combined canonical result without duplicating their logic.

- [ ] **Step 5: Document the protocol and verify the engine**

```bash
uv run pytest -q
uv run tc-fitness run
git diff --check
```

Expected: the full engine gate passes on Python 3.12 and 3.13.

- [ ] **Step 6: Commit**

```bash
git add src/tc_fitness/core_checks tests docs README.md CHANGELOG.md pyproject.toml
git commit -m "feat: validate deployment transactions"
```

### Task 6: Qualify and release the tc-fitness candidate

**Files:**
- Modify temporarily in qualification worktree: `tc-agent-zone/pyproject.toml`
- Modify temporarily in qualification worktree: `tc-agent-zone/uv.lock`
- Create in qualification worktree: `tc-agent-zone/tests/fixtures/deployment-contract/valid.json`
- Create in qualification worktree: `tc-agent-zone/tests/fixtures/deployment-contract/sabotaged.json`

**Interfaces:**
- Consumes: exact tc-fitness candidate commit from Tasks 2–5.
- Produces: candidate qualification evidence and the next immutable tc-fitness patch tag.

- [ ] **Step 1: Prove no-config compatibility**

Use `fitness-engine-canary.yml` to repin tc-agent-zone to the exact candidate commit with no new configuration. Run the complete consumer gate and compare its fitness ledger digest with the current v0.15.1 result.

- [ ] **Step 2: Prove adopted valid and sabotaged contracts**

Bind all four checks to the valid fixture and require green. Replace the fixture with each sabotage document and require the named check to fail with `fix:`, `next:` and `run:`.

- [ ] **Step 3: Run consumer-local parity**

```bash
make bootstrap
make check
make dry-run
```

Expected: valid fixture passes; every deliberately sabotaged run fails at its intended check; restoring valid fixture returns all commands to green.

- [ ] **Step 4: Publish the next immutable patch release**

Use the repository release process to derive the next patch version from the current `VERSION`. Tag only the exact green candidate commit. Record the tag and commit in the plan ledger.

### Task 7: Add the tc-pipelines deployment-contract action

**Files:**
- Create: `tc-pipelines/.github/actions/deployment-contract/action.yml`
- Create: `tc-pipelines/governance/scripts/tests/test_deployment_contract.py`
- Modify: `tc-pipelines/governance/scripts/tests/test_uses_ref_pinning.py`

**Interfaces:**
- Consumes: canonical contract JSON, independent expected identity values, target receipt JSON and the consumer's immutable pinned `tc-fitness-runtime-contract` executable.
- Produces: `validate`, `render-invocation` and `verify-receipt` operations plus outputs `contract-digest`, `receipt-digest`, `conformance-status` and `diagnostic-artifact-name`.

- [ ] **Step 1: Write action contract failures**

Test strict parsing, duplicate IDs, canonical hashing, unsafe entrypoints, contract/artifact/target mismatch, stale attempt/nonce, missing probes, failed probes and evidence size bounds.

- [ ] **Step 2: Prove the failures**

```bash
uv run pytest -q governance/scripts/tests/test_deployment_contract.py
```

Expected: failures identify the absent composite and helper.

- [ ] **Step 3: Implement validation and rendering**

Invoke `uv run tc-fitness-runtime-contract validate` in the consumer checkout. Represent remote commands as an executable plus argv list, constrain them to the verified consumer artifact, and pass protected parameters through file descriptors. Validate and hash contract bytes before any Azure authentication.

- [ ] **Step 4: Implement receipt verification**

Invoke `uv run tc-fitness-runtime-contract verify-evidence` with independent expected values. Validate intended and observed release identity, host/runtime identity, run/attempt/nonce, ordered phases, probe results, recovery digest and terminal state. Verify retrieved receipt bytes against the transported digest.

- [ ] **Step 5: Verify**

```bash
uv run pytest -q governance/scripts/tests/test_deployment_contract.py governance/scripts/tests/test_uses_ref_pinning.py
uv run tc-fitness run
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit**

```bash
git add .github/actions/deployment-contract governance/scripts/tests
git commit -m "feat: validate deployment contracts"
```

### Task 8: Integrate the contract with the Azure VM reusable

**Files:**
- Modify: `tc-pipelines/.github/workflows/azure-vm-deploy.yml`
- Modify: `tc-pipelines/governance/scripts/tests/test_azure_vm_deploy_preflight.py`
- Modify: `tc-pipelines/governance/scripts/tests/test_azure_vm_deploy_protected_run_command.py`
- Modify: `tc-pipelines/governance/scripts/tests/test_internal_call_contracts.py`

**Interfaces:**
- Consumes: Task 7 action and the existing WIF, Run Command, VM lock, snapshot, protected marker and cleanup surfaces.
- Produces: optional workflow inputs `deployment-contract` and `deployment-contract-digest`; outputs `conformance-status`, `conformance-receipt-digest` and `conformance-artifact-name`.

- [ ] **Step 1: Write transaction integration failures**

Extend fake-Azure execution tests for apply failure, probe failure, rollback success, rollback failure, cancellation, retained failure evidence and cleanup order. Assert successful rollback leaves deployment status failed.

- [ ] **Step 2: Add optional inputs with conflict detection**

Legacy callers remain unchanged. A contract caller supplies both contract bytes and digest and receives an error when legacy target/policy values conflict with the contract.

- [ ] **Step 3: Run the complete transaction under the existing VM lock**

Validate before WIF. Execute consumer preflight, recovery, apply, exact-runtime probe, cutover or rollback through the existing safe transport. Publish full secret-safe evidence as an immutable Actions artifact before returning a failed result.

- [ ] **Step 4: Pin internal action references and verify**

```bash
uv run pytest -q governance/scripts/tests/test_azure_vm_deploy_preflight.py \
  governance/scripts/tests/test_azure_vm_deploy_protected_run_command.py \
  governance/scripts/tests/test_internal_call_contracts.py
uv run pytest -q
uv run tc-fitness run
```

Expected: all commands exit 0 and every literal action reference points at the reviewed commit.

- [ ] **Step 5: Exercise and release the reusable**

Force the changed reusable path to execute in its PR. After merge, publish the next immutable tc-pipelines patch tag and record its commit. Keep Goss outside this first release; the existing Python/shell collector already carries the required identity and rollback semantics.

### Task 9: Restore the tc-agent-zone target registry and bind shared checks

**Files:**
- Create: `tc-agent-zone/deployment-targets.yaml`
- Create: `tc-agent-zone/tests/contract/test_deployment_targets.py`
- Create: `tc-agent-zone/tests/fixtures/deployment-contract/valid-evidence.json`
- Modify: `tc-agent-zone/.github/CODEOWNERS`
- Modify: `tc-agent-zone/agent-zone.manifest.yaml`
- Modify: `tc-agent-zone/pyproject.toml`
- Modify: `tc-agent-zone/uv.lock`
- Modify: `tc-agent-zone/scripts/checks/_rule_catalogue.py`
- Modify: `tc-agent-zone/Makefile`
- Modify: `tc-agent-zone/RESOLVER.md`

**Interfaces:**
- Consumes: immutable tc-fitness tag from Task 6 and the protocol in Task 5.
- Produces: one canonical YAML target registry selected and canonicalised by the shared engine for local, CI and deployment use.

- [ ] **Step 1: Write registry resolution failures**

Assert the documented root registry exists; every configured environment resolves one VM, cluster, runtime identity, path namespace, mount, recovery and probe definition; duplicate YAML keys fail; two `resolve` calls are byte-identical; and the digest changes for a semantic value change.

- [ ] **Step 2: Prove the failures**

```bash
uv run pytest -q tests/contract/test_deployment_targets.py
```

Expected: failures report the missing registry and unresolved target.

- [ ] **Step 3: Author the Hermes production contract**

Declare `/hermes-home`, every `/hermes-home/profiles/{profile}` root, `/data/obsidian-vault`, the release staging tree, managed configuration, executable path, runtime UID/GID, shared groups, mount direction, symlinks, access operations, probes, rollback and 172800-second retention. Reference secret names only.

Protect the registry with `@three-cubes/maintainers`, add it to `agent-zone.manifest.yaml`, preserve `version-catalog.json` as the version authority, and reference `platform/hermes/clusters.yaml` rather than copying its cluster rows.

- [ ] **Step 4: Resolve through the shared engine**

Run `tc-fitness-runtime-contract resolve --contract deployment-targets.yaml --environment prod --target hermes --output "$RUNNER_TEMP/hermes-runtime-contract.json"`. Local checks load the YAML directly; workflow inputs consume those exact selected canonical bytes and their printed SHA-256 digest.

- [ ] **Step 5: Register four checks and bind the declaration checks**

Add four catalogue rows. Bind the three declaration checks directly to the canonical registry:

```toml
[tool.tc_fitness.core_checks.runtime_filesystem_contract]
contract_file = "deployment-targets.yaml"
environment = "prod"
target = "hermes"

[tool.tc_fitness.core_checks.runtime_access_matrix]
contract_file = "deployment-targets.yaml"
environment = "prod"
target = "hermes"

[tool.tc_fitness.core_checks.deployment_transaction_contract]
contract_file = "deployment-targets.yaml"
environment = "prod"
target = "hermes"
```

The runtime-evidence catalogue row remains opt-in during ordinary authoring and is exercised with explicit live paths by `tc-fitness-runtime-contract verify-evidence` in deployment. Pin the immutable tc-fitness tag, regenerate `uv.lock`, and keep `make check` and CI on the same direct registry inputs.

- [ ] **Step 6: Verify locally**

```bash
make bootstrap
make check
make dry-run
```

Expected: all commands exit 0 with the valid canonical registry and finish without network access in the fast tier.

- [ ] **Step 7: Commit**

```bash
git add deployment-targets.yaml tests/contract/test_deployment_targets.py \
  tests/fixtures/deployment-contract \
  .github/CODEOWNERS agent-zone.manifest.yaml pyproject.toml uv.lock \
  scripts/checks/_rule_catalogue.py Makefile RESOLVER.md
git commit -m "feat: declare the Hermes deployment contract"
```

### Task 10: Produce real container and VM conformance evidence

**Files:**
- Create: `tc-agent-zone/devsecops/apply/hermes/collect-runtime-conformance.py`
- Create: `tc-agent-zone/tests/contract/test_hermes_runtime_conformance.py`
- Modify: `tc-agent-zone/.github/workflows/deploy-hermes-cluster.yml`
- Modify: `tc-agent-zone/devsecops/apply/tc_deploy_control.py`
- Modify: `tc-agent-zone/tests/fitness/test_hermes_deployment_admission.py`

**Interfaces:**
- Consumes: selected canonical contract bytes, exact release artifacts and tc-pipelines receipt interface.
- Produces: `tc-fitness/runtime-evidence/v1` observations from the real runtime identities and exact deployed candidate.

- [ ] **Step 1: Write Linux/container sabotage journeys**

Materialise users and groups in a disposable Linux container. Exercise all declared operations against real mounts and symlinks. Sabotage wrong owner, group, parent execute bit, setgid, umask, default ACL, sticky directory, profile root, executable path and runtime user. Assert each defect fails before cutover.

- [ ] **Step 2: Implement the collector**

Run bounded argv commands as each declared identity. Record operation result and observed metadata without changing protected source paths. Capture the declared dependency inventory with a schema version and timestamp so missing or stale inventory fails the evidence contract. Use atomic creation for the final receipt and hash every referenced diagnostic artifact.

- [ ] **Step 3: Integrate the exact contract with deployment**

Pass the selected canonical contract and digest to the new tc-pipelines inputs. Collect evidence after apply and before cutover. Preserve evidence on apply, probe, rollback and cleanup failure.

- [ ] **Step 4: Verify locally**

```bash
uv run pytest -q tests/contract/test_hermes_runtime_conformance.py \
  tests/fitness/test_hermes_deployment_admission.py
make dry-run
```

Expected: valid container journey passes and every sabotage case fails at its intended boundary.

- [ ] **Step 5: Commit**

```bash
git add devsecops/apply/hermes/collect-runtime-conformance.py \
  devsecops/apply/tc_deploy_control.py .github/workflows/deploy-hermes-cluster.yml \
  tests/contract/test_hermes_runtime_conformance.py tests/fitness/test_hermes_deployment_admission.py
git commit -m "feat: verify Hermes runtime conformance"
```

### Task 11: Qualify the exact production candidate

**Files:**
- Evidence artifact: `runtime-evidence.json`
- Evidence artifact: `deployment-receipt.json`
- Existing product evidence: Hermes fleet PVT, Kairix/Neo4j and Obsidian receipts

**Interfaces:**
- Consumes: exact release SHA, image digest, contract digest and prior known-good recovery receipt.
- Produces: one successful production cutover receipt plus product PVT and learning-harvest evidence.

- [ ] **Step 1: Run preflight without mutation**

Validate candidate provenance, contract digest, recovery reference, capacity, dependencies, runtime identities, mount parents and cleanup prerequisites. Retain the preflight receipt.

- [ ] **Step 2: Inject one controlled probe failure before production cutover**

Use a disposable deployment attempt to prove diagnostics, rollback, rollback verification, failed-candidate status and cleanup evidence. Confirm the active known-good deployment remains unchanged.

- [ ] **Step 3: Deploy the exact candidate**

Run the protected production workflow once. Monitor preparation, apply, runtime conformance, cutover and product PVT to terminal state. A failed phase uses retained evidence for a local reproduction before another release attempt.

- [ ] **Step 4: Verify product behaviour**

Exercise Hermes profile/plugin discovery, provider inference, cross-profile vault access, Slack approval persistence, restart recovery, Obsidian sync, Kairix indexing and Neo4j graph read-back. Bind every result to the deployment receipt.

- [ ] **Step 5: Complete learning retention and assessment**

Verify the protected EXE-75 candidate ledger remains complete, run the paired assessment against the exact deployed release, and attach the accepted disposition evidence to EXE-75 and EXE-90.

### Task 12: Retire proven duplication and close the feedback loop

**Files:**
- Review: `tc-agent-zone/scripts/checks/runtime_path_integrity.py`
- Review: `tc-agent-zone/scripts/checks/sudoers_validate.py`
- Review: `tc-agent-zone/scripts/checks/vm_dependency_drift.py`
- Review: `tc-agent-zone/scripts/checks/workspace_policy_artefacts.py`
- Review: `tc-agent-zone/scripts/checks/workspace_policy_compliance.py`
- Modify only after parity: `tc-agent-zone/scripts/checks/_rule_catalogue.py`
- Modify: `tc-pipelines/governance/standards/infrastructure-deployment-fitness.md`

**Interfaces:**
- Consumes: local/shared verdict comparison and live production receipts.
- Produces: one implementation per generic invariant and a recorded exception for every product-specific check retained.

- [ ] **Step 1: Classify each existing check**

Use `retain` for product semantics, `migrate` for generic logic and `remove-after-parity` for duplicate generic checks. Record old/new verdicts, diagnostics and runtime cost.

Use this initial classification:

| Existing surface | Initial decision | Evidence required to change it |
|---|---|---|
| `runtime_path_integrity.py` ToolPack branch | remove-after-parity | Same unresolved-binding set as `toolpack_manifest_consistency.py` |
| `runtime_path_integrity.py` cron writable-root branch | migrate | Shared filesystem contract catches every valid and invalid cron root |
| `sudoers_validate.py` | retain, then migrate | Shared syntax check fails when `visudo` is required and absent; live access evidence proves `sudo -n` behaviour |
| `vm_dependency_drift.py` | retain, then migrate | Fresh schema-versioned inventory is required evidence; missing and stale inventory fail |
| Hermes mount, installer, permission, cleanup and PVT tests | retain | Product behaviour remains distinct from shared contract semantics |

- [ ] **Step 2: Prove parity before removal**

Run valid and sabotaged fixtures through both implementations. Require the shared check to catch every old failure plus the new namespace, access and evidence failures.

- [ ] **Step 3: Remove duplicate catalogue entries**

Remove only entries classified `remove-after-parity`. Promote a repository-agnostic sudoers syntax check and inventory-drift comparison into `tc-fitness` after their required-tool and required-evidence semantics are proven against tc-agent-zone. Keep Hermes product PVT and exact-image tests as final qualification.

- [ ] **Step 4: Verify all repositories**

```bash
# tc-fitness
uv run tc-fitness run

# tc-pipelines
uv run pytest -q
uv run tc-fitness run

# tc-agent-zone
make check
make dry-run
```

Expected: every command exits 0, the fast consumer contract tier remains below 60 seconds, and the production receipt is linked from the delivery ledger.

- [ ] **Step 5: Update the canonical standard with measured results**

Record check runtimes, consumer qualification commit, immutable engine and pipeline tags, production deployment receipt and the final retain/migrate/remove classification.
