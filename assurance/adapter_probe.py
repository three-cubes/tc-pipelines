"""Small real consumer tasks for hosted adapters; reuses the Task 8 inventory."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probe", choices=["gate", "mutation", "precommit"])
    parser.add_argument("--output", type=Path, default=Path("artifacts/adapter-result.json"))
    args = parser.parse_args()
    if args.probe == "gate":
        completed = subprocess.run(
            [sys.executable, str(ROOT / "assurance/run.py"), "inventory"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        result = {"status": "pass", **json.loads(completed.stdout)}
    elif args.probe == "mutation":
        # The same assertion kills a real arithmetic mutant in a child process.
        original = subprocess.run(
            [sys.executable, "-c", "assert 2 + 3 == 5"],
            capture_output=True,
            check=False,
        )
        mutant = subprocess.run(
            [sys.executable, "-c", "assert 2 - 3 == 5"],
            capture_output=True,
            check=False,
        )
        if original.returncode != 0 or mutant.returncode != 1 or b"AssertionError" not in mutant.stderr:
            return 1
        result = {
            "status": "pass",
            "original_exit": original.returncode,
            "mutant_exit": mutant.returncode,
            "killed": 1,
        }
    else:
        if "Apache License" not in (ROOT / "LICENSE").read_text():
            return 1
        result = {"status": "pass", "license": "Apache-2.0"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
