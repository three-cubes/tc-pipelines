# Testing Strategy

*Strategic testing philosophy and comprehensive quality framework across all technology stacks.*

## Testing Philosophy

Our testing approach prioritises **regression prevention** through **contract enforcement**, **state validation**, and **systematic user experience protection**.

**Core Principles:**

- Test component agreements, not implementations
- Fail fast at integration boundaries
- Maintain user experience consistency
- Prevent regressions before they occur
- Every deploy must prove the app works end-to-end before traffic is routed

---

## Behavioural test tiers

Choose the tier that directly observes the claim. A critical claim receives
real-boundary evidence in the release path; lower tiers provide fast diagnosis
and regression coverage for the same rule.

| Tier | What it proves | Evidence |
|------|----------------|----------|
| **Unit** | A deterministic component makes its required decision. | Inputs and observable return values, files or state from the component's public interface. |
| **Contract** | A published interface preserves its schema, protocol and error behaviour. | A real implementation or versioned protocol collaborator at the interface boundary. |
| **Integration** | Components exchange data and preserve the required outcome. | A process, service container, filesystem, database or other production-equivalent boundary. |
| **Journey / E2E** | A user, deploy or operational flow reaches its intended outcome. | The public executable or endpoint plus the produced response, file, receipt or deployment state. |

Focused doubles support unit-level collaborator behaviour. Integration and
journey claims use the real boundary named by the claim, and release admission
uses retained evidence from that execution.

---

## BDD Scenario Tier Policy

Every `.feature` scenario carries a tier that names the evidence it demands.
Declare `@tier:walker` or `@tier:e2e` immediately above the `Scenario:` line;
a tag above the `Feature:` header supplies the tier for each scenario in that
feature.

### Tier definitions

| Tier | Demand | When to use |
|---|---|---|
| **`@tier:e2e`** | The journey runs end-to-end via `subprocess.run` / `Popen` / `check_*` (or, for in-process tools, an equivalent isolation-respecting executor). The test must observe captured output / written file / returned envelope content. | User journeys: agent dispatch behaviour, deploy / apply pipelines, governance flows, cross-process integration. Anything where "the title round-trips" doesn't prove the behaviour holds. |
| **`@tier:walker`** | The scenario title is bound to a test (function name slug, parametrize id, string literal, or `@scenario("...feature", "...")` decorator). Semantic coverage lives in a sibling **sabotage / contract / unit** test that exercises the same rule. | Fitness-gate scenarios where the rule is enforced by inverting it in a Python sabotage test; declarative scenarios whose semantic surface is a schema or AST rule already pinned elsewhere. |
| **(untagged)** | Invalid. | Add an explicit scenario or feature tier before the scenario enters the suite. |

### The enforcing gate

The `bdd_scenario_walked` fitness check runs two rules against each scenario:

1. **Title-bind (always):** at least one test file in `tests/**/*.py` binds the title (slug / parametrize id / string literal / pytest-bdd decorator). Fails when a scenario is unbound entirely.
2. **E2E-execute (`@tier:e2e` only):** at least one binding test file also invokes `subprocess.run` / `subprocess.Popen` / `subprocess.check_call` / `subprocess.check_output` / `subprocess.call`. Fails when an `@tier:e2e` scenario is only title-bound.

Both failure classes are current findings. The gate reports each missing bind,
missing executor and missing tier as a failure; the suite carries zero
grandfathered BDD findings.

### Migrating a feature to `@tier:e2e`

```gherkin
@tier:e2e
Feature: Agent boundary enforcement

  Scenario: The agent declines an out-of-scope request
    Given the live agent
    When the operator dispatches "delete prod database"
    Then the response is a structured refusal
    And the refusal names the violated boundary
```

The bound test must subprocess-execute the journey:

```python
# tests/bdd/agents/<agent>/test_boundary_e2e.py
import subprocess
import pytest

pytestmark = pytest.mark.e2e


def test_agent_declines_an_out_of_scope_request():
    r = subprocess.run(
        [
            "agent-runtime",
            "dispatch",
            "--agent=<agent>",
            "--input=delete prod database",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert "outside scope" in r.stdout.lower()
    assert "boundary" in r.stdout.lower()
```

A `@tier:walker` scenario for the same area would point a sibling sabotage test at the boundary rule (e.g. `tests/fitness/test_agent_boundary_enforcement.py`) and bind the title via a `SCENARIOS = [...]` tuple. The gate accepts the latter only when the tier is walker.

### Stay inside the tier contract

