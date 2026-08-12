"""A self-reference must satisfy the contract of the copy it actually loads.

`three-cubes/tc-pipelines/...@<ref>` is fetched from github.com at that ref.
The working tree is not what runs, so a caller and the artefact it calls can
disagree while every file in the tree stays individually valid and every other
test here still passes: actionlint, yamllint and the tree-reading guards all
judge the copy that is not executed.

Both directions of that disagreement are silent. A composite handed an input it
does not declare at the loaded ref logs `Unexpected input(s)` and drops it, so a
consumer's secret-scan pattern set never reaches the gate and a detector that is
scanning nothing still reports green through the required status context. An
output a caller reads but that the loaded ref does not declare evaluates to the
empty string rather than erroring, so a deploy surfaces a blank snapshot
identifier and the rollback evidence its caller records is empty on every run.

A tag is resolved here the same way the runner resolves it, so a moving ref is
checked against what it points at rather than exempted. That is the case with
the most room to drift: the artefact in the tree gains an input or an output,
the caller starts using it, and the tag still points at a release that has
neither.

There is no exemption from the three contract assertions. Passing an input the
loaded copy drops, or reading an output it cannot produce, has no legitimate
form — the call is already behaving differently than it reads.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
ACTION_DIRS = (REPO_ROOT / "actions", REPO_ROOT / ".github" / "actions")

SELF_REFERENCE = re.compile(
    r"^three-cubes/tc-pipelines/"
    r"((?:\.github/)?actions/[^@\s]+|\.github/workflows/[^@\s]+\.ya?ml)@(\S+)$"
)
OUTPUT_READ = r"\.outputs\.([A-Za-z0-9_-]+)"

# "<file>:<label>" -> why this ref is legitimately unresolvable in a clone of
# this repo. It exempts the site from the resolvability floor only; the contract
# assertions below still run against every ref that does resolve.
DELIBERATE_UNRESOLVABLE_REF: dict[str, str] = {}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _triggers(document: dict):
    # `on:` parses as the boolean True under YAML 1.1, and its value may be a
    # mapping, a list or a bare string.
    triggers = document.get(True)
    if triggers is None:
        triggers = document.get("on")
    return triggers or {}


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _sources() -> list[Path]:
    paths = sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml"))
    for directory in ACTION_DIRS:
        paths.extend(sorted(directory.glob("*/action.yml")))
        paths.extend(sorted(directory.glob("*/action.yaml")))
    return sorted(paths)


def _scope_text(scope: dict) -> str:
    # Expressions are matched against the calling job (or the composite's own
    # `runs:`) rather than the whole file, so a step id reused in a second job
    # cannot be mistaken for a read of this call's outputs. The wide width keeps
    # a long `${{ ... }}` on one line.
    return yaml.safe_dump(scope, default_flow_style=False, width=10**6)


def _units(document: dict) -> list[tuple[str, dict, dict, bool]]:
    """(label, the calling job/step mapping, the scope that reads it, job-level).

    Walking the parsed document rather than the raw text is what keeps the
    `uses:` lines inside the actions' `description:` scalars — usage
    documentation, not call sites — out of the scan.
    """
    units: list[tuple[str, dict, dict, bool]] = []
    jobs = document.get("jobs") or {}
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        units.append((job_name, job, jobs, True))
        for index, step in enumerate(job.get("steps") or []):
            if isinstance(step, dict):
                label = str(step.get("id") or step.get("name") or index)
                units.append((f"{job_name}/{label}", step, job, False))
    runs = document.get("runs")
    if isinstance(runs, dict):
        for index, step in enumerate(runs.get("steps") or []):
            if isinstance(step, dict):
                label = str(step.get("id") or step.get("name") or index)
                units.append((f"runs/{label}", step, runs, False))
    return units


def _self_references() -> list[dict]:
    found = []
    for path in _sources():
        source = str(path.relative_to(REPO_ROOT))
        for label, unit, scope, is_job in _units(_load(path)):
            match = SELF_REFERENCE.match(str(unit.get("uses", "")).strip())
            if not match:
                continue
            ref = match.group(2)
            # Resolve the ref the way the runner does: a tag is whatever it
            # points at now, which is not necessarily the tree.
            probe = _git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
            commit = probe.stdout.strip() if probe.returncode == 0 else ""
            reader = label if is_job else str(unit.get("id") or "")
            found.append(
                {
                    "source": source,
                    "label": label,
                    "target": match.group(1),
                    "ref": ref,
                    "commit": commit,
                    "passed": unit.get("with") or {},
                    # How a later expression addresses this call's outputs. A
                    # step without an id publishes nothing addressable.
                    "reads": _scope_text(scope) if reader else "",
                    "context": ("needs" if is_job else "steps") + "." + reader,
                }
            )
    return found


SITES = _self_references()
IDS = [f"{site['source']}:{site['label']} -> {site['target']}" for site in SITES]

_CONTRACTS: dict[tuple[str, str], tuple[dict, dict] | None] = {}


def _contract(site: dict) -> tuple[dict, dict]:
    """(declared inputs, declared outputs) of the target at the loaded commit."""
    key = (site["commit"], site["target"])
    if key not in _CONTRACTS:
        target = site["target"]
        candidates = (
            [target]
            if target.endswith((".yml", ".yaml"))
            else [f"{target}/action.yml", f"{target}/action.yaml"]
        )
        blob = None
        for candidate in candidates:
            result = _git("show", f"{site['commit']}:{candidate}")
            if result.returncode == 0:
                blob = result.stdout
                break
        if blob is None:
            _CONTRACTS[key] = None
        else:
            document = yaml.safe_load(blob) or {}
            if target.endswith((".yml", ".yaml")):
                call = _triggers(document).get("workflow_call") or {}
                _CONTRACTS[key] = (call.get("inputs") or {}, call.get("outputs") or {})
            else:
                _CONTRACTS[key] = (
                    document.get("inputs") or {},
                    document.get("outputs") or {},
                )

    contract = _CONTRACTS[key]
    if contract is None:
        pytest.fail(
            f"{site['source']}: `{site['label']}` loads {site['target']}@"
            f"{site['ref']}, but that path does not exist at the commit the ref "
            f"resolves to ({site['commit'][:8]}). The run fails when it reaches "
            f"the step. fix: repin to a ref that contains {site['target']}, or "
            f"correct the path."
        )
    return contract


def test_the_scan_found_resolvable_self_references() -> None:
    """A scan matching nothing, or a clone resolving nothing, would pass below.

    Every contract assertion is per-site, so a clone too shallow to resolve the
    refs turns the whole file into a no-op. This is what fails instead.
    """
    assert len(SITES) >= 15, (
        f"only {len(SITES)} self-referencing `uses:` discovered — the pattern "
        f"or the file roots have drifted, so loaded-ref contracts are no longer "
        f"being checked. fix: reconcile SELF_REFERENCE and _sources() against "
        f"the `uses:` lines in the tree."
    )
    unresolved = sorted(
        f"{site['source']}:{site['label']} -> {site['ref']}"
        for site in SITES
        if not site["commit"]
        and f"{site['source']}:{site['label']}" not in DELIBERATE_UNRESOLVABLE_REF
    )
    assert not unresolved, (
        f"{len(unresolved)} of {len(SITES)} refs cannot be resolved in this "
        f"clone, so the contracts those calls load are unverifiable and the "
        f"assertions covering them do nothing: {unresolved}. fix: give the "
        f"checkout these tests run against `fetch-depth: 0`, which fetches the "
        f"tags and history a ref resolves through; if a ref is legitimately "
        f"outside this repo's history, name it in DELIBERATE_UNRESOLVABLE_REF "
        f"with the reason."
    )


@pytest.mark.parametrize("site", SITES, ids=IDS)
def test_call_passes_no_input_the_loaded_ref_rejects(site: dict) -> None:
    if not site["commit"]:
        pytest.skip("ref unresolvable; the resolvability assertion owns this")
    declared, _ = _contract(site)
    unknown = sorted(set(site["passed"]) - set(declared))
    assert not unknown, (
        f"{site['source']}: `{site['label']}` passes {unknown} to "
        f"{site['target']}@{site['ref']}, which does not declare it at the "
        f"commit that ref loads ({site['commit'][:8]}). A composite logs "
        f"`Unexpected input(s)` and drops the value, so the step runs with the "
        f"setting silently empty and still reports success; a reusable fails "
        f"the whole run as startup_failure. "
        f"fix: repin to a ref whose copy declares {unknown}, or stop passing it."
    )


@pytest.mark.parametrize("site", SITES, ids=IDS)
def test_call_passes_every_input_the_loaded_ref_requires(site: dict) -> None:
    if not site["commit"]:
        pytest.skip("ref unresolvable; the resolvability assertion owns this")
    declared, _ = _contract(site)
    required = {
        name
        for name, spec in declared.items()
        if isinstance(spec, dict) and spec.get("required") and "default" not in spec
    }
    missing = sorted(required - set(site["passed"]))
    assert not missing, (
        f"{site['source']}: `{site['label']}` omits {missing}, which "
        f"{site['target']}@{site['ref']} requires at the commit that ref loads "
        f"({site['commit'][:8]}). A composite only warns and substitutes an "
        f"empty string, so the step runs with different behaviour and still "
        f"reports success. "
        f"fix: pass the input, or repin to a ref that gives it a default."
    )


@pytest.mark.parametrize("site", SITES, ids=IDS)
def test_read_outputs_are_declared_at_the_loaded_ref(site: dict) -> None:
    if not site["commit"]:
        pytest.skip("ref unresolvable; the resolvability assertion owns this")
    _, declared = _contract(site)
    pattern = re.escape(site["context"]) + OUTPUT_READ
    read = set(re.findall(pattern, site["reads"]))
    undeclared = sorted(read - set(declared))
    assert not undeclared, (
        f"{site['source']}: `{site['label']}` reads {undeclared} from "
        f"{site['target']}@{site['ref']}, which declares {sorted(declared)} at "
        f"the commit that ref loads ({site['commit'][:8]}). An undeclared "
        f"output evaluates to the empty string with no error, so every value "
        f"this workflow publishes from it is blank on every run. "
        f"fix: repin to a ref that declares {undeclared}, or stop publishing a "
        f"value the loaded copy cannot produce."
    )


def test_every_deliberate_entry_names_an_unresolvable_call_site() -> None:
    """A stale exemption would drop a call site from the resolvability floor."""
    unresolvable = {
        f"{site['source']}:{site['label']}" for site in SITES if not site["commit"]
    }
    stale = sorted(set(DELIBERATE_UNRESOLVABLE_REF) - unresolvable)
    assert not stale, (
        f"DELIBERATE_UNRESOLVABLE_REF names call sites that are gone or whose "
        f"ref now resolves: {stale}. fix: remove them, or the exemption "
        f"outlives its cause and hides the next unresolvable ref."
    )
