"""Validate actual composite outputs after the real GitHub action invocation."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def verify(case):
    if case == "action-actions-detect-code-changes":
        if os.environ.get("CODE_CHANGED") != "true":
            raise ValueError("changed exact candidate was not detected")
        return {"code_changed": True}
    if case == "action-actions-license-present":
        if "Apache License" not in Path("LICENSE").read_text():
            raise ValueError("missing license")
        return {"license": "Apache-2.0"}
    if case in {"action-actions-pre-commit-cached", "action-actions-python-gate-body"}:
        result = json.loads(Path("artifacts/adapter-result.json").read_text())
        if result["status"] != "pass":
            raise ValueError("consumer task did not pass")
        return result
    if case == "action-actions-setup-cloudflared":
        binary = Path(os.environ["CLOUDFLARED_PATH"])
        observed = hashlib.sha256(binary.read_bytes()).hexdigest()
        if observed != os.environ["CLOUDFLARED_DIGEST"].removeprefix("sha256:"):
            raise ValueError("wrong installed cloudflared digest")
        version = subprocess.run(
            [str(binary), "--version"], capture_output=True, text=True, check=True
        ).stdout
        return {"executable_digest": observed, "version": version.strip()}
    if case == "action-actions-setup-uv-cached":
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--no-sync",
                "python",
                "-c",
                "import tc_fitness; print(tc_fitness.__file__)",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return {"installed_fitness": completed.stdout.strip()}
    if case == "action-actions-python-preparation":
        clean = subprocess.run(
            ["git", "diff", "--exit-code", "--", "."],
            capture_output=True,
            text=True,
            check=False,
        )
        if clean.returncode != 0:
            raise ValueError(f"preparation changed the hosted fixture:\n{clean.stdout}")
        return {"status": "pass", "working_tree": "clean"}
    raise ValueError("unknown adapter case")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/observed.json"))
    args = parser.parse_args()
    try:
        result = verify(os.environ["CASE_ID"])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        print(f"assurance: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
