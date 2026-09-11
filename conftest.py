"""Repository-wide pytest execution controls."""

from __future__ import annotations

import os
from typing import Any


def pytest_xdist_auto_num_workers(config: Any) -> int:
    """Use several cores without starving subprocess-heavy contract tests."""
    del config
    return min(os.cpu_count() or 1, 6)
