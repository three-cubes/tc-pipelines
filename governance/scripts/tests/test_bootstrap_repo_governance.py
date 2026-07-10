"""Contract test for the bootstrap-repo-governance.sh operator entrypoint (SGO-164).

Exercises the CLI contract (the public surface an operator/agent relies on) —
not the live `gh`/`az` calls. The help branch, arg-parse, and the local
affordance render run before any network write, so these cases are hermetic:
the affordance render sources governance/skeletons/ from this checkout, and the
live sections are toggled off (--no-secrets/--no-ruleset/--no-files) so the
--dry-run path prints its payload without pushing.

Interface: shell-entrypoint.governance.scripts.bootstrap-repo-governance
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = "governance/scripts/bootstrap-repo-governance.sh"

# A template placeholder is UPPER_SNAKE in double braces ({{REPO}}); this is
# distinct from a GitHub Actions ${{ expression }}, so a resolved wiring file must
# carry no match of THIS pattern while keeping its GHA expressions intact.
TEMPLATE_TOKEN_RE = re.compile(r"\{\{[A-Z_]+\}\}")
# External contexts posted by an app (not a ci.yml job) — verify allows these.
EXTERNAL_CONTEXTS = {"SonarCloud Code Analysis"}


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    # The script path is a literal here (not a Path var) so an outcome-test gate
    # can match the surface name in the subprocess call; cwd resolves it.
    return subprocess.run(
        ["bash", "governance/scripts/bootstrap-repo-governance.sh", *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )


def _render(out_dir: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    # Render ONLY the local wiring/affordance payload to out_dir — every live
    # section (secrets/ruleset/files) toggled off so the case is hermetic.
    return _run(
        "--repo",
        "three-cubes/sample",
        "--dry-run",
        "--no-secrets",
        "--no-ruleset",
        "--no-files",
        "--no-affordance",
        "--out-dir",
        str(out_dir),
        *extra,
    )


def _ci_job_names(ci_yaml: Path) -> list[str]:
    # Job-level `name:` is at 4-space indent; step names are deeper (and dashed).
    return [
        line[len("    name: ") :].strip().strip('"')
        for line in ci_yaml.read_text(encoding="utf-8").splitlines()
        if line.startswith("    name: ")
    ]


def _required_contexts(ruleset: Path) -> list[str]:
    data = json.loads(ruleset.read_text(encoding="utf-8"))
    for rule in data["rules"]:
        if rule.get("type") == "required_status_checks":
            return [c["context"] for c in rule["parameters"]["required_status_checks"]]
    return []


def test_help_exits_zero_and_documents_the_flags() -> None:
    result = _run("--help")
    assert result.returncode == 0
    out = result.stdout
    assert "bootstrap-repo-governance" in out
    for flag in (
        "--repo",
        "--dry-run",
        "--no-secrets",
        "--no-ruleset",
        "--no-files",
        "--no-affordance",
    ):
        assert flag in out, f"help text omits {flag}"


def test_missing_repo_is_an_actionable_error() -> None:
    result = _run()  # no --repo
    assert result.returncode == 2
    assert "--repo" in result.stderr
    assert "fix:" in result.stderr


def test_unknown_flag_is_rejected() -> None:
    result = _run("--bogus")
    assert result.returncode == 2
    assert "unknown flag" in result.stderr


def test_dry_run_covers_the_affordance_payload() -> None:
    # The extended payload (SGO-164): rendered skeletons + sonar-sqaa hook +
    # idempotent settings.json jq-merge + safe-commit/preflight — all named in
    # the --dry-run output. Live sections are toggled off so this stays hermetic.
    result = _run(
        "--repo", "three-cubes/sample", "--dry-run",
        "--no-secrets", "--no-ruleset", "--no-files",
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout

    # Section header present.
    assert "affordance + harness payload" in out

    # All six rendered skeletons named.
    for skel in ("CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md", "ETHOS.md", "RESOLVER.md", "SCORECARD.md"):
        assert skel in out, f"affordance payload omits {skel}"

    # The hook + the idempotent settings.json merge.
    assert "sonar-sqaa" in out
    assert "PostToolUse" in out
    assert "unique" in out, "settings.json merge must be idempotent (jq unique), not an append"

    # The harness scripts.
    assert "scripts/safe-commit.sh" in out
    assert "scripts/preflight.sh" in out

    # Placeholders resolved from --repo at render time (no unrendered token, and
    # the repo slug appears in the rendered instructions).
    assert "{{REPO}}" not in out, "an affordance skeleton rendered with an unresolved {{REPO}} token"
    assert "three-cubes/sample" in out


def test_no_affordance_toggle_suppresses_the_payload() -> None:
    result = _run(
        "--repo", "three-cubes/sample", "--dry-run", "--no-affordance",
        "--no-secrets", "--no-ruleset", "--no-files",
    )
    assert result.returncode == 0, result.stderr
    assert "affordance + harness payload" not in result.stdout


def test_dry_run_governance_files_install_gitignore_template() -> None:
    result = _run(
        "--repo", "three-cubes/sample", "--dry-run",
        "--no-secrets", "--no-ruleset", "--no-affordance",
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout

    assert "contents/governance/gitignore" in out
    assert "> .gitignore" in out
    assert ".DS_Store" in (REPO_ROOT / "governance/gitignore").read_text(encoding="utf-8")


# ── quality-gate wiring (the FULL-baseline extension) ────────────────────────


def test_help_lists_the_quality_gate_wiring_flags() -> None:
    result = _run("--help")
    assert result.returncode == 0
    out = result.stdout
    for flag in (
        "--fitness-tag",
        "--pipelines-tag",
        "--sonar",
        "--no-sonar",
        "--with-release",
        "--out-dir",
        "--verify",
        "--verify-only",
        "--no-wiring",
    ):
        assert flag in out, f"help text omits {flag}"


def test_wiring_render_resolves_every_token(tmp_path: Path) -> None:
    out_dir = tmp_path / "wire"
    result = _render(out_dir)
    assert result.returncode == 0, result.stderr

    # Every rendered wiring file carries ZERO unresolved {{TOKEN}} placeholders
    # (GHA ${{ }} expressions must survive — they are not template tokens).
    for rel in (
        "pyproject.tc_fitness.toml",
        "Makefile",
        "scripts/checks/_core_catalogue.py",
        ".github/workflows/ci.yml",
        ".github/workflows/auto-merge.yml",
        "sonar-project.properties",
    ):
        text = (out_dir / rel).read_text(encoding="utf-8")
        leftovers = TEMPLATE_TOKEN_RE.findall(text)
        assert not leftovers, f"{rel} left unresolved template tokens: {leftovers}"

    # The engine pin + the CORE bindings landed in the pyproject fragment.
    pyproject = (out_dir / "pyproject.tc_fitness.toml").read_text(encoding="utf-8")
    assert "three-cubes-fitness @ git+" in pyproject
    for binding in (
        "no_llm_attribution",
        "canonical_commit_identity",
        "engine_version_floor",
        "harness_canon_reference",
        "ci_consumes_shared_gate",
    ):
        assert f"core_checks.{binding}" in pyproject, f"pyproject omits CORE binding {binding}"


def test_wiring_ci_emits_every_required_ruleset_context(tmp_path: Path) -> None:
    # The gap this whole extension closes: the ruleset must never require a
    # context nothing emits. Every required context is a ci.yml job name (or an
    # app-external check).
    out_dir = tmp_path / "wire"
    assert _render(out_dir, "--verify").returncode == 0

    names = set(_ci_job_names(out_dir / ".github/workflows/ci.yml"))
    contexts = _required_contexts(out_dir / ".github/rulesets/main.json")
    assert "Quality gate" in contexts and "no-attribution" in contexts
    for ctx in contexts:
        assert ctx in names or ctx in EXTERNAL_CONTEXTS, (
            f"ruleset requires '{ctx}' but ci.yml emits no job of that name"
        )


def test_verify_passes_on_a_clean_render(tmp_path: Path) -> None:
    result = _render(tmp_path / "wire", "--verify")
    assert result.returncode == 0, result.stderr
    assert "verify: PASS" in result.stdout


def test_verify_catches_a_context_mismatch(tmp_path: Path) -> None:
    # Render clean, then swap the ruleset to require a context ci.yml never emits
    # (`CI gate` — the classic drift). --verify-only must FAIL, actionably.
    out_dir = tmp_path / "wire"
    assert _render(out_dir).returncode == 0

    ruleset = out_dir / ".github/rulesets/main.json"
    data = json.loads(ruleset.read_text(encoding="utf-8"))
    for rule in data["rules"]:
        if rule.get("type") == "required_status_checks":
            rule["parameters"]["required_status_checks"] = [{"context": "CI gate"}]
    ruleset.write_text(json.dumps(data, indent=2), encoding="utf-8")

    result = _run("--repo", "three-cubes/sample", "--verify-only", "--out-dir", str(out_dir))
    assert result.returncode != 0, "verify must fail when a required context has no emitting job"
    assert "CI gate" in result.stderr
    assert "FAIL" in result.stderr


def test_no_sonar_trims_the_sonar_contexts_and_jobs(tmp_path: Path) -> None:
    out_dir = tmp_path / "wire"
    assert _render(out_dir, "--no-sonar", "--verify").returncode == 0

    contexts = _required_contexts(out_dir / ".github/rulesets/main.json")
    assert not any("SonarCloud" in c for c in contexts), "SonarCloud contexts must be trimmed"
    assert set(contexts) == {"Quality gate", "no-attribution"}

    names = _ci_job_names(out_dir / ".github/workflows/ci.yml")
    assert "SonarCloud scan" not in names, "ci.yml must not emit a Sonar job under --no-sonar"
    assert not (out_dir / "sonar-project.properties").exists()


def test_no_wiring_toggle_suppresses_the_wiring_section() -> None:
    result = _run(
        "--repo", "three-cubes/sample", "--dry-run", "--no-wiring",
        "--no-secrets", "--no-ruleset", "--no-files", "--no-affordance",
    )
    assert result.returncode == 0, result.stderr
    assert "quality-gate wiring" not in result.stdout
