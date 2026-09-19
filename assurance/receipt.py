"""Exact-candidate assurance receipts. Hosted writers require real Actions context."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


class ReceiptError(ValueError):
    """Evidence does not establish the declared assurance case."""


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ReceiptError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(Path(path).read_text(), object_pairs_hook=unique)


def output_path(root, path):
    value = Path(path)
    target = (root / value).resolve()
    if value.is_absolute() or ".." in value.parts or not target.is_relative_to(root.resolve()):
        raise ReceiptError(f"unsafe output path: {path}")
    if not target.is_file() or target.stat().st_size == 0:
        raise ReceiptError(f"missing or empty output: {path}")
    return target


def validate(receipt, expectation, root):
    schema = read(Path(__file__).with_name("receipt.schema.json"))
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(receipt))
    if errors:
        raise ReceiptError(f"schema: {errors[0].message}")
    for key in ("subject", "case_id", "expected", "candidate", "consumer"):
        if receipt[key] != expectation[key]:
            raise ReceiptError(f"identity mismatch: {key}")
    execution = receipt["execution"]
    for key, value in expectation["execution"].items():
        if execution[key] != value:
            raise ReceiptError(f"execution identity mismatch: {key}")
    if execution["executor"] == "local" and execution["workflow_run_id"] is not None:
        raise ReceiptError("local execution cannot claim a GitHub run")
    if execution["executor"] == "github-actions" and execution["workflow_run_id"] is None:
        raise ReceiptError("GitHub execution requires workflow identity")
    tasks = execution["tasks"]
    if len({row["id"] for row in tasks}) != len(tasks):
        raise ReceiptError("duplicate task")
    start, finish = [datetime.fromisoformat(execution[key]) for key in ("started_at", "finished_at")]
    if finish < start or finish > datetime.now(UTC):
        raise ReceiptError("stale or nonterminal execution time")
    if expectation.get("not_before") and start < datetime.fromisoformat(expectation["not_before"]):
        raise ReceiptError("execution predates the selected attempt")
    if receipt["actual"] != receipt["expected"] or (execution["exit_code"] == 0) != (
        receipt["actual"] == "pass"
    ):
        raise ReceiptError("unexpected terminal outcome or exit classification")
    outputs = receipt["evidence"]["outputs"]
    ids = [row["id"] for row in outputs]
    if len(set(ids)) != len(ids) or len({row["path"] for row in outputs}) != len(outputs):
        raise ReceiptError("duplicate output")
    if sorted(ids) != sorted(expectation["output_ids"]) or "execution-log" not in ids:
        raise ReceiptError("missing or unexpected named output")
    for row in outputs:
        if digest(output_path(root, row["path"]).read_bytes()) != row["digest"]:
            raise ReceiptError(f"output digest mismatch: {row['id']}")
    for key, identity in (
        ("fitness_ledger_digest", "fitness-ledger"),
        ("runtime_receipt_digest", "runtime-receipt"),
    ):
        expected_digest = next((row["digest"] for row in outputs if row["id"] == identity), None)
        if receipt["evidence"][key] != expected_digest:
            raise ReceiptError(f"unbound {key}")
    finding = receipt["evidence"]["finding"]
    if finding != expectation["finding"]:
        raise ReceiptError("finding identity mismatch")
    if receipt["actual"] != "pass" and (
        not finding
        or not any(
            finding in output_path(root, row["path"]).read_text(errors="replace")
            for row in outputs
            if row["id"] != "execution-log"
        )
    ):
        raise ReceiptError("negative case missing declared finding/denial evidence")
    return digest(json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode())


def write(expectation, observation, root, destination):
    execution = expectation["execution"]
    if execution["executor"] == "github-actions" and (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_RUN_ID") != execution["workflow_run_id"]
        or os.environ.get("GITHUB_RUN_ATTEMPT") != str(execution["attempt"])
    ):
        raise ReceiptError("GitHub receipt requires the current Actions run and attempt")
    if execution["executor"] == "live-boundary":
        raise ReceiptError("live-boundary receipts require the protected admission writer")
    outputs = [
        {**row, "digest": digest(output_path(root, row["path"]).read_bytes())}
        for row in observation["outputs"]
    ]
    receipt = {
        "schema": "tc.sdlc/assurance/v1",
        **{key: expectation[key] for key in ("subject", "case_id", "expected", "candidate", "consumer")},
        "actual": observation["actual"],
        "execution": {
            **execution,
            **{key: observation[key] for key in ("started_at", "finished_at", "exit_code")},
        },
        "evidence": {
            "outputs": outputs,
            "finding": observation["finding"],
            "fitness_ledger_digest": None,
            "runtime_receipt_digest": None,
        },
    }
    for key, identity in (
        ("fitness_ledger_digest", "fitness-ledger"),
        ("runtime_receipt_digest", "runtime-receipt"),
    ):
        receipt["evidence"][key] = next((row["digest"] for row in outputs if row["id"] == identity), None)
    with destination.open("x") as stream:
        stream.write(json.dumps(receipt, indent=2) + "\n")
    validate(receipt, expectation, root)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["write", "validate"])
    parser.add_argument("--expectation", type=Path, required=True)
    parser.add_argument("--observation", type=Path)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        expectation = read(args.expectation)
        receipt = (
            write(expectation, read(args.observation), args.root, args.receipt)
            if args.operation == "write"
            else read(args.receipt)
        )
        validate(receipt, expectation, args.root)
        print(f"{digest(args.receipt.read_bytes())} {receipt['case_id']}: {receipt['actual']}")
    except (ReceiptError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"assurance: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
