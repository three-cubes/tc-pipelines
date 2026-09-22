"""Release catalogue inputs are selected from the exact locked distribution."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
HELPER = REPO_ROOT / "images" / "sdlc" / "read-locked-fitness-version.py"


def test_locked_fitness_helper_selects_the_named_package_not_a_neighbouring_version(
    tmp_path: Path,
) -> None:
    lock = tmp_path / "uv.lock"
    lock.write_text(
        """version = 1

[[package]]
name = "unrelated-package"
version = "99.99.99"

[[package]]
name = "three-cubes-fitness"
version = "0.17.1"
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(HELPER), str(lock)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "0.17.1\n"
