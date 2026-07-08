"""Shard-probe for the python-quality-gate self-test.

Runs as the fixture gate's single `run` step. When the reusable invokes
`tc-fitness run --shard i/N`, the engine appends this step's substituted
`shard_args` (`--split i of N`) to argv and sets `COVERAGE_FILE=.coverage.<i>`.
The probe echoes both so the self-test log proves the passthrough, writes real
coverage data to `COVERAGE_FILE` so `coverage-combine` has something to merge,
and asserts the shape indicated by `EXPECT_SHARD` (exported by the caller's
pre-steps) so a broken passthrough FAILS the gate rather than passing silently.
"""

from __future__ import annotations

import os
import sys

argv = sys.argv[1:]
joined = " ".join(argv)
cov_file = os.environ.get("COVERAGE_FILE", "")
expect_shard = os.environ.get("EXPECT_SHARD", "") == "1"
print(f"SHARD-PROBE argv={argv!r} COVERAGE_FILE={cov_file!r} expect_shard={expect_shard}")

if expect_shard:
    if "--split" not in argv or "of" not in argv:
        sys.exit(f"FAIL: expected injected shard args (--split i of N), got {joined!r}")
    if not cov_file.startswith(".coverage."):
        sys.exit(f"FAIL: expected COVERAGE_FILE=.coverage.<i>, got {cov_file!r}")
else:
    if argv:
        sys.exit(f"FAIL: expected no shard args when unsharded, got {joined!r}")
    if cov_file:
        sys.exit(f"FAIL: expected no COVERAGE_FILE override when unsharded, got {cov_file!r}")

# Write real (branch) coverage data to the shard-scoped file so coverage-combine
# has genuine data to merge (empty files make `coverage combine` error).
if cov_file:
    try:
        import coverage

        cov = coverage.Coverage(data_file=cov_file, branch=True)
        cov.start()
        _ = sum(range(3))
        cov.stop()
        cov.save()
        print(f"SHARD-PROBE wrote coverage data to {cov_file}")
    except Exception as exc:  # noqa: BLE001 - probe is best-effort on coverage
        print(f"SHARD-PROBE coverage skipped: {exc}")

print("SHARD-PROBE OK")
