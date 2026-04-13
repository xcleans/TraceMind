"""Bootstrap TraceAnalyzer from atrace-analyzer (monorepo sibling) or installed package."""

from __future__ import annotations

import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent.parent  # TraceMind/
_monorepo_path = _repo_root / "_monorepo.py"
if _monorepo_path.is_file():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    import _monorepo; _monorepo.bootstrap()  # noqa: E702

from atrace_analyzer import TraceAnalyzer  # noqa: E402

# Singleton — TraceProcessor sessions are expensive; share across requests.
_analyzer: TraceAnalyzer | None = None


def get_analyzer() -> TraceAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = TraceAnalyzer()
    return _analyzer
