"""Trace management and raw query endpoints."""

from __future__ import annotations

import re
import time
import urllib.parse
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from atrace_service.engine import TraceAnalyzer, get_analyzer
from atrace_service.models import (
    CallChainResponse,
    ErrorResponse,
    LoadTraceRequest,
    SliceChildrenResponse,
    SlicesRequest,
    SqlRequest,
    SqlResponse,
    ThreadStatesRequest,
    TraceOverview,
    summarize_rows,
)

router = APIRouter(prefix="/trace", tags=["trace"])


def _decode_trace_id(trace_id: str) -> str:
    return urllib.parse.unquote(trace_id)


def _require_session(trace_id: str, analyzer: TraceAnalyzer) -> str:
    """Return resolved trace path; auto-load on cache miss."""
    trace_path = _decode_trace_id(trace_id)
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


def _sanitize_upload_filename(filename: str) -> str:
    """Keep only safe basename characters for uploaded trace files."""
    base = Path(filename).name
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return safe or f"trace_{int(time.time())}.perfetto"


# ── Load / Unload ─────────────────────────────────────────────────────────────

@router.post(
    "/load",
    response_model=TraceOverview,
    responses={400: {"model": ErrorResponse}},
    summary="Load a Perfetto trace file",
    description=(
        "Load a .perfetto or .pb trace file into the analysis engine. "
        "Returns a trace overview. Must be called before any other /trace/{trace_id}/* endpoint. "
        "The `trace_id` used in subsequent requests is the URL-encoded `trace_path`."
    ),
)
def load_trace(
    body: LoadTraceRequest,
    analyzer: TraceAnalyzer = Depends(get_analyzer),
) -> Any:
    try:
        loaded_path = analyzer.load(body.trace_path, body.process_name)
        overview = analyzer.overview(loaded_path)
        return overview
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/upload",
    response_model=TraceOverview,
    responses={400: {"model": ErrorResponse}},
    summary="Upload a local trace file and load it immediately",
    description=(
        "Accepts raw file bytes (`application/octet-stream`) and stores them under `/tmp/atrace/uploads/`, "
        "then loads the saved file into TraceAnalyzer. "
        "Use query params: `filename=<original-name>` and optional `process_name=<package>`."
    ),
)
def upload_trace(
    filename: str = Query(..., description="Original trace file name"),
    process_name: str | None = Query(None, description="Optional default process name"),
    payload: bytes = Body(..., media_type="application/octet-stream"),
    analyzer: TraceAnalyzer = Depends(get_analyzer),
) -> Any:
    if not payload:
        raise HTTPException(status_code=400, detail="Empty upload body")

    try:
        safe_name = _sanitize_upload_filename(filename)
        upload_dir = Path("/tmp/atrace/uploads")
        upload_dir.mkdir(parents=True, exist_ok=True)

        ts = int(time.time())
        save_path = upload_dir / f"{ts}_{safe_name}"
        save_path.write_bytes(payload)

        loaded_path = analyzer.load(str(save_path), process_name)
        overview = analyzer.overview(loaded_path)
        return overview
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/{trace_id:path}",
    summary="Close and unload a trace session",
)
def unload_trace(
    trace_id: str,
    analyzer: TraceAnalyzer = Depends(get_analyzer),
) -> dict[str, str]:
    trace_path = _decode_trace_id(trace_id)
    analyzer.close(trace_path)
    return {"status": "closed", "trace_path": trace_path}


# ── Overview ──────────────────────────────────────────────────────────────────

@router.get(
    "/{trace_id:path}/overview",
    response_model=TraceOverview,
    summary="Get trace overview",
)
def overview(
    trace_id: str,
    analyzer: TraceAnalyzer = Depends(get_analyzer),
) -> Any:
    abs_path = _require_session(trace_id, analyzer)
    return analyzer.overview(abs_path)


# ── SQL ───────────────────────────────────────────────────────────────────────

@router.post(
    "/{trace_id:path}/sql",
    response_model=SqlResponse,
    summary="Execute arbitrary PerfettoSQL",
    description=(
        "Run a custom SQL query against the loaded trace. "
        "Set `summarize=true` to get statistical aggregates instead of raw rows — "
        "useful when feeding results to an LLM to avoid context overflow."
    ),
)
def execute_sql(
    trace_id: str,
    body: SqlRequest,
    analyzer: TraceAnalyzer = Depends(get_analyzer),
) -> Any:
    abs_path = _require_session(trace_id, analyzer)
    try:
        rows = analyzer.query(abs_path, body.sql)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"SQL error: {exc}") from exc

    truncated = len(rows) > body.limit
    visible_rows = rows[: body.limit]

    summary: dict[str, Any] | None = None
    if body.summarize:
        summary = summarize_rows(rows, sample_size=10)

    return SqlResponse(
        row_count=len(rows),
        truncated=truncated,
        rows=visible_rows,
        summary=summary,
    )


# ── Slices ────────────────────────────────────────────────────────────────────

@router.post(
    "/{trace_id:path}/slices",
    summary="Query function call slices sorted by duration",
    description="Find slow functions. Supports filtering by process, thread, name pattern, duration.",
)
def query_slices(
    trace_id: str,
    body: SlicesRequest,
    analyzer: TraceAnalyzer = Depends(get_analyzer),
) -> Any:
    abs_path = _require_session(trace_id, analyzer)
    try:
        rows = analyzer.top_slices(
            abs_path,
            process=body.process,
            thread=body.thread,
            name_pattern=body.name_pattern,
            min_dur_ms=body.min_dur_ms,
            limit=body.limit,
            main_thread_only=body.main_thread_only,
        )
        return {"rows": rows, "count": len(rows)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/{trace_id:path}/slice/{slice_id}/children",
    response_model=SliceChildrenResponse,
    summary="Get direct children of a slice sorted by duration",
    description="Drill down into what a slow function is doing.",
)
def slice_children(
    trace_id: str,
    slice_id: int,
    limit: int = Query(20, ge=1, le=200),
    analyzer: TraceAnalyzer = Depends(get_analyzer),
) -> Any:
    abs_path = _require_session(trace_id, analyzer)
    try:
        children = analyzer.children(abs_path, slice_id, limit)
        return SliceChildrenResponse(slice_id=slice_id, children=children)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/{trace_id:path}/slice/{slice_id}/call-chain",
    response_model=CallChainResponse,
    summary="Get full ancestor chain for a slice",
    description="Trace upward from a specific slice to understand the call stack.",
)
def call_chain(
    trace_id: str,
    slice_id: int,
    analyzer: TraceAnalyzer = Depends(get_analyzer),
) -> Any:
    abs_path = _require_session(trace_id, analyzer)
    try:
        ancestors = analyzer.call_chain(abs_path, slice_id)
        return CallChainResponse(slice_id=slice_id, ancestors=ancestors)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── Thread States ─────────────────────────────────────────────────────────────

@router.post(
    "/{trace_id:path}/thread-states",
    summary="Analyze thread state distribution (Running / Sleeping / Blocked)",
    description=(
        "Understand if a thread is CPU-bound, IO-bound, or lock-contended. "
        "Useful for confirming hypotheses after finding a slow slice."
    ),
)
def thread_states(
    trace_id: str,
    body: ThreadStatesRequest,
    analyzer: TraceAnalyzer = Depends(get_analyzer),
) -> Any:
    abs_path = _require_session(trace_id, analyzer)
    try:
        rows = analyzer.thread_states(abs_path, body.thread_name, body.ts_start, body.ts_end)
        return {"thread_name": body.thread_name, "states": rows}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
