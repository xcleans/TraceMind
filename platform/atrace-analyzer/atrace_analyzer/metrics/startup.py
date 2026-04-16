"""Startup analysis metric."""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atrace_analyzer.analyzer import TraceAnalyzer


def analyze_startup(
    analyzer: TraceAnalyzer, trace_path: str, process: str | None = None
) -> dict:
    try:
        process = analyzer.resolve_process(trace_path, process)
    except ValueError as e:
        return {"error": str(e)}

    top = analyzer.top_slices(trace_path, process=process, limit=30, main_thread_only=True)

    bind_app = [r for r in top if "bindApplication" in (r.get("name") or "")]
    activity_create = [
        r for r in top
        if "onCreate" in (r.get("name") or "") and "Activity" in (r.get("name") or "")
    ]
    app_create = [
        r for r in top
        if "onCreate" in (r.get("name") or "") and "Application" in (r.get("name") or "")
    ]

    blocking = analyzer.query(trace_path, f"""
        SELECT
            s.name, s.dur / 1000000.0 AS dur_ms, t.name AS thread
        FROM slice s
        JOIN thread_track tt ON s.track_id = tt.id
        JOIN thread t ON tt.utid = t.utid
        JOIN process p ON t.upid = p.upid
        WHERE p.name LIKE '%{process}%'
            AND t.is_main_thread = 1 AND s.dur > 5000000
            AND (s.name LIKE '%Binder%' OR s.name LIKE '%Lock%'
                 OR s.name LIKE '%GC%' OR s.name LIKE '%IO%'
                 OR s.name LIKE '%inflate%' OR s.name LIKE '%dex%'
                 OR s.name LIKE '%class%init%')
        ORDER BY s.dur DESC LIMIT 15
    """)

    return {
        "process": process,
        "top_main_thread_slices": top[:15],
        "bind_application": bind_app[:3],
        "application_onCreate": app_create[:3],
        "activity_onCreate": activity_create[:3],
        "blocking_calls": blocking,
    }
