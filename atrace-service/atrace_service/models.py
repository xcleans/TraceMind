"""Pydantic request / response models for the atrace HTTP service."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ── Trace Management ──────────────────────────────────────────────────────────

class LoadTraceRequest(BaseModel):
    trace_path: str = Field(..., description="Absolute path to .perfetto / .pb trace file")
    process_name: str | None = Field(None, description="Default process for subsequent queries")


class TraceOverview(BaseModel):
    trace_path: str
    duration_ms: float
    total_slices: int
    total_threads: int
    processes: list[dict[str, Any]]


class CaptureTraceRequest(BaseModel):
    package: str = Field(..., description="Android package name, e.g. com.example.app")
    duration_seconds: int = Field(10, ge=1, le=300)
    output_dir: str = Field("/tmp/atrace", description="Directory for output .perfetto file")
    serial: str | None = Field(None, description="ADB serial if multiple devices connected")
    port: int = Field(9090, ge=1, le=65535)
    cold_start: bool = False
    activity: str | None = None
    perfetto_config: str | None = Field(None, description="Path to .txtpb config file")
    proguard_mapping: str | None = Field(None, description="Path to mapping.txt for deobfuscation")
    buffer_size: str = Field("64mb", description='Perfetto ring buffer size, e.g. "64mb"')

    # Optional scroll injection while capture is running.
    inject_scroll: bool = False
    scroll_start_delay_seconds: float = Field(1.5, ge=0)
    scroll_repeat: int = Field(5, ge=1, le=200)
    scroll_dy: int = 600
    scroll_duration_ms: int = Field(200, ge=1, le=5000)
    scroll_start_x: int = 540
    scroll_start_y: int = 1200
    scroll_end_x: int | None = None
    scroll_end_y: int | None = None
    scroll_pause_ms: int = Field(300, ge=0, le=10000)


# ── SQL / Slice Query ─────────────────────────────────────────────────────────

class SqlRequest(BaseModel):
    sql: str = Field(..., description="PerfettoSQL query string")
    limit: int = Field(100, ge=1, le=2000, description="Row cap before truncation")
    summarize: bool = Field(
        False,
        description=(
            "Return statistical summary (min/max/avg/percentiles for numeric columns, "
            "top-5 values for string columns) instead of raw rows — keeps LLM context small"
        ),
    )


class SqlResponse(BaseModel):
    row_count: int
    truncated: bool
    rows: list[dict[str, Any]]
    summary: dict[str, Any] | None = None


class SlicesRequest(BaseModel):
    process: str | None = None
    thread: str | None = None
    name_pattern: str | None = None
    min_dur_ms: float = Field(0.0, ge=0)
    limit: int = Field(20, ge=1, le=500)
    main_thread_only: bool = False


class SliceChildrenResponse(BaseModel):
    slice_id: int
    children: list[dict[str, Any]]


class CallChainResponse(BaseModel):
    slice_id: int
    ancestors: list[dict[str, Any]]


class ThreadStatesRequest(BaseModel):
    thread_name: str
    ts_start: int = Field(0, description="Start timestamp in nanoseconds (0 = no filter)")
    ts_end: int = Field(0, description="End timestamp in nanoseconds (0 = no filter)")


# ── Analysis ──────────────────────────────────────────────────────────────────

class AnalysisRequest(BaseModel):
    process: str | None = Field(None, description="App package name; uses session default if omitted")


class ScrollAnalysisRequest(AnalysisRequest):
    layer_name_hint: str | None = Field(
        None,
        description="Substring to match FrameTimeline layer (e.g. 'MainActivity')",
    )


# ── Error ─────────────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


# ── AI Chat ───────────────────────────────────────────────────────────────────

class AiChatRequest(BaseModel):
    trace_path: str = Field(..., description="Loaded trace path")
    question: str = Field(..., description="User question for AI analysis")
    process: str | None = Field(None, description="Optional process/package context")
    include_context: bool = Field(
        True,
        description="If true, include overview/startup/jank/scroll snippets in AI prompt",
    )


class AutoAnalyzeRequest(BaseModel):
    trace_path: str = Field(..., description="Loaded trace path")
    process: str | None = Field(None, description="App package name")
    layer_name_hint: str | None = None


class AiChatMessage(BaseModel):
    role: str = Field(..., description="user | assistant | system")
    text: str
    source: str | None = Field(None, description="llm | fallback | auto | system")
    ts: float = Field(0, description="Unix timestamp")


class AiChatResponse(BaseModel):
    answer: str
    source: str = Field(..., description="llm | fallback | auto")
    context: dict[str, Any] | None = None
    session_id: str | None = None


class AiSessionInfo(BaseModel):
    session_id: str
    trace_path: str
    message_count: int
    created_ts: float
    last_ts: float


# ── SQL Summarizer ────────────────────────────────────────────────────────────

def summarize_rows(rows: list[dict[str, Any]], sample_size: int = 10) -> dict[str, Any]:
    """Return statistical digest of query results — keeps LLM context small.

    For numeric columns: min / max / avg / p50 / p90 / p95 / p99.
    For string columns: top-5 values with occurrence counts.
    Sample rows are chosen by the highest-value numeric column (performance-relevant).
    """
    if not rows:
        return {"total_rows": 0, "column_stats": [], "sample_rows": []}

    columns = list(rows[0].keys())
    column_stats: list[dict[str, Any]] = []

    perf_keys = {"dur", "dur_ms", "latency", "jank", "count", "total_ms", "max_ms"}
    sort_col: str | None = next(
        (c for c in columns if any(k in c.lower() for k in perf_keys)), None
    )

    for col in columns:
        values = [r[col] for r in rows if r.get(col) is not None]
        if not values:
            continue

        if all(isinstance(v, (int, float)) for v in values):
            sorted_vals = sorted(float(v) for v in values)

            def _pct(lst: list[float], p: float) -> float:
                k = (len(lst) - 1) * p / 100
                lo, hi = int(k), min(int(k) + 1, len(lst) - 1)
                return round(lst[lo] + (lst[hi] - lst[lo]) * (k - lo), 3)

            column_stats.append({
                "column": col,
                "type": "numeric",
                "min": round(sorted_vals[0], 3),
                "max": round(sorted_vals[-1], 3),
                "avg": round(sum(sorted_vals) / len(sorted_vals), 3),
                "p50": _pct(sorted_vals, 50),
                "p90": _pct(sorted_vals, 90),
                "p95": _pct(sorted_vals, 95),
                "p99": _pct(sorted_vals, 99),
            })
        else:
            from collections import Counter
            counts = Counter(str(v) for v in values)
            column_stats.append({
                "column": col,
                "type": "string",
                "top_values": [
                    {"value": v, "count": c}
                    for v, c in counts.most_common(5)
                ],
            })

    if sort_col:
        sample = sorted(rows, key=lambda r: -(r.get(sort_col) or 0))[:sample_size]
    else:
        step = max(1, len(rows) // sample_size)
        sample = rows[::step][:sample_size]

    return {
        "total_rows": len(rows),
        "column_stats": column_stats,
        "sample_rows": sample,
    }
