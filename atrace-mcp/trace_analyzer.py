"""trace_analyzer.py — Compatibility facade.

All analysis logic has been extracted to the ``atrace-analyzer`` package.
This module re-exports ``TraceAnalyzer`` so existing callers (server.py)
continue to work.
"""

from __future__ import annotations

import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
_monorepo_path = _repo_root / "_monorepo.py"
if _monorepo_path.is_file():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    import _monorepo; _monorepo.bootstrap()  # noqa: E702

from atrace_analyzer import TraceAnalyzer, TraceSession  # noqa: E402, F401

__all__ = ["TraceAnalyzer", "TraceSession"]
