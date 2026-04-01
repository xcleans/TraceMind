"""
Perfetto Trace Processor wrapper for AI-driven analysis.

Provides structured query results from Perfetto traces,
designed to feed LLM agents with high-quality performance context.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from perfetto.trace_processor import TraceProcessor


@dataclass
class TraceSession:
    path: str
    tp: TraceProcessor
    process_name: str | None = None


class TraceAnalyzer:
    """Manages Perfetto TraceProcessor sessions and executes queries."""

    def __init__(self):
        self._sessions: dict[str, TraceSession] = {}

    def load(self, trace_path: str, process_name: str | None = None) -> str:
        abs_path = str(Path(trace_path).resolve())
        if abs_path in self._sessions:
            s = self._sessions[abs_path]
            if process_name:
                s.process_name = process_name
            return abs_path

        tp = TraceProcessor(trace=abs_path)
        self._sessions[abs_path] = TraceSession(
            path=abs_path, tp=tp, process_name=process_name
        )
        return abs_path

    def close(self, trace_path: str):
        abs_path = str(Path(trace_path).resolve())
        s = self._sessions.pop(abs_path, None)
        if s:
            s.tp.close()

    def close_all(self):
        for s in self._sessions.values():
            s.tp.close()
        self._sessions.clear()

    def _get(self, trace_path: str) -> TraceSession:
        abs_path = str(Path(trace_path).resolve())
        s = self._sessions.get(abs_path)
        if not s:
            raise ValueError(
                f"Trace not loaded: {trace_path}. "
                "Call load_trace first."
            )
        return s

    def query(self, trace_path: str, sql: str) -> list[dict[str, Any]]:
        s = self._get(trace_path)
        result = s.tp.query(sql)
        columns = result.column_names
        rows = []
        for row in result:
            rows.append({col: getattr(row, col) for col in columns})
        return rows

    # ── Pre-built analysis queries ──────────────────────────────

    def overview(self, trace_path: str) -> dict:
        s = self._get(trace_path)
        tp = s.tp

        procs = self.query(trace_path, """
            SELECT pid, name, upid FROM process
            WHERE name IS NOT NULL AND name != ''
            ORDER BY pid
        """)

        threads = self.query(trace_path, """
            SELECT COUNT(*) as cnt FROM thread WHERE name IS NOT NULL
        """)

        slices = self.query(trace_path, """
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

    def top_slices(
        self,
        trace_path: str,
        process: str | None = None,
        thread: str | None = None,
        name_pattern: str | None = None,
        min_dur_ms: float = 0,
        limit: int = 20,
    ) -> list[dict]:
        s = self._get(trace_path)
        process = process or s.process_name

        where = ["s.dur > 0"]
        if process:
            where.append(f"p.name LIKE '%{process}%'")
        if thread:
            where.append(f"t.name LIKE '%{thread}%'")
        if name_pattern:
            where.append(f"s.name LIKE '%{name_pattern}%'")
        if min_dur_ms > 0:
            where.append(f"s.dur > {int(min_dur_ms * 1e6)}")

        where_clause = " AND ".join(where)

        return self.query(trace_path, f"""
            SELECT
                s.name,
                s.dur / 1000000.0 AS dur_ms,
                s.ts,
                t.name AS thread,
                t.tid,
                p.name AS process,
                p.pid,
                s.id AS slice_id,
                s.depth
            FROM slice s
            JOIN thread_track tt ON s.track_id = tt.id
            JOIN thread t ON tt.utid = t.utid
            JOIN process p ON t.upid = p.upid
            WHERE {where_clause}
            ORDER BY s.dur DESC
            LIMIT {limit}
        """)

    def call_chain(self, trace_path: str, slice_id: int) -> list[dict]:
        return self.query(trace_path, f"""
            WITH RECURSIVE ancestors(id, name, dur, depth, parent_id) AS (
                SELECT id, name, dur, depth, parent_id FROM slice WHERE id = {slice_id}
                UNION ALL
                SELECT s.id, s.name, s.dur, s.depth, s.parent_id
                FROM slice s
                JOIN ancestors a ON s.id = a.parent_id
            )
            SELECT id, name, dur / 1000000.0 AS dur_ms, depth
            FROM ancestors
            ORDER BY depth ASC
        """)

    def children(self, trace_path: str, slice_id: int, limit: int = 20) -> list[dict]:
        return self.query(trace_path, f"""
            SELECT
                s.id AS slice_id,
                s.name,
                s.dur / 1000000.0 AS dur_ms,
                s.depth
            FROM slice s
            WHERE s.parent_id = {slice_id} AND s.dur > 0
            ORDER BY s.dur DESC
            LIMIT {limit}
        """)

    def thread_states(
        self, trace_path: str, thread_name: str, ts_start: int = 0, ts_end: int = 0
    ) -> list[dict]:
        time_filter = ""
        if ts_start and ts_end:
            time_filter = f"AND ts.ts >= {ts_start} AND ts.ts <= {ts_end}"

        return self.query(trace_path, f"""
            SELECT
                ts.state,
                SUM(ts.dur) / 1000000.0 AS total_ms,
                COUNT(*) AS count
            FROM thread_state ts
            JOIN thread t ON ts.utid = t.utid
            WHERE t.name LIKE '%{thread_name}%'
                AND ts.dur > 0
                {time_filter}
            GROUP BY ts.state
            ORDER BY total_ms DESC
        """)

    def analyze_startup(self, trace_path: str, process: str | None = None) -> dict:
        s = self._get(trace_path)
        process = process or s.process_name
        if not process:
            return {"error": "process name required"}

        top = self.top_slices(trace_path, process=process, thread="main", limit=30)

        bind_app = [r for r in top if "bindApplication" in (r.get("name") or "")]
        activity_create = [
            r for r in top if "onCreate" in (r.get("name") or "") and "Activity" in (r.get("name") or "")
        ]
        app_create = [
            r for r in top if "onCreate" in (r.get("name") or "") and "Application" in (r.get("name") or "")
        ]

        blocking = self.query(trace_path, f"""
            SELECT
                s.name,
                s.dur / 1000000.0 AS dur_ms,
                t.name AS thread
            FROM slice s
            JOIN thread_track tt ON s.track_id = tt.id
            JOIN thread t ON tt.utid = t.utid
            JOIN process p ON t.upid = p.upid
            WHERE p.name LIKE '%{process}%'
                AND t.is_main_thread = 1
                AND s.dur > 5000000
                AND (s.name LIKE '%Binder%'
                     OR s.name LIKE '%Lock%'
                     OR s.name LIKE '%GC%'
                     OR s.name LIKE '%IO%'
                     OR s.name LIKE '%inflate%'
                     OR s.name LIKE '%dex%'
                     OR s.name LIKE '%class%init%')
            ORDER BY s.dur DESC
            LIMIT 15
        """)

        return {
            "process": process,
            "top_main_thread_slices": top[:15],
            "bind_application": bind_app[:3],
            "application_onCreate": app_create[:3],
            "activity_onCreate": activity_create[:3],
            "blocking_calls": blocking,
        }

    # ── Scroll performance metrics ───────────────────────────────────────────────

    def scroll_performance_metrics(
        self,
        trace_path: str,
        process: str | None = None,
        layer_name_hint: str | None = None,
    ) -> dict:
        """Full scroll jank / frame quality report for comparing before-vs-after.

        Returns:
            frame_quality     – jank type/tag distribution + percentages (FrameTimeline)
            frame_duration    – P50/P90/P95/P99 and worst-N frame durations
            main_thread_top   – top-N slow slices on the main thread during scroll
            compose_slices    – Recomposer / compose:lazy:prefetch breakdown
            blocking_calls    – Binder/GC/IO on main thread ≥ 2ms
            verdict           – machine-readable summary dict for automated comparison
        """
        s = self._get(trace_path)
        process = process or s.process_name
        if not process:
            return {"error": "process name required"}

        # ── 1. Auto-detect layer name if not supplied ────────────────────────
        if not layer_name_hint:
            layers = self.query(trace_path, f"""
                SELECT DISTINCT layer_name
                FROM actual_frame_timeline_slice
                WHERE layer_name LIKE '%{process}%'
                LIMIT 5
            """)
            layer_name_hint = layers[0]["layer_name"] if layers else process

        layer_filter = f"layer_name LIKE '%{layer_name_hint}%'"

        # ── 2. Frame quality distribution ────────────────────────────────────
        quality_rows = self.query(trace_path, f"""
            SELECT
                jank_type,
                jank_tag,
                present_type,
                COUNT(*) AS frame_count,
                ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct
            FROM actual_frame_timeline_slice
            WHERE {layer_filter}
            GROUP BY jank_type, jank_tag, present_type
            ORDER BY frame_count DESC
        """)

        total_frames = sum(r["frame_count"] for r in quality_rows)
        no_jank_pct = sum(
            r["pct"] for r in quality_rows if r["jank_tag"] == "No Jank"
        )
        buffer_stuffing_pct = sum(
            r["pct"] for r in quality_rows if r["jank_tag"] == "Buffer Stuffing"
        )
        self_jank_pct = sum(
            r["pct"] for r in quality_rows if r["jank_tag"] == "Self Jank"
        )
        late_pct = sum(
            r["pct"] for r in quality_rows if r["present_type"] == "Late Present"
        )

        # ── 3. Frame duration percentiles ─────────────────────────────────────
        dur_rows = self.query(trace_path, f"""
            SELECT dur / 1e6 AS dur_ms
            FROM actual_frame_timeline_slice
            WHERE {layer_filter}
            ORDER BY dur
        """)
        durs = [r["dur_ms"] for r in dur_rows]

        def percentile(lst: list, p: float) -> float:
            if not lst:
                return 0.0
            k = (len(lst) - 1) * p / 100
            lo, hi = int(k), min(int(k) + 1, len(lst) - 1)
            return round(lst[lo] + (lst[hi] - lst[lo]) * (k - lo), 3)

        frame_duration = {
            "total_frames": total_frames,
            "p50_ms": percentile(durs, 50),
            "p90_ms": percentile(durs, 90),
            "p95_ms": percentile(durs, 95),
            "p99_ms": percentile(durs, 99),
            "max_ms": round(max(durs), 3) if durs else 0.0,
        }

        # worst 10 frames with jank context
        worst_frames = self.query(trace_path, f"""
            SELECT
                ts,
                ROUND(dur / 1e6, 3) AS dur_ms,
                present_type,
                jank_type,
                jank_tag
            FROM actual_frame_timeline_slice
            WHERE {layer_filter}
            ORDER BY dur DESC
            LIMIT 10
        """)

        # ── 4. Main thread top-N slow slices (excl. idle wait) ───────────────
        main_top = self.query(trace_path, f"""
            SELECT
                s.name,
                ROUND(s.dur / 1e6, 3) AS dur_ms,
                s.ts,
                t.name AS thread
            FROM slice s
            JOIN thread_track tt ON s.track_id = tt.id
            JOIN thread t ON tt.utid = t.utid
            JOIN process p ON t.upid = p.upid
            WHERE p.name LIKE '%{process}%'
                AND t.is_main_thread = 1
                AND s.dur > 4000000
                AND s.name NOT LIKE '%nativePollOnce%'
                AND s.name NOT LIKE '%MessageQueue.next%'
                AND s.name NOT LIKE '%Looper.loop%'
                AND s.name NOT LIKE '%ActivityThread.main%'
                AND s.name NOT LIKE '%ZygoteInit%'
                AND s.name NOT LIKE '%RuntimeInit%'
            ORDER BY s.dur DESC
            LIMIT 20
        """)

        # ── 5. Compose-specific slices ────────────────────────────────────────
        compose_slices = self.query(trace_path, f"""
            SELECT
                s.name,
                COUNT(*) AS call_count,
                ROUND(MAX(s.dur) / 1e6, 3) AS max_ms,
                ROUND(AVG(s.dur) / 1e6, 3) AS avg_ms,
                ROUND(SUM(s.dur) / 1e6, 3) AS total_ms
            FROM slice s
            JOIN thread_track tt ON s.track_id = tt.id
            JOIN thread t ON tt.utid = t.utid
            JOIN process p ON t.upid = p.upid
            WHERE p.name LIKE '%{process}%'
                AND t.is_main_thread = 1
                AND (s.name LIKE 'Recomposer%'
                     OR s.name LIKE 'compose:%'
                     OR s.name LIKE '%recompos%'
                     OR s.name LIKE '%Compose%')
                AND s.dur > 500000
            GROUP BY s.name
            ORDER BY total_ms DESC
            LIMIT 15
        """)

        # ── 6. Blocking calls on main thread ─────────────────────────────────
        blocking = self.query(trace_path, f"""
            SELECT
                s.name,
                COUNT(*) AS call_count,
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
            WHERE p.name LIKE '%{process}%'
                AND t.is_main_thread = 1
                AND s.dur > 2000000
                AND (s.name LIKE '%Binder%'
                     OR s.name LIKE '%Lock%'
                     OR s.name LIKE '%GC%'
                     OR s.name LIKE '%Monitor%'
                     OR s.name LIKE '%contention%'
                     OR s.name LIKE '%IO%')
            GROUP BY s.name
            ORDER BY total_ms DESC
            LIMIT 15
        """)

        # ── 7. Machine-readable verdict (for automated comparison) ────────────
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
            "process": process,
            "layer": layer_name_hint,
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

    def analyze_jank(self, trace_path: str, process: str | None = None) -> dict:
        s = self._get(trace_path)
        process = process or s.process_name
        if not process:
            return {"error": "process name required"}

        jank_frames = self.query(trace_path, f"""
            SELECT
                s.name,
                s.dur / 1000000.0 AS dur_ms,
                s.ts
            FROM slice s
            JOIN thread_track tt ON s.track_id = tt.id
            JOIN thread t ON tt.utid = t.utid
            JOIN process p ON t.upid = p.upid
            WHERE p.name LIKE '%{process}%'
                AND t.is_main_thread = 1
                AND (s.name LIKE 'Choreographer%'
                     OR s.name LIKE 'doFrame%'
                     OR s.name LIKE 'DrawFrame%')
                AND s.dur > 16600000
            ORDER BY s.dur DESC
            LIMIT 30
        """)

        long_slices_on_main = self.query(trace_path, f"""
            SELECT
                s.name,
                s.dur / 1000000.0 AS dur_ms,
                s.ts
            FROM slice s
            JOIN thread_track tt ON s.track_id = tt.id
            JOIN thread t ON tt.utid = t.utid
            JOIN process p ON t.upid = p.upid
            WHERE p.name LIKE '%{process}%'
                AND t.is_main_thread = 1
                AND s.dur > 16600000
                AND s.name NOT LIKE 'Choreographer%'
            ORDER BY s.dur DESC
            LIMIT 20
        """)

        return {
            "process": process,
            "jank_frame_count": len(jank_frames),
            "jank_frames": jank_frames,
            "long_main_thread_slices": long_slices_on_main,
        }
