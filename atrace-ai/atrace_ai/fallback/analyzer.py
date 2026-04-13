"""FallbackAnalyzer — local TraceAnalyzer analysis when Cursor Agent is unavailable.

Provides structured evidence collection using local TraceAnalyzer methods.
This is the fallback path: when Cursor CLI + MCP is available, analysis is
AI-driven (via Playbook prompts). This module only runs when that path fails.

TraceAnalyzer is injected via constructor (dependency inversion) so this module
stays independent of import mechanics and perfetto native library loading.

TraceAnalyzer protocol (duck-typed):
  overview(trace_path)
  top_slices(trace_path, process=, main_thread_only=, limit=)
  children(trace_path, slice_id, limit=)
  call_chain(trace_path, slice_id)
  thread_states(trace_path, process)
  query(trace_path, sql)
  analyze_startup(trace_path, process)
  analyze_jank(trace_path, process)
  scroll_performance_metrics(trace_path, process, layer_hint)
"""

from __future__ import annotations

from typing import Any, Protocol


class TraceAnalyzerLike(Protocol):
    """Minimal interface expected from TraceAnalyzer."""

    def overview(self, trace_path: str) -> dict[str, Any]: ...
    def top_slices(self, trace_path: str, *, process: str | None = None,
                   main_thread_only: bool = False, limit: int = 10) -> list[dict[str, Any]]: ...
    def children(self, trace_path: str, slice_id: int, limit: int = 10) -> list[dict[str, Any]]: ...
    def call_chain(self, trace_path: str, slice_id: int) -> list[dict[str, Any]]: ...
    def thread_states(self, trace_path: str, process: str) -> list[dict[str, Any]]: ...
    def query(self, trace_path: str, sql: str) -> list[dict[str, Any]]: ...
    def analyze_startup(self, trace_path: str, process: str | None = None) -> dict[str, Any]: ...
    def analyze_jank(self, trace_path: str, process: str | None = None) -> dict[str, Any]: ...
    def scroll_performance_metrics(self, trace_path: str, process: str | None = None,
                                   layer_hint: str | None = None) -> dict[str, Any]: ...


def _safe_call(name: str, fn, ctx: dict[str, Any]) -> None:
    try:
        ctx[name] = fn()
    except Exception as exc:
        ctx[name] = {"error": str(exc)}


