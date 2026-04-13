"""Core TraceAnalyzer — Perfetto TraceProcessor session manager + SQL engine.

This is the canonical implementation. The metrics (startup, jank, scroll)
are imported from the ``metrics`` sub-package and attached as methods.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
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
        self._tp_lock = threading.RLock()

    # ── Session management ───────────────────────────────────

    def load(self, trace_path: str, process_name: str | None = None) -> str:
        abs_path = str(Path(trace_path).resolve())
        with self._tp_lock:
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
        with self._tp_lock:
            s = self._sessions.pop(abs_path, None)
            if s:
                s.tp.close()

    def close_all(self):
        with self._tp_lock:
            for s in self._sessions.values():
                s.tp.close()
            self._sessions.clear()

    def _get(self, trace_path: str) -> TraceSession:
        abs_path = str(Path(trace_path).resolve())
        s = self._sessions.get(abs_path)
        if not s:
            raise ValueError(f"Trace not loaded: {trace_path}. Call load_trace first.")
        return s

    def _default_process_name(self, trace_path: str) -> str | None:
        with self._tp_lock:
            return self._get(trace_path).process_name

    def resolve_process(self, trace_path: str, process: str | None) -> str:
        """Resolve and validate process name: use default if missing, reject too-short values."""
        p = process or self._default_process_name(trace_path)
        if not p:
            raise ValueError(
                "process 未指定且 trace 加载时未设置 process_name，"
                "请提供完整包名（如 com.example.app）"
            )
        if len(p) < 3:
            default = self._default_process_name(trace_path)
            if default and len(default) >= 3:
                return default
            raise ValueError(
                f'process="{p}" 太短会匹配到大量无关进程，'
                f"请使用完整包名（如 com.example.app）"
            )
        return p

    # ── SQL query engine ─────────────────────────────────────

    def query(self, trace_path: str, sql: str) -> list[dict[str, Any]]:
        with self._tp_lock:
            s = self._get(trace_path)
            result = s.tp.query(sql)
            columns = result.column_names
            rows = []
            for row in result:
                rows.append({col: getattr(row, col) for col in columns})
            return rows

    # ── Core queries ─────────────────────────────────────────

    def overview(self, trace_path: str) -> dict:
        from atrace_analyzer.metrics.overview import overview
        return overview(self, trace_path)

    def top_slices(self, trace_path: str, **kwargs) -> list[dict]:
        from atrace_analyzer.metrics.slices import top_slices
        return top_slices(self, trace_path, **kwargs)

    def call_chain(self, trace_path: str, slice_id: int) -> list[dict]:
        from atrace_analyzer.metrics.slices import call_chain
        return call_chain(self, trace_path, slice_id)

    def children(self, trace_path: str, slice_id: int, limit: int = 20) -> list[dict]:
        from atrace_analyzer.metrics.slices import children
        return children(self, trace_path, slice_id, limit)

    def thread_states(self, trace_path: str, thread_name: str, **kwargs) -> list[dict]:
        from atrace_analyzer.metrics.slices import thread_states
        return thread_states(self, trace_path, thread_name, **kwargs)

    # ── Pre-built analysis ───────────────────────────────────

    def analyze_startup(self, trace_path: str, process: str | None = None) -> dict:
        from atrace_analyzer.metrics.startup import analyze_startup
        return analyze_startup(self, trace_path, process)

    def analyze_jank(self, trace_path: str, process: str | None = None) -> dict:
        from atrace_analyzer.metrics.jank import analyze_jank
        return analyze_jank(self, trace_path, process)

    def scroll_performance_metrics(self, trace_path: str, **kwargs) -> dict:
        from atrace_analyzer.metrics.scroll import scroll_performance_metrics
        return scroll_performance_metrics(self, trace_path, **kwargs)
