"""Trace overview metric."""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atrace_analyzer.analyzer import TraceAnalyzer


def overview(analyzer: TraceAnalyzer, trace_path: str) -> dict:
    procs = analyzer.query(trace_path, """
        SELECT pid, name, upid FROM process
        WHERE name IS NOT NULL AND name != ''
        ORDER BY pid
    """)
    threads = analyzer.query(trace_path, """
        SELECT COUNT(*) as cnt FROM thread WHERE name IS NOT NULL
    """)
    slices = analyzer.query(trace_path, """
        SELECT COUNT(*) as cnt, MIN(ts) as min_ts, MAX(ts + dur) as max_ts
        FROM slice WHERE dur > 0
    """)
    info = slices[0] if slices else {"cnt": 0, "min_ts": 0, "max_ts": 0}
    duration_ns = (info["max_ts"] or 0) - (info["min_ts"] or 0)

    return {
        "trace_path": trace_path,
        "duration_ms": round(duration_ns / 1e6, 1),
        "total_slices": info["cnt"],
        "total_threads": threads[0]["cnt"] if threads else 0,
        "processes": procs[:50],
    }
