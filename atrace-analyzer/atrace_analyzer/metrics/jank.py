"""Jank analysis metric."""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atrace_analyzer.analyzer import TraceAnalyzer


def analyze_jank(
    analyzer: TraceAnalyzer, trace_path: str, process: str | None = None
) -> dict:
    try:
        process = analyzer.resolve_process(trace_path, process)
    except ValueError as e:
        return {"error": str(e)}

    jank_frames = analyzer.query(trace_path, f"""
        SELECT s.name, s.dur / 1000000.0 AS dur_ms, s.ts
        FROM slice s
        JOIN thread_track tt ON s.track_id = tt.id
        JOIN thread t ON tt.utid = t.utid
        JOIN process p ON t.upid = p.upid
        WHERE p.name LIKE '%{process}%'
            AND t.is_main_thread = 1
            AND (s.name LIKE 'Choreographer%' OR s.name LIKE 'doFrame%'
                 OR s.name LIKE 'DrawFrame%')
            AND s.dur > 16600000
        ORDER BY s.dur DESC LIMIT 30
    """)

    long_slices = analyzer.query(trace_path, f"""
        SELECT s.name, s.dur / 1000000.0 AS dur_ms, s.ts
        FROM slice s
        JOIN thread_track tt ON s.track_id = tt.id
        JOIN thread t ON tt.utid = t.utid
        JOIN process p ON t.upid = p.upid
        WHERE p.name LIKE '%{process}%'
            AND t.is_main_thread = 1
            AND s.dur > 16600000
            AND s.name NOT LIKE 'Choreographer%'
        ORDER BY s.dur DESC LIMIT 20
    """)

    return {
        "process": process,
        "jank_frame_count": len(jank_frames),
        "jank_frames": jank_frames,
        "long_main_thread_slices": long_slices,
    }
