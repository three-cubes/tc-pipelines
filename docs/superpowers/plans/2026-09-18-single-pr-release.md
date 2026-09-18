# Single-PR Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace separate version-only PRs with same-branch mechanical preparation and an idempotent release of the exact reviewed merge commit.

**Architecture:** tc-pipelines owns preparation and release behaviour. A feature branch receives generated metadata before review; a receipt-changing merged PR invokes a pinned reusable which validates and tags its exact merge SHA. Consumer repositories carry only thin callers and their version metadata.

**Tech Stack:** Python 3.12, uv, Git, GitHub Actions reusable workflows, pytest, PyYAML.

**Spec:** `docs/superpowers/specs/2026-09-18-single-pr-release-design.md`

## Global Constraints

- Use `three-cubes-agent` for every GitHub write and commit identity.
- Do not execute pull-request-controlled code with a privileged token.
- Do not create a post-merge source commit.
- Preserve explicit-version CalVer support.
- Tag only the exact reviewed merge SHA.
- Replays must be safe and must reject an existing tag at another SHA.

---

### Task 1: Behavioural preparation command

**Files:**
- Modify: `actions/prepare-release-metadata/prepare_release.py`
- Modify: `actions/prepare-release-metadata/action.yml`
- Test: `governance/scripts/tests/test_release_preparation.py`

**Interfaces:**
- Consumes: either `version: str` or `bump: Literal["major", "minor", "patch"]`, plus changelog, optional version file, receipt path and tag prefix.
- Produces: prepared CHANGELOG, version source/uv lock updates, receipt, and the resolved tag printed as `version=<tag>`.

- [x] Write subprocess tests that run the command in real temporary uv projects and assert on changed package metadata, lockfile, CHANGELOG and receipt.
- [x] Run the focused test and confirm the bump case fails because `--bump` is not accepted.
- [x] Add mutually exclusive version/bump parsing and invoke `uv version --bump <part> --no-sync` for bump mode.
- [x] Extend the composite action inputs and expose the resolved version output.
- [x] Run the focused tests and the existing release-preparation tests.

### Task 2: Exact-SHA idempotent tag helper

**Files:**
- Modify: `.github/workflows/release.yml`
- Test: `governance/scripts/tests/test_release_tag.py`

**Interfaces:**
- Consumes: repository path, validated tag, exact 40-character target SHA, annotation message.
- Produces: a `created` output; creates one local annotated tag only when absent. The behavioural test executes the exact workflow step against a real Git repository because a called reusable checks out the consumer repository and cannot address an unpublished local composite action.

- [x] Write real-Git tests for absent tag, same-SHA replay, and different-SHA conflict.
- [x] Run the focused test and confirm it fails because the exact-SHA step is absent.
- [x] Implement the exact-SHA step without network calls and make the workflow push only a newly created tag.
- [x] Make GitHub Release creation idempotent while rejecting conflicting state.
- [x] Run focused tests and release workflow contract tests.

### Task 3: Same-PR preparation and merge-triggered release wiring

**Files:**
- Create: `.github/workflows/release-on-merge.yml`
- Modify: `governance/scripts/bootstrap-repo-governance.sh`
- Modify: `governance/scripts/tests/test_bootstrap_repo_governance.py`
- Modify: `governance/scripts/tests/test_release_notes_coverage.py`
- Modify: `governance/standards/sdlc-release-workflow.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: exact merge SHA and receipt path from a thin consumer caller.
- Produces: resolved receipt version and a call into the release spine for that exact SHA.

- [x] Change bootstrap tests to require App-token same-branch preparation and a receipt-filtered merged-PR caller.
- [x] Run the focused tests and confirm they fail against the separate-release-PR wiring.
- [x] Render the two workflows and add the reusable resolver/release workflow.
- [x] Replace the release standard's second-PR procedure with the single-PR flow and update the action catalogue.
- [x] Run bootstrap, release, YAML, shell and documentation checks.

### Task 4: Integrated verification and tc-fitness migration

**Files:**
- Modify in tc-fitness PR #62: `.github/workflows/prepare-release.yml`
- Create in tc-fitness PR #62: `.github/workflows/release-on-merge.yml`
- Create in tc-fitness PR #62: `.release-prepared.json`
- Modify in tc-fitness PR #62: `src/tc_fitness/__init__.py`
- Modify in tc-fitness PR #62: `tests/test_version.py`

**Interfaces:**
- Consumes: immutable tc-pipelines release SHA and tc-fitness version `0.16.1` already present on PR #62.
- Produces: a final migration PR whose merge automatically creates `v0.16.1`; future releases use their original feature PR.

- [x] Run the full tc-pipelines local gate and inspect the integrated diff.
- [ ] Commit, push and obtain green required checks for the canonical tc-pipelines PR.
- [ ] Release/tag tc-pipelines and pin the immutable SHA in tc-fitness callers.
- [ ] Write a failing tc-fitness version test that rejects a mutable fallback literal, then replace it with metadata-only version resolution plus a stable unknown fallback.
- [ ] Generate the v0.16.1 receipt, run the full tc-fitness gate, update PR #62, and verify its required checks and conversations.