- **Pair every title-bind with a semantic test.** A `SCENARIOS = ["..."]` tuple must reference a sibling sabotage / contract / unit test that actually fires when the rule breaks; walker tier requires the semantic test to exist (reviewer discipline today, gate planned).
- **Land the executor in the same PR as `@tier:e2e`.** Tag and subprocess executor ship together; the gate FAILs the tag without the executor.
- **Override walker-acceptable scenarios per-scenario.** When a feature-level `@tier:e2e` block contains scenarios that are walker-acceptable, add `@tier:walker` on those scenarios; keep the feature-level tag as the default and let scenario-level overrides win.

## Behavioural evidence integrity

A source-shape test proves the static invariant it asserts. Reading a
Dockerfile, workflow, script or configuration file establishes structural
policy or contract evidence. Behavioural claims add an execution through the
named public boundary and retain the observed outcome.

Every critical deployable surface also declares executable evidence through
the `tc-fitness` `core:behavioural_evidence` check. Its consumer configuration:

1. selects the critical files with `surface_globs`;
2. names the accepted integration, E2E, journey or equivalent pytest markers
   with `behaviour_markers`; and
3. declares one or more `claims`, each with a stable `id`, exact `surfaces`,
   behavioural `tests` and invoked `executables`.

The check passes only when a named, marked test invokes the declared executable,
observes process success and asserts a produced file, response or retained
receipt passed to that executable. Static source assertions, an unrelated
subprocess, missing or unmarked tests, unclaimed matched surfaces, an unobserved
process result, or an unobserved output fail the check. This is a hard gate;
baselines cannot suppress its findings.

Run every named behavioural test in the required local release gate and PR
gate. Nightly or soak-only execution does not provide merge evidence.

## Preparation before evaluation and local-hosted parity

Deterministic preparation runs before any evaluator observes a candidate. The
preparation receipt binds the candidate SHA, tree, tool policy and resulting
patch; a changed candidate receives a fresh evaluation on its prepared head.

Local and hosted execution use the same declared preparation policy, tool
version, configuration and path selection. The hosted writer independently
replays the policy from the recorded head before it applies the result. Local
verification exercises the same policy and records its outcome, while hosted
qualification retains the workflow identity and receipt needed for release
admission.

---

## Contract Testing

### Why Contracts Are Critical

Contracts make interface expectations explicit at the boundaries where
components exchange data. Contract tests prevent:

- Interface changes breaking dependent components
- Data format changes causing integration failures
- State synchronisation issues between components
- UI/UX regressions from component interface changes

### Contract test categories

| Category | Purpose |
|----------|---------|
| **Interface contracts** | Preserve public component interfaces. |
| **Data-flow contracts** | Preserve required data formats and transformations. |
| **State-consistency contracts** | Preserve state across related components. |

### Contract Failure Policy

- **Zero tolerance** — contract failures block all development and merges
- Contract tests must be deterministic (no flaky tests)
- Contract tests support the required local feedback loop

---

## Quality Gates

### Pre-Commit (MANDATORY)

1. **Contract validation** — Zero contract test failures allowed
2. **Critical path protection** — All critical user paths must remain functional
3. **Type checking** — Zero type errors (TypeScript `tsc`, Python `mypy`)
4. **Linting** — Code meets style and quality standards

### CI/CD Pipeline

| Stage | Gate | Policy |
|-------|------|--------|
| Stage 1: Contracts | Contract tests pass | Blocks promotion on failure |
| Stage 2: Unit + Type | Unit tests and type checking | Blocks promotion on failure |
| Stage 3: Integration | Integration tests pass | Blocks promotion on failure |
| Stage 4: E2E | User experience validation | Blocks promotion on failure |

### Post-Deploy

- Health check endpoint returns 200
- Auth smoke test passes (authenticated request succeeds)
- No crash loops in container logs
- New revision confirmed running

---

## Language-Specific Guidance

### Node.js / TypeScript

| Aspect | Standard |
|--------|----------|
| **Test runner** | Jest (unit), Playwright (E2E) |
| **Type checking** | `tsc --noEmit` — zero errors, CI blocks merge |
| **Coverage** | ≥80% line/statement |
| **API testing** | Supertest against real database (service container in CI) |
| **Accessibility** | `jest-axe` for UI components |
| **Auth smoke tests** | Post-deploy, pre-traffic — prove authenticated API request succeeds |
| **Boundary evidence** | Exercise the public interface with real filesystem, process and service-container collaborators where the claim needs them. |

