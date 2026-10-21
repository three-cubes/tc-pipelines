"""Release-only verification using the canonical runtime CLI and approved provenance.

The release operator supplies policy out of band; receipt contents cannot nominate
their own host, user, deployment, contract, authorised actor or producer workflow.
No protected operation is executed here.
"""

import json
import subprocess
from pathlib import Path

from github_evidence import archive_member, download
from receipt import ReceiptError, digest, output_path, read

# Released v0.16.1 adds the public runtime verifier; do not fork its validator or
# change the repository's independently pinned compatibility-engine baseline.
RUNTIME_VERIFIER = (
    "git+https://github.com/three-cubes/tc-fitness.git@8d39d7e2f5b5d9daae778ec8195e344b0e7cc396"
)


def verify_runtime(directory, evidence, policy, head):
    if not policy["required_checks"] or policy["max_age_seconds"] <= 0:
        raise ReceiptError("protected policy must require fresh runtime checks")
    output = directory / "canonical-verification.json"
    args = [
        "uvx",
        "--from",
        RUNTIME_VERIFIER,
        "tc-fitness-runtime-contract",
        "verify-evidence",
        "--contract",
        str(Path(policy["contract"]).resolve()),
        "--environment",
        policy["environment"],
        "--target",
        policy["target"],
        "--evidence",
        str(evidence),
        "--output",
        str(output),
        "--expected-source-sha",
        head,
        "--max-age-seconds",
        str(policy["max_age_seconds"]),
    ]
    for key in (
        "image_digest",
        "host_id",
        "runtime_user",
        "deployment_id",
        "configuration_identity",
        "run_id",
        "attempt_id",
    ):
        args.extend(["--expected-" + key.replace("_", "-"), str(policy[key])])
    for check in policy["required_checks"]:
        args.extend(["--required-check", check])
    result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=120)
    (directory / "canonical-verifier.stdout").write_text(result.stdout)
    (directory / "canonical-verifier.stderr").write_text(result.stderr)
    if result.returncode or read(output) != {"valid": True, "findings": []}:
        raise ReceiptError("canonical protected runtime verification failed")


def validate_provenance(run, selection, policy):
    """The producer run is the authorised one, at the commit the release operator approved.

    The producer may be a consumer repository, so its run's ``head_sha`` is that repository's
    commit, never ``selection["candidate_head"]`` (the tc-pipelines candidate). The pipeline
    candidate stays bound where the runtime receipt is verified (``--expected-source-sha``).
    """
    repo, run_id, attempt = policy["repository"], policy["run_id"], policy["attempt_id"]
    producer = policy.get("producer_commit")
    if not isinstance(producer, str) or len(producer) != 40 or set(producer) - set("0123456789abcdef"):
        raise ReceiptError("protected policy must name the approved producer commit")
    if (
        run["head_sha"] != producer
        or run["status"] != "completed"
        or run["conclusion"] != "success"
        or run["path"] != policy["workflow_path"]
        or run["event"] != "workflow_dispatch"
        or run["actor"]["id"] != policy["actor_id"]
        or run["run_attempt"] != attempt
        or run["id"] != run_id
        or run["repository"]["full_name"] != repo
    ):
        raise ReceiptError("protected evidence lacks authorised successful provenance")


def run_artifacts(root, repo, run_id, api):
    """Every artifact of the run: the endpoint returns at most 100 per page."""
    found, page = [], 1
    while True:
        response = api(root, f"repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100&page={page}")
        batch = response["artifacts"]
        found.extend(batch)
        if not batch or len(found) >= response["total_count"]:
            return found
        page += 1


def attempt_window(root, repo, run_id, attempt, api):
    """First job start and last job completion of one run attempt, from the attempt's own jobs."""
    started, completed, page = [], [], 1
    while True:
        response = api(
            root, f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100&page={page}"
        )
        jobs = response["jobs"]
        started.extend(job["started_at"] for job in jobs if job.get("started_at"))
        completed.extend(job["completed_at"] for job in jobs if job.get("completed_at"))
        if not jobs or page * 100 >= response["total_count"]:
            break
        page += 1
    if not started or not completed:
        raise ReceiptError("protected run attempt has no executed jobs")
    return min(started), max(completed)


def attempt_artifacts(root, repo, run_id, attempt, api):
    """The run's artifacts that the selected attempt created.

    The artifacts endpoint is scoped to the run and its metadata names no attempt, so a re-run leaves
    earlier attempts' artifacts beside the approved one. Attempts do not overlap, so an artifact
    belongs to the attempt whose job window contains its ``created_at`` (UTC timestamps compare as text).
    """
    start, end = attempt_window(root, repo, run_id, attempt, api)
    return [
        artifact
        for artifact in run_artifacts(root, repo, run_id, api)
        if start <= str(artifact.get("created_at") or "") <= end
    ]


def verify_provenance(root, directory, receipt, selection, policy, api):
    repo, run_id, attempt = policy["repository"], policy["run_id"], policy["attempt_id"]
    run = api(root, f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}")
    validate_provenance(run, selection, policy)
    artifacts = attempt_artifacts(root, repo, run_id, attempt, api)
    selected = [a for a in artifacts if a["name"] == policy["artifact_name"] and not a["expired"]]
    if len(selected) != 1 or selected[0]["digest"] != policy["artifact_digest"]:
        raise ReceiptError("protected artifact is missing or not authorised by release policy")
    archive = directory / "protected-provenance.zip"
    data = download(
        f"https://api.github.com/repos/{repo}/actions/artifacts/{selected[0]['id']}/zip",
        archive,
    )
    if digest(data) != policy["artifact_digest"]:
        raise ReceiptError("protected artifact digest mismatch")
    for row in receipt["evidence"]["outputs"]:
        member = {
            "runtime-receipt": "runtime-evidence.json",
            "status-result": "status.json",
            "execution-log": "execution.log",
        }[row["id"]]
        if digest(archive_member(archive, member)) != row["digest"]:
            raise ReceiptError("protected evidence differs from authorised producer artifact")
    (directory / "protected-provenance.json").write_text(
        json.dumps({"run": run, "artifact": selected[0]}, indent=2)
    )


def validate_protected(root, directory, receipt, selection, policy, api):
    if policy is None:
        raise ReceiptError("protected admission requires explicit release-authority policy")
    outputs = {row["id"]: output_path(directory, row["path"]) for row in receipt["evidence"]["outputs"]}
    verify_runtime(directory, outputs["runtime-receipt"], policy, selection["head"])
    if read(outputs["status-result"]) != {"valid": True, "findings": []}:
        raise ReceiptError("protected status result is not the canonical terminal success")
    verify_provenance(root, directory, receipt, selection, policy, api)
