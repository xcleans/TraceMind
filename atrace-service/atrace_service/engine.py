"""Bootstrap TraceAnalyzer from atrace-mcp (monorepo sibling) or installed package."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_trace_analyzer_importable() -> None:
    """Add atrace-mcp to sys.path so TraceAnalyzer can be imported.

    Resolution order:
    1. Already on sys.path (installed package or PYTHONPATH override).
    2. Sibling directory: <repo-root>/atrace-mcp/ next to this service.
    """
    try:
        import trace_analyzer  # noqa: F401 — already importable
        return
    except ModuleNotFoundError:
        pass

    # Walk up from this file to the repo root, then look for atrace-mcp/
    service_root = Path(__file__).resolve().parent.parent  # atrace-service/
    repo_root = service_root.parent                         # TraceMind/
    mcp_dir = repo_root / "atrace-mcp"

    if mcp_dir.is_dir():
        sys.path.insert(0, str(mcp_dir))
        return

    raise ImportError(
        "Cannot locate trace_analyzer. "
        "Either install atrace-mcp or run from the TraceMind monorepo "
        "where atrace-mcp/ sits next to atrace-service/."
    )


_ensure_trace_analyzer_importable()

from trace_analyzer import TraceAnalyzer  # noqa: E402 — path fix must run first

# Singleton — TraceProcessor sessions are expensive; share across requests.
_analyzer: TraceAnalyzer | None = None


def get_analyzer() -> TraceAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = TraceAnalyzer()
    return _analyzer
