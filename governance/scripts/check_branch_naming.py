"""Check the local branch against meta-quality-gate's configurable policy."""

from __future__ import annotations

import argparse
import os
import re

from tc_fitness.checks.branch_naming import check_branch, current_branch

PATTERN = re.compile(r"^[a-z][a-z0-9-]*/[a-z0-9][a-z0-9_/-]*$")
EXEMPT_BRANCHES = {"main", "develop", "HEAD", "gh-pages"}
EXEMPT_PATTERNS = (
    re.compile(r"^worktree-agent-.*$"),
    re.compile(r"^renovate/.*$"),
    re.compile(r"^dependabot/.*$"),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch")
    args = parser.parse_args()
    branch = args.branch or os.environ.get("BRANCH_NAME") or current_branch()
    return check_branch(
        branch,
        exempt_branches=EXEMPT_BRANCHES,
        exempt_patterns=EXEMPT_PATTERNS,
        pattern=PATTERN,
    )


if __name__ == "__main__":
    raise SystemExit(main())
