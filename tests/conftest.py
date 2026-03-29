"""
pytest configuration — stubs out the openai/pydantic chain at import time.

The system Python 3.9 has an arm64/x86_64 architecture mismatch for
pydantic_core, so any module that transitively imports openai will fail to
collect.  We register fake modules for the unavailable packages before any
test file imports them, so tests that don't need openai (batch utility
functions, batch_io helpers, etc.) can still be collected and run.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

_STUB_MODS = [
    "openai",
    "openai.types",
    "openai.types.batch",
    "pydantic",
    "pydantic_core",
]

for _mod in _STUB_MODS:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
