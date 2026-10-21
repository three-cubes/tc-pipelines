"""Local published-surface inventory: every callable workflow and composite action is declared.

The disposable consumer lab that once ran beside it is superseded (ledger consumer-lab-superseded).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LEVELS = ("structural", "hermetic", "hosted", "live")


class AssuranceError(Exception):
    """A required assurance obligation was not demonstrated."""


def read_yaml(path):
    return yaml.safe_load(path.read_text())


def discover(root):
    rows = []
    for path in sorted((root / ".github/workflows").glob("*.y*ml")):
        data = read_yaml(path)
        events = data.get("on", data.get(True, {}))
        if events == "workflow_call" or (isinstance(events, (dict, list)) and "workflow_call" in events):
            rows.append(
                {
                    "id": "workflow." + path.stem,
                    "path": path.relative_to(root).as_posix(),
                }
            )
    for home in ("actions", ".github/actions"):
        for path in sorted((root / home).rglob("action.y*ml")):
            if read_yaml(path).get("runs", {}).get("using") == "composite":
                name = path.parent.relative_to(root).as_posix().replace("/", ".").lstrip(".")
                rows.append({"id": "action." + name, "path": path.relative_to(root).as_posix()})
    return rows


def inventory(root):
    data = read_yaml(root / "assurance/surfaces.yaml")
    if data.get("schema") != "tc.sdlc/surface-assurance/v1":
        raise AssuranceError("inventory: unsupported schema")
    entries = data.get("surfaces", [])
    actual = {row["path"]: row["id"] for row in discover(root)}
    declared = {row["path"]: row["id"] for row in entries}
    if len(declared) != len(entries) or len({r["id"] for r in entries}) != len(entries):
        raise AssuranceError("inventory: duplicate path or id")
    if declared != actual:
        raise AssuranceError(f"inventory: public surface mismatch; discovered={actual}, declared={declared}")
    for row in entries:
        # Every public adapter controls a GitHub boundary. None may declare a
        # structural-only PR obligation or omit hosted release qualification.
        if row.get("risk") not in {"control-plane", "deployment"}:
            raise AssuranceError(f"inventory: invalid risk for {row['id']}")
        for lane, minimum in (("pr", 2), ("release", 3)):
            levels = row.get("required", {}).get(lane, [])
            if len(levels) < minimum or levels != list(LEVELS[: len(levels)]):
                raise AssuranceError(f"inventory: {row['id']} requires cumulative {lane} evidence")
        if not row.get("sabotage") or not all(isinstance(s, str) and s.strip() for s in row["sabotage"]):
            raise AssuranceError(f"inventory: missing sabotage for {row['id']}")
        evidence = row.get("evidence", {})
        if not isinstance(evidence, dict) or not set(evidence) <= set(LEVELS):
            raise AssuranceError(f"inventory: invalid evidence levels for {row['id']}")
        for refs in evidence.values():
            if not isinstance(refs, list):
                raise AssuranceError("inventory: evidence references must be lists")
            for ref in refs:
                target = (root / ref).resolve()
                if not target.is_relative_to(root.resolve()) or not target.is_file():
                    raise AssuranceError(f"inventory: missing or unsafe evidence reference {ref}")
    return {
        "surfaces": len(entries),
        "evidence_produced": ["structural"],
        "note": "Required levels are obligations, not execution claims; hosted/live evidence is not produced here.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    # prepare and all are the public Makefile's entry points (`make prepare`, `make assurance`); the
    # consumer lab they once ran is superseded, so prepare has nothing to refresh and all validates
    # the inventory. --output and --fitness-wheel stay accepted for the callers that pass them.
    parser.add_argument("command", choices=["discover", "inventory", "prepare", "all"])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fitness-wheel", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command == "discover":
            result = discover(root)
        elif args.command == "prepare":
            result = {"prepared": [], "note": "the disposable consumer lab is superseded; nothing to refresh"}
        else:
            result = inventory(root)
        print(json.dumps(result, indent=2))
        return 0
    except (AssuranceError, OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
