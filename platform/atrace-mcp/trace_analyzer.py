"""trace_analyzer.py — Compatibility facade.

All analysis logic has been extracted to the ``atrace-analyzer`` package.
This module re-exports ``TraceAnalyzer`` so existing callers (server.py)
continue to work.
"""

from __future__ import annotations

import sys
from pathlib import Path

def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "platform" / "_monorepo.py").is_file():
            return parent
        if (parent / "_monorepo.py").is_file():
            return parent.parent if parent.name == "platform" else parent
    return here.parents[2]


_repo_root = _find_repo_root()
_monorepo_path = _repo_root / "platform" / "_monorepo.py"
if _monorepo_path.is_file():
    _module_dir = _monorepo_path.parent
    if str(_module_dir) not in sys.path:
        sys.path.insert(0, str(_module_dir))
    import _monorepo; _monorepo.bootstrap()  # noqa: E702

from atrace_analyzer import TraceAnalyzer, TraceSession  # noqa: E402, F401

__all__ = ["TraceAnalyzer", "TraceSession"]
