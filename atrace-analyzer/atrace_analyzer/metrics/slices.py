"""Slice-level query metrics: top_slices, call_chain, children, thread_states."""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atrace_analyzer.analyzer import TraceAnalyzer


def top_slices(
    analyzer: TraceAnalyzer,
    trace_path: str,
    process: str | None = None,
    thread: str | None = None,
    name_pattern: str | None = None,
    min_dur_ms: float = 0,
    limit: int = 20,
    main_thread_only: bool = False,
) -> list[dict]:
    process = analyzer.resolve_process(trace_path, process)

    where = ["s.dur > 0"]
    if process:
        where.append(f"p.name LIKE '%{process}%'")
    if main_thread_only:
        where.append("t.is_main_thread = 1")
    elif thread:
        where.append(f"t.name LIKE '%{thread}%'")
    if name_pattern:
        where.append(f"s.name LIKE '%{name_pattern}%'")
    if min_dur_ms > 0:
        where.append(f"s.dur > {int(min_dur_ms * 1e6)}")

    where_clause = " AND ".join(where)
    return analyzer.query(trace_path, f"""
        SELECT
            s.name, s.dur / 1000000.0 AS dur_ms, s.ts,
            t.name AS thread, t.tid,
            p.name AS process, p.pid,
            s.id AS slice_id, s.depth
        FROM slice s
        JOIN thread_track tt ON s.track_id = tt.id
        JOIN thread t ON tt.utid = t.utid
        JOIN process p ON t.upid = p.upid
        WHERE {where_clause}
        ORDER BY s.dur DESC
        LIMIT {limit}
    """)


def call_chain(analyzer: TraceAnalyzer, trace_path: str, slice_id: int) -> list[dict]:
    return analyzer.query(trace_path, f"""
        WITH RECURSIVE ancestors(id, name, dur, depth, parent_id) AS (
            SELECT id, name, dur, depth, parent_id FROM slice WHERE id = {slice_id}
            UNION ALL
            SELECT s.id, s.name, s.dur, s.depth, s.parent_id
            FROM slice s JOIN ancestors a ON s.id = a.parent_id
        )
        SELECT id, name, dur / 1000000.0 AS dur_ms, depth
        FROM ancestors ORDER BY depth ASC
    """)


def children(
    analyzer: TraceAnalyzer, trace_path: str, slice_id: int, limit: int = 20
) -> list[dict]:
    return analyzer.query(trace_path, f"""
        SELECT
            s.id AS slice_id, s.name,
            s.dur / 1000000.0 AS dur_ms, s.depth
        FROM slice s
        WHERE s.parent_id = {slice_id} AND s.dur > 0
        ORDER BY s.dur DESC LIMIT {limit}
    """)


def thread_states(
    analyzer: TraceAnalyzer,
    trace_path: str,
    thread_name: str,
    ts_start: int = 0,
    ts_end: int = 0,
) -> list[dict]:
    time_filter = ""
    if ts_start and ts_end:
        time_filter = f"AND ts.ts >= {ts_start} AND ts.ts <= {ts_end}"

    return analyzer.query(trace_path, f"""
        SELECT
            ts.state,
            SUM(ts.dur) / 1000000.0 AS total_ms,
            COUNT(*) AS count
        FROM thread_state ts
        JOIN thread t ON ts.utid = t.utid
        WHERE t.name LIKE '%{thread_name}%' AND ts.dur > 0 {time_filter}
        GROUP BY ts.state ORDER BY total_ms DESC
    """)
