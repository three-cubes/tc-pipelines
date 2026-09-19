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
RUNTIME_VERIFIER = "git+https://github.com/three-cubes/tc-fitness.git@8d39d7e2f5b5d9daae778ec8195e344b0e7cc396"


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
    result = subprocess.run(
        args, capture_output=True, text=True, check=False, timeout=120
    )
    (directory / "canonical-verifier.stdout").write_text(result.stdout)
    (directory / "canonical-verifier.stderr").write_text(result.stderr)
    if result.returncode or read(output) != {"valid": True, "findings": []}:
        raise ReceiptError("canonical protected runtime verification failed")


def validate_provenance(run, selection, policy):
    repo, run_id, attempt = policy["repository"], policy["run_id"], policy["attempt_id"]
    if (
        run["head_sha"] != selection["candidate_head"]
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


def verify_provenance(root, directory, receipt, selection, policy, api):
    repo, run_id, attempt = policy["repository"], policy["run_id"], policy["attempt_id"]
    run = api(root, f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}")
    validate_provenance(run, selection, policy)
    artifacts = api(root, f"repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100")[
        "artifacts"
    ]
    selected = [
        a
        for a in artifacts
        if a["name"] == policy["artifact_name"] and not a["expired"]
    ]
    if len(selected) != 1 or selected[0]["digest"] != policy["artifact_digest"]:
        raise ReceiptError(
            "protected artifact is missing or not authorised by release policy"
        )
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
            raise ReceiptError(
                "protected evidence differs from authorised producer artifact"
            )
    (directory / "protected-provenance.json").write_text(
        json.dumps({"run": run, "artifact": selected[0]}, indent=2)
    )


def validate_protected(root, directory, receipt, selection, policy, api):
    if policy is None:
        raise ReceiptError(
            "protected admission requires explicit release-authority policy"
        )
    outputs = {
        row["id"]: output_path(directory, row["path"])
        for row in receipt["evidence"]["outputs"]
    }
    verify_runtime(directory, outputs["runtime-receipt"], policy, selection["head"])
    if read(outputs["status-result"]) != {"valid": True, "findings": []}:
        raise ReceiptError(
            "protected status result is not the canonical terminal success"
        )
    verify_provenance(root, directory, receipt, selection, policy, api)
