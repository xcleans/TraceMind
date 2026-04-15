"""Pre-built structured analysis endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from atrace_service.engine import TraceAnalyzer, get_analyzer
from atrace_service.models import AnalysisRequest, ErrorResponse, ScrollAnalysisRequest

router = APIRouter(prefix="/analyze", tags=["analysis"])
log = logging.getLogger("atrace.service.analysis")


def _require_session(trace_id: str, analyzer: TraceAnalyzer) -> str:
    trace_path = urllib.parse.unquote(trace_id)
    abs_path = str(Path(trace_path).resolve())
    if abs_path not in analyzer._sessions:
        # Dev mode with --reload clears in-memory sessions; try lazy re-load.
        if not Path(abs_path).is_file():
            raise HTTPException(
                status_code=404,
                detail=f"Trace not loaded and file does not exist: {trace_path}",
            )
        try:
            analyzer.load(abs_path)
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Trace exists but cannot be loaded: {trace_path}. {exc}",
            ) from exc
    return abs_path


# ── Startup ───────────────────────────────────────────────────────────────────

@router.post(
    "/{trace_id:path}/startup",
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Analyze app cold startup performance",
    description=(
        "Returns top slow main-thread functions, `bindApplication`, "
        "`Application.onCreate`, `Activity.onCreate`, and blocking calls (Binder/GC/IO). "
        "Designed as the first tool to call for startup regression investigation."
    ),
)
def analyze_startup(
    trace_id: str,
    body: AnalysisRequest,
    analyzer: TraceAnalyzer = Depends(get_analyzer),
) -> Any:
    log.info("POST /analyze/%s/startup process=%s", trace_id, body.process)
    abs_path = _require_session(trace_id, analyzer)
    try:
        result = analyzer.analyze_startup(abs_path, body.process)
        log.info("POST /analyze/%s/startup → done", trace_id)
        return result
    except Exception as exc:
        log.error("POST /analyze/%s/startup failed: %s", trace_id, exc, exc_info=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── Jank (quick smoke-check) ──────────────────────────────────────────────────

@router.post(
    "/{trace_id:path}/jank",
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Quick jank smoke-check",
    description=(
        "Fast first-pass: detects obvious jank frames (>16.6ms threshold) and returns "
        "long main-thread operations. Use for startup/general traces or as a preliminary "
        "check. For precise 60/90/120Hz over-budget stats and jank-type distribution, "
        "call `/analyze/{trace_id}/scroll` instead."
    ),
)
def analyze_jank(
    trace_id: str,
    body: AnalysisRequest,
    analyzer: TraceAnalyzer = Depends(get_analyzer),
) -> Any:
    log.info("POST /analyze/%s/jank process=%s", trace_id, body.process)
    abs_path = _require_session(trace_id, analyzer)
    try:
        result = analyzer.analyze_jank(abs_path, body.process)
        log.info("POST /analyze/%s/jank → done", trace_id)
        return result
    except Exception as exc:
        log.error("POST /analyze/%s/jank failed: %s", trace_id, exc, exc_info=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── Scroll Performance (primary) ──────────────────────────────────────────────

@router.post(
    "/{trace_id:path}/scroll",
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Primary scroll smoothness and frame quality analysis",
    description=(
        "Comprehensive scroll jank report covering:\n"
        "- **frame_quality**: FrameTimeline jank-type/tag distribution (No Jank / Buffer Stuffing / "
        "App Deadline Missed / Self Jank / Late Present)\n"
        "- **frame_duration**: P50 / P90 / P95 / P99 / max (ms)\n"
        "- **worst_frames**: Top-10 slowest frames with jank context\n"
        "- **main_thread_top**: Slowest meaningful main-thread slices (idle-wait excluded)\n"
        "- **compose_slices**: Recomposer / compose:lazy:prefetch stats\n"
        "- **blocking_calls**: Binder / Lock / GC / IO on main thread ≥ 2ms\n"
        "- **verdict**: Machine-readable summary (assessment: excellent/good/fair/poor)\n\n"
        "Tip: diff two `verdict` dicts to measure before-vs-after optimisation impact."
    ),
)
def analyze_scroll(
    trace_id: str,
    body: ScrollAnalysisRequest,
    analyzer: TraceAnalyzer = Depends(get_analyzer),
) -> Any:
    log.info("POST /analyze/%s/scroll process=%s layer=%s", trace_id, body.process, body.layer_name_hint)
    abs_path = _require_session(trace_id, analyzer)
    try:
        result = analyzer.scroll_performance_metrics(
            abs_path,
            process=body.process,
            layer_name_hint=body.layer_name_hint,
        )
        verdict = result.get("verdict", {}).get("assessment", "?") if isinstance(result, dict) else "?"
        log.info("POST /analyze/%s/scroll → verdict=%s", trace_id, verdict)
        return result
    except Exception as exc:
        log.error("POST /analyze/%s/scroll failed: %s", trace_id, exc, exc_info=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── SSE streaming (Perfetto UI plugin / live progress) ───────────────────────

async def _sse_scroll_stream(
    abs_path: str,
    process: str | None,
    layer_name_hint: str | None,
    analyzer: TraceAnalyzer,
) -> AsyncIterator[str]:
    """Yield SSE events during scroll analysis so the UI can render progressively."""

    def _emit(event: str, data: Any) -> str:
        payload = json.dumps(data, default=str)
        return f"event: {event}\ndata: {payload}\n\n"

    yield _emit("status", {"phase": "frame_quality", "pct": 10})
    await asyncio.sleep(0)  # let other coroutines run

    try:
        # scroll_performance_metrics(self, trace_path, **kwargs) — pass process/layer as keywords,
        # not extra positionals (to_thread would otherwise raise "takes 2 positional arguments but 4 were given").
        result = await asyncio.to_thread(
            analyzer.scroll_performance_metrics,
            abs_path,
            process=process,
            layer_name_hint=layer_name_hint,
        )
    except Exception as exc:
        yield _emit("error", {"message": str(exc)})
        return

    # Stream sub-sections so the frontend can render each table as it arrives
    for section in ("frame_quality", "frame_duration", "worst_frames", "main_thread_top",
                    "compose_slices", "blocking_calls"):
        yield _emit(section, result.get(section))
        await asyncio.sleep(0)

    yield _emit("verdict", result.get("verdict"))
    yield _emit("done", {"status": "complete"})


@router.post(
    "/{trace_id:path}/scroll/stream",
    response_class=StreamingResponse,
    summary="Scroll analysis as Server-Sent Events (for Perfetto UI plugin)",
    description=(
        "Same analysis as `/analyze/{trace_id}/scroll` but streams results section-by-section "
        "as SSE events so the UI can render progressively without waiting for the full result. "
        "Event types: `frame_quality`, `frame_duration`, `worst_frames`, `main_thread_top`, "
        "`compose_slices`, `blocking_calls`, `verdict`, `done`, `error`."
    ),
)
def analyze_scroll_stream(
    trace_id: str,
    body: ScrollAnalysisRequest,
    analyzer: TraceAnalyzer = Depends(get_analyzer),
) -> StreamingResponse:
    log.info("POST /analyze/%s/scroll/stream process=%s layer=%s", trace_id, body.process, body.layer_name_hint)
    abs_path = _require_session(trace_id, analyzer)
    return StreamingResponse(
        _sse_scroll_stream(abs_path, body.process, body.layer_name_hint, analyzer),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