### Python

| Aspect | Standard |
|--------|----------|
| **Test runner** | pytest with markers (`contract`, `unit`, `integration`, `bdd`) |
| **Type checking** | mypy — zero errors |
| **Coverage** | ≥80% overall, 100% for security-critical functions |
| **SAST** | Bandit — zero HIGH/MEDIUM findings |
| **Dependencies** | Safety — zero known CVEs with patches available |
| **Boundary evidence** | Use temporary directories for file tests and execute the named public boundary for integration and journey claims. |

---

## Test Execution Strategies

### Development Cycle (Fast Feedback)

```bash
# Quick validation during development
# Python: pytest -m "contract or (unit and not slow)" --maxfail=5
# Node:   pnpm test --bail
```

### Pre-Commit (Safety Gate)

```bash
# Must pass before commit
# Python: pytest -m "contract or critical" --maxfail=1
# Node:   pnpm typecheck && pnpm test
```

### Full Pipeline (Comprehensive)

```bash
# Complete validation before deployment
# Python: pytest -m contract && pytest -m integration && pytest -m bdd
# Node:   pnpm typecheck && pnpm test && pnpm build
```

---

## Regression Prevention Protocol

When a regression occurs:

1. **Categorise** — Interface change, state desync, data format, or user experience?
2. **Identify missing contract** — What test would have prevented this?
3. **Add prevention test** — Create the contract/regression test
4. **Fix the regression** — Make the new test pass
5. **Verify no new regressions** — Run full test suite

### Contract Maintenance

- **Interface changes** → Update contract tests FIRST
- **New components** → Define contracts before integration
- **Refactoring** → Verify contracts remain satisfied
- **Bug fixes** → Add regression prevention contract

---

## Test Organisation

### Naming Conventions

```
# Unit tests — test what it does
test_extracts_text_from_pdf()
test_calculates_token_count()

# Integration — test interaction
test_content_to_ai_pipeline()
test_auth_token_flow_end_to_end()

# E2E — test user stories
test_user_processes_batch_of_pdfs()

# Regression — reference the issue
test_regression_issue_423_path_traversal()
```

## Test Data Security — No Real or Production Data (P0)

**Confidential data leakage via test fixtures is a first-class security concern.**

Test data must always be fictional and generic, regardless of repo visibility. A private repo can be made public, history can leak, and contributors may not have the same confidentiality obligations.

### Rules

- **Never use real client names** — use `Acme Corp`, `Widget Co`, `Global Industries`
- **Never use real people's names** — use `Jane Smith`, `John Doe`, `Alex Chen`
- **Never use real project names** — use `Project Alpha`, `Initiative B`, `Platform X`
- **Never use real internal paths** — make deployment paths configurable via env vars; use `~/test-vault/` in tests, not a real absolute path like `/data/vault/`
- **Never commit result/output files** — benchmark results, generated reports, export files are outputs, not source; add to `.gitignore`
- **Audit before publishing** — before making a repo public, run a grep for real names, internal paths, and result files

### Pre-publish audit checklist

```bash
# Check for real names and internal paths
grep -rn "real_client_name\|real_person\|/data/production/" tests/ --include="*.py"
# Check for output files that shouldn't be committed
git ls-files | grep -E "\.(json|csv|xlsx)$" | grep -i "result\|output\|export"
```

### Consequence

Violation = immediate repo visibility change to private until remediated.

---

### Collaborator strategy

Focused unit tests may use a controlled collaborator to establish a protocol or
error-handling decision. Their result is labelled unit evidence. Contract,
integration and journey tests exercise the real boundary required by the
claim: temporary filesystems for file behaviour, service containers for
databases, and the public executable or endpoint for operational behaviour.
Release evidence records that boundary execution and its observable outcome.

---

## Evidence outcomes

The testing programme is effective when critical claims have current
real-boundary evidence, contract and quality findings block promotion, and the
local feedback loop supplies a timely diagnosis before hosted qualification.

---

*For tactical implementation details, contract test patterns, and TDD workflow, use this standard and the repo standards index.*


---

## Per-repo reconciliation notes

Apply these repo-specific rules when adopting this baseline in a given repo:

- Branch from current `main` and use PRs for all repo changes.
- Do not edit live runtime config directly; change templates/scripts in the repo and apply only after explicit approval.
- Do not restart live services or deploy as part of documentation or standards work.
- One complete-feature PR with evidence (diff, validation command, rollback note) — never micro-PRs; see the development-workflow standard §Branching.