def _drill_children(
    analyzer: TraceAnalyzerLike,
    trace_path: str,
    slice_id: int,
    depth: int = 2,
    limit: int = 5,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        kids = analyzer.children(trace_path, slice_id, limit=limit)
    except Exception:
        return items
    for kid in kids:
        entry: dict[str, Any] = {
            "slice_id": kid.get("slice_id"),
            "name": kid.get("name", "?"),
            "dur_ms": kid.get("dur_ms", 0),
            "depth": kid.get("depth", 0),
        }
        if depth > 1 and kid.get("slice_id"):
            sub = _drill_children(analyzer, trace_path, kid["slice_id"], depth - 1, limit=3)
            if sub:
                entry["children"] = sub
        items.append(entry)
    return items


def _blocking_calls_sql(process: str | None) -> str:
    proc_filter = f"AND p.name LIKE '%{process}%'" if process else ""
    return f"""
SELECT s.name, count(*) AS cnt, round(sum(s.dur)/1e6,2) AS total_ms
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE t.is_main_thread = 1
  AND (s.name LIKE '%binder%' OR s.name LIKE '%Lock%' OR s.name LIKE '%GC%'
       OR s.name LIKE '%contention%' OR s.name LIKE '%IO%'
       OR s.name LIKE '%Blocking%' OR s.name LIKE '%monitor%')
  {proc_filter}
GROUP BY s.name ORDER BY total_ms DESC LIMIT 15
"""


class FallbackAnalyzer:
    """Produces structured evidence context using local TraceAnalyzer.

    Used only when Cursor Agent + MCP is unavailable.
    When Cursor Agent is available, analysis is AI-driven via Playbook prompts.
    """

    def __init__(self, analyzer: TraceAnalyzerLike) -> None:
        self._analyzer = analyzer

    def chat_analysis(
        self,
        question: str,
        trace_path: str,
        process: str | None = None,
    ) -> dict[str, Any]:
        """Keyword-guided selective analysis for chat questions."""
        ctx: dict[str, Any] = {}
        a = self._analyzer
        _safe_call("overview", lambda: a.overview(trace_path), ctx)
        q = question.lower()

        do_startup = any(k in q for k in ("start", "启动", "冷启动", "首帧", "launch"))
        do_jank = any(k in q for k in ("jank", "卡顿", "掉帧", "frame", "帧"))
        do_scroll = any(k in q for k in ("scroll", "滑动", "fps", "列表"))
        do_slice = any(k in q for k in ("slice", "函数", "耗时", "主线程", "热点", "slow", "top"))
        do_thread = any(k in q for k in ("thread", "线程", "sleep", "running", "状态"))
        do_block = any(k in q for k in ("binder", "gc", "lock", "io", "阻塞", "block"))

        if do_startup:
            _safe_call("startup", lambda: a.analyze_startup(trace_path, process), ctx)
        if do_jank:
            _safe_call("jank", lambda: a.analyze_jank(trace_path, process), ctx)
        if do_scroll:
            _safe_call("scroll", lambda: a.scroll_performance_metrics(trace_path, process, None), ctx)
        if not (do_startup or do_jank or do_scroll):
            _safe_call("jank", lambda: a.analyze_jank(trace_path, process), ctx)

        if do_slice or do_startup or do_jank:
            _safe_call("top_slices", lambda: a.top_slices(
                trace_path, process=process, main_thread_only=True, limit=10,
            ), ctx)
        if do_block:
            _safe_call("blocking_calls", lambda: a.query(trace_path, _blocking_calls_sql(process)), ctx)
        if do_thread and process:
            _safe_call("main_thread_states", lambda: a.thread_states(trace_path, process), ctx)

        self._add_drill_down(ctx, trace_path, top_n=3, drill_depth=2, drill_limit=4)
        return ctx

    def auto_analysis(
        self,
        trace_path: str,
        process: str | None = None,
        layer_hint: str | None = None,
    ) -> dict[str, Any]:
        """Comprehensive auto-analysis — all metrics + deep drill."""
        ctx: dict[str, Any] = {}
        a = self._analyzer
        _safe_call("overview", lambda: a.overview(trace_path), ctx)
        _safe_call("startup", lambda: a.analyze_startup(trace_path, process), ctx)
        _safe_call("jank", lambda: a.analyze_jank(trace_path, process), ctx)
        _safe_call("scroll", lambda: a.scroll_performance_metrics(trace_path, process, layer_hint), ctx)
        _safe_call("top_slices", lambda: a.top_slices(
            trace_path, process=process, main_thread_only=True, limit=15,
        ), ctx)
        _safe_call("blocking_calls", lambda: a.query(trace_path, _blocking_calls_sql(process)), ctx)
        if process:
            _safe_call("main_thread_states", lambda: a.thread_states(trace_path, process), ctx)

        self._add_drill_down(ctx, trace_path, top_n=5, drill_depth=2, drill_limit=5)
        return ctx

    # ── Deep drill ─────────────────────────────────────────

    def _add_drill_down(
        self,
        ctx: dict[str, Any],
        trace_path: str,
        top_n: int,
        drill_depth: int,
        drill_limit: int,
    ) -> None:
        top = ctx.get("top_slices", [])
        if not isinstance(top, list):
            return
        drill_results = []
        for s in top[:top_n]:
            if not (isinstance(s, dict) and s.get("slice_id")):
                continue
            kids = _drill_children(self._analyzer, trace_path, s["slice_id"], drill_depth, drill_limit)
            chain: list[dict[str, Any]] = []
            try:
                chain = self._analyzer.call_chain(trace_path, s["slice_id"])
            except Exception:
                pass
            drill_results.append({
                "name": s.get("name", "?"),
                "dur_ms": s.get("dur_ms", 0),
                "slice_id": s["slice_id"],
                "thread": s.get("thread", ""),
                "children": kids,
                "call_chain": chain,
            })
        if drill_results:
            ctx["drill_down"] = drill_results
