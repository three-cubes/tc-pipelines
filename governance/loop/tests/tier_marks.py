"""pytest's tier marks for the guardrail harness, with or without pytest installed.

The loop's lights-out gate (``loop_dispatcher.guardrails_validated``) runs
``test_loop_guardrails.py`` under stdlib ``unittest`` on a runner that installs
no packages. Under pytest this module re-exports pytest itself, so the tier
marker the gate engine checks is real; without it, the marks are inert.
"""

from __future__ import annotations

import types

try:
    import pytest
except ModuleNotFoundError:
    pytest = types.SimpleNamespace(mark=types.SimpleNamespace(unit=None))
