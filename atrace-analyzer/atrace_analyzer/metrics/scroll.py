"""Scroll performance metrics — frame quality + duration percentiles."""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atrace_analyzer.analyzer import TraceAnalyzer


def scroll_performance_metrics(
    analyzer: TraceAnalyzer,
    trace_path: str,
    process: str | None = None,
    layer_name_hint: str | None = None,
) -> dict:
    try:
        process = analyzer.resolve_process(trace_path, process)
    except ValueError as e:
        return {"error": str(e)}

    if not layer_name_hint:
        layers = analyzer.query(trace_path, f"""
            SELECT DISTINCT layer_name FROM actual_frame_timeline_slice
            WHERE layer_name LIKE '%{process}%' LIMIT 5
        """)
        layer_name_hint = layers[0]["layer_name"] if layers else process

    lf = f"layer_name LIKE '%{layer_name_hint}%'"

    quality_rows = analyzer.query(trace_path, f"""
        SELECT jank_type, jank_tag, present_type,
               COUNT(*) AS frame_count,
               ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct
        FROM actual_frame_timeline_slice WHERE {lf}
        GROUP BY jank_type, jank_tag, present_type ORDER BY frame_count DESC
    """)

    total_frames = sum(r["frame_count"] for r in quality_rows)
    no_jank_pct = sum(r["pct"] for r in quality_rows if r["jank_tag"] == "No Jank")
    buffer_stuffing_pct = sum(r["pct"] for r in quality_rows if r["jank_tag"] == "Buffer Stuffing")
    self_jank_pct = sum(r["pct"] for r in quality_rows if r["jank_tag"] == "Self Jank")
    late_pct = sum(r["pct"] for r in quality_rows if r["present_type"] == "Late Present")

    dur_rows = analyzer.query(trace_path, f"""
        SELECT dur / 1e6 AS dur_ms FROM actual_frame_timeline_slice
        WHERE {lf} ORDER BY dur
    """)
    durs = [r["dur_ms"] for r in dur_rows]

    def pctl(lst: list, p: float) -> float:
        if not lst:
            return 0.0
        k = (len(lst) - 1) * p / 100
        lo, hi = int(k), min(int(k) + 1, len(lst) - 1)
        return round(lst[lo] + (lst[hi] - lst[lo]) * (k - lo), 3)

    frame_duration = {
        "total_frames": total_frames,
        "p50_ms": pctl(durs, 50), "p90_ms": pctl(durs, 90),
        "p95_ms": pctl(durs, 95), "p99_ms": pctl(durs, 99),
        "max_ms": round(max(durs), 3) if durs else 0.0,
    }

    worst_frames = analyzer.query(trace_path, f"""
        SELECT ts, ROUND(dur / 1e6, 3) AS dur_ms, present_type, jank_type, jank_tag
        FROM actual_frame_timeline_slice WHERE {lf} ORDER BY dur DESC LIMIT 10
    """)

    main_top = analyzer.query(trace_path, f"""
        SELECT s.name, ROUND(s.dur / 1e6, 3) AS dur_ms, s.ts, t.name AS thread
        FROM slice s
        JOIN thread_track tt ON s.track_id = tt.id
        JOIN thread t ON tt.utid = t.utid
        JOIN process p ON t.upid = p.upid
        WHERE p.name LIKE '%{process}%' AND t.is_main_thread = 1
            AND s.dur > 4000000
            AND s.name NOT LIKE '%nativePollOnce%'
            AND s.name NOT LIKE '%MessageQueue.next%'
            AND s.name NOT LIKE '%Looper.loop%'
            AND s.name NOT LIKE '%ActivityThread.main%'
            AND s.name NOT LIKE '%ZygoteInit%'
            AND s.name NOT LIKE '%RuntimeInit%'
        ORDER BY s.dur DESC LIMIT 20
    """)

    compose_slices = analyzer.query(trace_path, f"""
        SELECT s.name, COUNT(*) AS call_count,
               ROUND(MAX(s.dur) / 1e6, 3) AS max_ms,
               ROUND(AVG(s.dur) / 1e6, 3) AS avg_ms,
               ROUND(SUM(s.dur) / 1e6, 3) AS total_ms
        FROM slice s
        JOIN thread_track tt ON s.track_id = tt.id
        JOIN thread t ON tt.utid = t.utid
        JOIN process p ON t.upid = p.upid
        WHERE p.name LIKE '%{process}%' AND t.is_main_thread = 1
            AND (s.name LIKE 'Recomposer%' OR s.name LIKE 'compose:%'
                 OR s.name LIKE '%recompos%' OR s.name LIKE '%Compose%')
            AND s.dur > 500000
        GROUP BY s.name ORDER BY total_ms DESC LIMIT 15
    """)

    blocking = analyzer.query(trace_path, f"""
        SELECT s.name, COUNT(*) AS call_count,
               ROUND(MAX(s.dur) / 1e6, 3) AS max_ms,
               ROUND(AVG(s.dur) / 1e6, 3) AS avg_ms,
               ROUND(SUM(s.dur) / 1e6, 3) AS total_ms,
               CASE
                   WHEN s.name LIKE '%Binder%' THEN 'Binder'
                   WHEN s.name LIKE '%Lock%' OR s.name LIKE '%Monitor%' OR s.name LIKE '%contention%' THEN 'Lock'
                   WHEN s.name LIKE '%GC%' OR s.name LIKE '%concurrent%' THEN 'GC'
                   WHEN s.name LIKE '%IO%' OR s.name LIKE '%read%' OR s.name LIKE '%write%' THEN 'IO'
                   ELSE 'Other'
               END AS category
        FROM slice s
        JOIN thread_track tt ON s.track_id = tt.id
        JOIN thread t ON tt.utid = t.utid
        JOIN process p ON t.upid = p.upid
        WHERE p.name LIKE '%{process}%' AND t.is_main_thread = 1
            AND s.dur > 2000000
            AND (s.name LIKE '%Binder%' OR s.name LIKE '%Lock%'
                 OR s.name LIKE '%GC%' OR s.name LIKE '%Monitor%'
                 OR s.name LIKE '%contention%' OR s.name LIKE '%IO%')
        GROUP BY s.name ORDER BY total_ms DESC LIMIT 15
    """)

    verdict = {
        "layer": layer_name_hint,
        "no_jank_pct": round(no_jank_pct, 2),
        "buffer_stuffing_pct": round(buffer_stuffing_pct, 2),
        "self_jank_pct": round(self_jank_pct, 2),
        "late_present_pct": round(late_pct, 2),
        "p95_frame_ms": frame_duration["p95_ms"],
        "p99_frame_ms": frame_duration["p99_ms"],
        "max_frame_ms": frame_duration["max_ms"],
        "assessment": (
            "excellent" if no_jank_pct >= 95
            else "good" if no_jank_pct >= 85
            else "fair" if no_jank_pct >= 70
            else "poor"
        ),
    }

    return {
        "process": process, "layer": layer_name_hint,
        "frame_quality": {
            "distribution": quality_rows,
            "summary": {
                "total_frames": total_frames,
                "no_jank_pct": round(no_jank_pct, 2),
                "buffer_stuffing_pct": round(buffer_stuffing_pct, 2),
                "self_jank_pct": round(self_jank_pct, 2),
                "late_present_pct": round(late_pct, 2),
            },
        },
        "frame_duration": frame_duration,
        "worst_frames": worst_frames,
        "main_thread_top": main_top,
        "compose_slices": compose_slices,
        "blocking_calls": blocking,
        "verdict": verdict,
    }
