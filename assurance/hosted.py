"""Select exact changed adapters and retain real GitHub workflow-call evidence."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import yaml
from github_evidence import archive_member, download, download_log, validate_mutation
from protected_evidence import validate_protected
from receipt import ReceiptError, digest, read, validate, write


def command(root, *args):
    return subprocess.run(args, cwd=root, text=True, capture_output=True, check=True).stdout


def git(root, *args):
    return command(root, "git", *args).strip()


def select(root, base, head, *, complete=False, candidate_head=None):
    candidate_head = candidate_head or head
    for sha in (base, head, candidate_head):
        if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
            raise ReceiptError("selection requires exact 40-hex commit identities")
        git(root, "cat-file", "-e", f"{sha}^{{commit}}")
    if candidate_head != head:
        parents = git(root, "show", "-s", "--format=%P", head).split()
        if parents != [base, candidate_head]:
            raise ReceiptError("tested PR merge does not bind base and candidate head")
    data = yaml.safe_load(git(root, "show", f"{head}:assurance/surfaces.yaml"))
    cases = yaml.safe_load(git(root, "show", f"{head}:assurance/hosted-cases.yaml"))["cases"]
    declared_cases = [
        row["hosted"]["case"] for row in data["surfaces"] if row["hosted"]["boundary"] == "safe-hosted"
    ]
    if len(set(declared_cases)) != len(declared_cases) or set(declared_cases) != set(cases):
        raise ReceiptError("missing, duplicate or orphan executable case")
    changed = git(root, "diff", "--name-only", "--no-renames", base, head).splitlines()
    paths = set(git(root, "ls-tree", "-r", "--name-only", head).splitlines())
    safe, protected, selected = [], [], []
    ids = set()
    for row in data["surfaces"]:
        if row["id"] in ids:
            raise ReceiptError("duplicate surface")
        ids.add(row["id"])
        if row["path"] not in paths:
            raise ReceiptError(f"missing surface: {row['path']}")
        hosted = row["hosted"]
        boundary = hosted["boundary"]
        if boundary not in {
            "safe-hosted",
            "protected-live",
            "structural-example",
            "assurance-harness",
        }:
            raise ReceiptError("unclassified surface")
        if boundary == "safe-hosted" and not hosted["case"]:
            raise ReceiptError(f"missing executable case: {row['id']}")
        if boundary == "protected-live" and not hosted["release_probe"]:
            raise ReceiptError(f"missing approved release probe: {row['id']}")
        affected = complete or any(
            path == row["path"]
            or any(fnmatch.fnmatchcase(path, pattern) for pattern in hosted["dependencies"])
            for path in changed
        )
        if not affected or boundary in {"structural-example", "assurance-harness"}:
            continue
        selected.append(row)
        (safe if boundary == "safe-hosted" else protected).append(
            hosted["case"] if boundary == "safe-hosted" else row["id"]
        )
    return {
        "base": base,
        "head": head,
        "candidate_head": candidate_head,
        "complete": complete,
        "changed": changed,
        "safe": safe,
        "protected": protected,
        "surfaces": selected,
    }


def plan(
    root,
    base,
    head,
    destination,
    complete=False,
    *,
    candidate_head=None,
    execution_environment: Mapping[str, str] | None = None,
):
    execution_environment = os.environ if execution_environment is None else execution_environment
    selection = select(root, base, head, complete=complete, candidate_head=candidate_head)
    if git(root, "rev-parse", "HEAD") != head:
        raise ReceiptError("checkout is not the selected exact candidate")
    if (
        execution_environment.get("GITHUB_ACTIONS") == "true"
        and execution_environment.get("GITHUB_SHA") != head
    ):
        raise ReceiptError("tested commit does not match the Actions event")
    selection.update(
        execution_id=str(uuid.uuid4()),
        workflow_run_id=execution_environment.get("GITHUB_RUN_ID"),
        attempt=int(execution_environment.get("GITHUB_RUN_ATTEMPT", "1")),
        started_at=datetime.now(UTC).isoformat(),
        repository=execution_environment.get("GITHUB_REPOSITORY", "fixtures/local"),
    )
    selection["required_probes"] = [
        {
            "surface_id": row["id"],
            "case_id": row["id"] + ":status",
            "candidate_commit": head,
            "operation": "status",
            "external_mutation": False,
            "boundary": row["path"],
            "probe_contract": row["hosted"]["release_probe"],
            "authority": "consumer-protected-environment",
            "runtime_receipt_required": True,
            "release_authority_policy_required": True,
            "required_policy_fields": [
                "contract",
                "environment",
                "target",
                "image_digest",
                "host_id",
                "runtime_user",
                "deployment_id",
                "configuration_identity",
                "run_id",
                "attempt_id",
                "required_checks",
                "max_age_seconds",
                "repository",
                "workflow_path",
                "actor_id",
                "artifact_name",
                "artifact_digest",
            ],
            "expectation": expectation_for(root, selection, row, {}),
        }
        for row in selection["surfaces"]
        if row["hosted"]["boundary"] == "protected-live"
    ]
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "selection.json").write_text(json.dumps(selection, indent=2) + "\n")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            stream.write("safe=" + json.dumps(selection["safe"]) + "\n")
            stream.write(
                "actions="
                + json.dumps([case for case in selection["safe"] if case.startswith("action-")])
                + "\n"
            )
    return selection


def expectation_for(root, selection, row, case):
    protected = row["hosted"]["boundary"] == "protected-live"
    identity = row["id"] + ":status" if protected else row["hosted"]["case"]
    head = selection["head"]
    inputs = {
        "candidate_tree": git(root, "rev-parse", f"{head}^{{tree}}"),
        "surface": row,
        "case": case,
    }
    return {
        "subject": "pipeline-adapter",
        "case_id": identity,
        "expected": "pass",
        "candidate": {
            "fitness_digest": None,
            "pipeline_commit": head,
            "pipeline_head_commit": selection["candidate_head"],
            "pipeline_package_digest": None,
            "pipeline_image_digest": None,
        },
        "consumer": {
            "repository": selection["repository"],
            "commit": head,
            "sdlc_lock_digest": None,
        },
        "execution": {
            "execution_id": str(uuid.uuid5(uuid.UUID(selection["execution_id"]), identity)),
            "workflow_run_id": None if protected else selection["workflow_run_id"],
            "attempt": selection["attempt"],
            "command": ["status", row["id"]] if protected else ["workflow_call", row["path"]],
            "tasks": [
                {
                    "id": identity,
                    "input_digest": digest(json.dumps(inputs, sort_keys=True).encode()),
                }
            ],
            "executor": "live-boundary" if protected else "github-actions",
        },
        "output_ids": ["execution-log", "runtime-receipt", "status-result"]
        if protected
        else ["execution-log", "github-terminal"]
        + (["native-artifact", "mutation-result"] if case.get("native_artifact") else []),
        "finding": None,
        "not_before": selection["started_at"],
    }


def validate_jobs(jobs, expected_steps, run_id, attempt, head):
    if not jobs or len({job["id"] for job in jobs}) != len(jobs):
        raise ReceiptError("missing or duplicate terminal jobs")
    executed = []
    for job in jobs:
        if (
            job.get("run_id") != int(run_id)
            or job.get("run_attempt") != attempt
            or job.get("head_sha") != head
        ):
            raise ReceiptError("wrong GitHub run/attempt/candidate")
        if job.get("status") != "completed" or job.get("conclusion") != "success":
            raise ReceiptError("missing, skipped or unsuccessful required job")
        executed.extend(
            step["name"]
            for step in job.get("steps", [])
            if step.get("status") == "completed" and step.get("conclusion") == "success"
        )
    for step in expected_steps:
        if executed.count(step) != 1:
            raise ReceiptError(f"missing, skipped or duplicate required step: {step}")


def validate_run(run, selection):
    if (
        run["head_sha"] != selection["candidate_head"]
        or run["status"] != "completed"
        or run["conclusion"] != "success"
        or run["id"] != int(selection["workflow_run_id"])
        or run["run_attempt"] != selection["attempt"]
    ):
        raise ReceiptError("GitHub has no successful exact-candidate execution")


def download_native(root, selection, name, archive):
    repo, run_id = (
        selection["repository"],
        selection["workflow_run_id"],
    )
    pages = json.loads(
        command(
            root,
            "gh",
            "api",
            "--paginate",
            "--slurp",
            f"repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100",
        )
    )
    artifacts = [a for page in pages for a in page["artifacts"] if a["name"] == name and not a["expired"]]
    if len(artifacts) != 1:
        raise ReceiptError("missing or duplicate native artifact")
    artifact = artifacts[0]
    if artifact["workflow_run"]["head_sha"] != selection["candidate_head"]:
        raise ReceiptError("native artifact has wrong candidate")
    data = download(
        f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact['id']}/zip",
        archive,
    )
    if artifact.get("digest") != digest(data):
        raise ReceiptError("native artifact digest does not match GitHub")
    return data


def collect_mutation(root, selection, directory, *, verify=False):
    name = f"assurance-mutation-{selection['workflow_run_id']}-{selection['attempt']}"
    archive = directory / ("native.verify.zip" if verify else "native.zip")
    data = download_native(root, selection, name, archive)
    result = archive_member(archive, "mutation.json")
    if verify:
        if (
            data != (directory / "native.zip").read_bytes()
            or result != (directory / "mutation.json").read_bytes()
        ):
            raise ReceiptError("retained native mutation evidence does not match GitHub")
    else:
        (directory / "mutation.json").write_bytes(result)
    validate_mutation(directory / "mutation.json")


def collect(root, directory):
    selection = read(directory / "selection.json")
    run_id, attempt, head = (
        selection["workflow_run_id"],
        selection["attempt"],
        selection["head"],
    )
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_RUN_ID") != run_id
        or os.environ.get("GITHUB_RUN_ATTEMPT") != str(attempt)
    ):
        raise ReceiptError("collection requires the selected real GitHub run/attempt")
    repository = os.environ["GITHUB_REPOSITORY"]
    pages = command(
        root,
        "gh",
        "api",
        "--paginate",
        "--slurp",
        f"repos/{repository}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100",
    )
    all_jobs = [job for page in json.loads(pages) for job in page["jobs"]]
    cases = yaml.safe_load((root / "assurance/hosted-cases.yaml").read_text())["cases"]
    receipts = []
    failures = []
    for row in selection["surfaces"]:
        if row["hosted"]["boundary"] != "safe-hosted":
            continue
        case_id = row["hosted"]["case"]
        case = cases[case_id]
        case_dir = directory / case_id
        case_dir.mkdir(exist_ok=False)
        try:
            jobs = [
                job
                for job in all_jobs
                if case_id in job["name"].split(" / ") and job["name"].rsplit(" / ", 1)[-1] in case["jobs"]
            ]
            (case_dir / "terminal.json").write_text(json.dumps(jobs, indent=2) + "\n")
            logs = []
            for job in jobs:
                logs.append(
                    download_log(
                        f"https://api.github.com/repos/{repository}/actions/jobs/{job['id']}/logs",
                        case_dir / f"job-{job['id']}",
                    )
                )
            (case_dir / "execution.log").write_text("\n".join(logs))
            validate_jobs(jobs, case["steps"], run_id, attempt, selection["candidate_head"])
            if sorted(job["name"].rsplit(" / ", 1)[-1] for job in jobs) != sorted(case["jobs"]):
                raise ReceiptError("missing or duplicate required case job")
            expectation = expectation_for(root, selection, row, case)
            native_outputs = []
            if case.get("native_artifact"):
                collect_mutation(root, selection, case_dir)
                native_outputs = [
                    {"id": "native-artifact", "path": "native.zip"},
                    {"id": "mutation-result", "path": "mutation.json"},
                ]
            observation = {
                "actual": "pass",
                "started_at": min(job["started_at"] for job in jobs),
                "finished_at": max(job["completed_at"] for job in jobs),
                "exit_code": 0,
                "outputs": [
                    {"id": "execution-log", "path": "execution.log"},
                    {"id": "github-terminal", "path": "terminal.json"},
                ]
                + native_outputs,
                "finding": None,
            }
            (case_dir / "expectation.json").write_text(json.dumps(expectation, indent=2) + "\n")
            receipt = write(expectation, observation, case_dir, case_dir / "receipt.json")
            validate(receipt, expectation, case_dir)
            receipts.append(
                {
                    "case_id": case_id,
                    "digest": digest((case_dir / "receipt.json").read_bytes()),
                    "actual": receipt["actual"],
                }
            )
        except (ReceiptError, subprocess.CalledProcessError, OSError) as error:
            (case_dir / "failure.txt").write_text(str(error) + "\n")
            (case_dir / "failure.json").write_text(
                json.dumps(
                    {
                        "case_id": case_id,
                        "expected": "pass",
                        "actual": "error",
                        "candidate_commit": head,
                        "workflow_run_id": run_id,
                        "attempt": attempt,
                        "external_mutation": False,
                        "diagnostic": str(error)[-4000:],
                    },
                    indent=2,
                )
                + "\n"
            )
            if (
                jobs
                and all(job.get("completed_at") for job in jobs)
                and (case_dir / "execution.log").is_file()
                and (case_dir / "execution.log").stat().st_size
                and not (case_dir / "receipt.json").exists()
            ):
                expectation = expectation_for(root, selection, row, case)
                observation = {
                    "actual": "error",
                    "started_at": min(job["started_at"] for job in jobs),
                    "finished_at": max(job["completed_at"] for job in jobs),
                    "exit_code": 1,
                    "outputs": [
                        {"id": "execution-log", "path": "execution.log"},
                        {"id": "github-terminal", "path": "terminal.json"},
                    ],
                    "finding": None,
                }
                (case_dir / "expectation.json").write_text(json.dumps(expectation, indent=2) + "\n")
                try:
                    write(expectation, observation, case_dir, case_dir / "receipt.json")
                except ReceiptError:
                    # The persisted failed receipt must not pass validation.
                    pass
            failures.append(case_id)
    (directory / "index.json").write_text(
        json.dumps(
            {
                "receipts": receipts,
                "failed": failures,
                "protected_release_probes": selection["protected"],
            },
            indent=2,
        )
        + "\n"
    )
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            for receipt in receipts:
                stream.write(f"- `{receipt['case_id']}`: {receipt['actual']} `{receipt['digest']}`\n")
            for case_id in failures:
                stream.write(f"- `{case_id}`: FAIL; retained diagnostics\n")
    if failures:
        raise ReceiptError(f"hosted cases failed: {failures}")


def admit(root, directory, protected_policy=None):
    """Consume exact retained evidence; never execute a protected operation."""
    selection = read(directory / "selection.json")
    current = select(
        root,
        selection["base"],
        selection["head"],
        complete=selection["complete"],
        candidate_head=selection["candidate_head"],
    )
    for key in ("safe", "protected", "surfaces"):
        if current[key] != selection[key]:
            raise ReceiptError("selection does not bind the exact candidate inventory")
    required = set(selection["safe"]) | {identity + ":status" for identity in selection["protected"]}
    receipts = {}
    executions = set()
    for path in directory.rglob("receipt.json"):
        receipt = read(path)
        identity = receipt["case_id"]
        if identity in receipts or receipt["execution"]["execution_id"] in executions:
            raise ReceiptError("duplicate receipt or execution identity")
        executions.add(receipt["execution"]["execution_id"])
        receipts[identity] = (path, receipt)
    if required - receipts.keys():
        raise ReceiptError(f"missing required receipt: {sorted(required - receipts.keys())}")
    if receipts.keys() - required:
        raise ReceiptError("unexpected receipt outside selected cases")
    cases = (
        yaml.safe_load(git(root, "show", f"{selection['head']}:assurance/hosted-cases.yaml"))["cases"]
        if receipts
        else {}
    )
    hosted_jobs = {}
    if selection["safe"]:
        if not selection["workflow_run_id"]:
            raise ReceiptError("local plans cannot satisfy hosted release admission")
        repo, run_id, attempt = (
            selection["repository"],
            selection["workflow_run_id"],
            selection["attempt"],
        )
        run = json.loads(
            command(
                root,
                "gh",
                "api",
                f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}",
            )
        )
        validate_run(run, selection)
        plan_archive = directory / "selection-provenance.zip"
        download_native(root, selection, f"assurance-plan-{run_id}-{attempt}", plan_archive)
        if archive_member(plan_archive, "selection.json") != (directory / "selection.json").read_bytes():
            raise ReceiptError("selection identities differ from the actual GitHub plan artifact")
        pages = json.loads(
            command(
                root,
                "gh",
                "api",
                "--paginate",
                "--slurp",
                f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100",
            )
        )
        hosted_jobs = {job["id"]: job for page in pages for job in page["jobs"]}
    for identity, (path, receipt) in receipts.items():
        row = next(
            row
            for row in current["surfaces"]
            if row["hosted"]["case"] == identity or row["id"] + ":status" == identity
        )
        case = cases[identity] if identity in selection["safe"] else {}
        expectation = expectation_for(root, selection, row, case)
        validate(receipt, expectation, path.parent)
        execution = receipt["execution"]
        if (
            receipt["candidate"]["pipeline_commit"] != selection["head"]
            or execution["attempt"] != selection["attempt"]
        ):
            raise ReceiptError("wrong candidate or attempt at admission")
        if execution["execution_id"] != str(uuid.uuid5(uuid.UUID(selection["execution_id"]), identity)):
            raise ReceiptError("receipt was not produced for this selection")
        if identity in selection["safe"]:
            if (
                execution["executor"] != "github-actions"
                or execution["workflow_run_id"] != selection["workflow_run_id"]
            ):
                raise ReceiptError("local or wrong-run evidence cannot satisfy hosted admission")
            terminal = next(
                item for item in receipt["evidence"]["outputs"] if item["id"] == "github-terminal"
            )
            validate_jobs(
                read(path.parent / terminal["path"]),
                case["steps"],
                selection["workflow_run_id"],
                selection["attempt"],
                selection["candidate_head"],
            )
            for job in read(path.parent / terminal["path"]):
                actual_job = hosted_jobs.get(job["id"])
                if actual_job is None or any(
                    job.get(key) != actual_job.get(key)
                    for key in (
                        "run_id",
                        "run_attempt",
                        "head_sha",
                        "name",
                        "status",
                        "conclusion",
                        "steps",
                    )
                ):
                    raise ReceiptError("retained terminal evidence does not match GitHub")
            if case.get("native_artifact"):
                collect_mutation(root, selection, path.parent, verify=True)
        else:
            if execution["executor"] != "live-boundary" or not receipt["evidence"]["runtime_receipt_digest"]:
                raise ReceiptError("protected admission requires a bound runtime receipt")
            if execution["command"] != ["status", identity.removesuffix(":status")]:
                raise ReceiptError("protected admission permits only the declared status operation")
            validate_protected(
                root,
                path.parent,
                receipt,
                selection,
                protected_policy.get(identity) if protected_policy else None,
                lambda root, endpoint: json.loads(command(root, "gh", "api", endpoint)),
            )
    index = [
        {
            "case_id": identity,
            "digest": digest(path.read_bytes()),
            "actual": receipt["actual"],
        }
        for identity, (path, receipt) in sorted(receipts.items())
    ]
    (directory / "admission.json").write_text(
        json.dumps(
            {
                "candidate_commit": selection["head"],
                "candidate_head": selection["candidate_head"],
                "protected_policy_digest": digest(json.dumps(protected_policy, sort_keys=True).encode())
                if protected_policy
                else None,
                "receipts": index,
            },
            indent=2,
        )
        + "\n"
    )
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["select", "plan", "collect", "admit"])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--candidate-head")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--complete", action="store_true")
    parser.add_argument(
        "--protected-policy",
        type=Path,
        help="Release-authority policy supplied out of band, keyed by case id",
    )
    args = parser.parse_args()
    try:
        if args.operation == "select":
            print(
                json.dumps(
                    select(
                        args.root,
                        args.base,
                        args.head,
                        complete=args.complete,
                        candidate_head=args.candidate_head,
                    )
                )
            )
        elif args.operation == "plan":
            plan(
                args.root,
                args.base,
                args.head,
                args.output,
                args.complete or os.environ.get("COMPLETE") == "true",
                candidate_head=args.candidate_head,
            )
        elif args.operation == "collect":
            collect(args.root, args.output)
        else:
            admit(
                args.root,
                args.output,
                read(args.protected_policy) if args.protected_policy else None,
            )
    except (
        ReceiptError,
        subprocess.CalledProcessError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        print(f"assurance: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
