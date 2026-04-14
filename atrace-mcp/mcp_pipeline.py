"""MCP end-to-end tracing → ``log/atrace-mcp-pipeline.log`` (+ ``atrace-all.log``).

Records:
  - launch (transport, cwd, pid)
  - each tool handler **after** FastMCP/Pydantic validation (``tool_enter`` / ``tool_exit`` / ``tool_error``)

JSON-RPC and argument parsing happen inside the MCP stack; if the host sends ``{}`` or invalid
JSON, validation fails **before** ``tool_enter`` — use Cursor/client logs for that phase.
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

_repo_root = Path(__file__).resolve().parent.parent
_logging_path = _repo_root / "_logging.py"

log = logging.getLogger("atrace.mcp.pipeline")

_pipeline_file_installed = False


def _ensure_pipeline_file_logger() -> logging.Logger:
    global _pipeline_file_installed
    if not _pipeline_file_installed and _logging_path.is_file():
        if str(_repo_root) not in sys.path:
            sys.path.insert(0, str(_repo_root))
        try:
            from _logging import get_logger as _get_logger

            _get_logger("atrace.mcp.pipeline", log_file="atrace-mcp-pipeline.log")
            _pipeline_file_installed = True
        except Exception:
            pass
    return log


def _json_preview(obj: Any, limit: int = 6000) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        s = repr(obj)
    if len(s) > limit:
        return f"{s[: limit - 3]}..."
    return s


def _result_preview(out: Any, limit: int = 2000) -> str:
    if isinstance(out, str):
        s = out
    else:
        s = repr(out)
    s = s.replace("\n", "\\n")
    if len(s) > limit:
        return f"{s[: limit - 3]}..."
    return s


def _wrap_tool_fn(fn: Callable[..., Any]) -> Callable[..., Any]:
    tool_name = getattr(fn, "__name__", "tool")

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        pl = _ensure_pipeline_file_logger()
        t0 = time.monotonic()
        pl.info(
            "[pipeline] phase=tool_enter tool=%s pid=%s kwargs=%s",
            tool_name,
            os.getpid(),
            _json_preview(dict(kwargs)),
        )
        try:
            result = fn(*args, **kwargs)
            ms = (time.monotonic() - t0) * 1000.0
            pl.info(
                "[pipeline] phase=tool_exit tool=%s ms=%.2f ok=true result=%s",
                tool_name,
                ms,
                _result_preview(result),
            )
            return result
        except Exception:
            ms = (time.monotonic() - t0) * 1000.0
            pl.exception(
                "[pipeline] phase=tool_error tool=%s ms=%.2f",
                tool_name,
                ms,
            )
            raise

    return wrapper


def _is_payload_tool_signature(fn: Callable[..., Any]) -> bool:
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    if len(params) != 1:
        return False
    p = params[0]
    return p.name == "payload_json" and p.kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    )


def _parse_payload_dict(payload_json: Any, tool_name: str) -> tuple[dict[str, Any] | None, str | None]:
    if isinstance(payload_json, dict):
        return payload_json, None
    raw = "" if payload_json is None else str(payload_json).strip()
    if not raw:
        return {}, None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"Error: {tool_name} payload_json is not valid JSON ({e})."
    if not isinstance(obj, dict):
        return None, f"Error: {tool_name} payload_json must be a JSON object."
    return obj, None


def _make_payload_adapter(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Adapt a multi-arg tool fn to single-arg ``payload_json``."""
    if _is_payload_tool_signature(fn):
        return fn

    sig = inspect.signature(fn)
    params = [
        p
        for p in sig.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    ]
    tool_name = getattr(fn, "__name__", "tool")

    def adapted(payload_json: str = "{}") -> Any:
        payload, err = _parse_payload_dict(payload_json, tool_name)
        if err:
            return err
        assert payload is not None

        # Cursor sometimes wraps real arguments inside {"args": {...}}.
        nested_args = payload.get("args")
        if isinstance(nested_args, dict) and not any(p.name in payload for p in params):
            payload = nested_args

        call_kwargs: dict[str, Any] = {}
        missing: list[str] = []
        for p in params:
            if p.name in payload:
                call_kwargs[p.name] = payload[p.name]
            elif p.default is inspect._empty:
                missing.append(p.name)
        if missing:
            return (
                f"Error: {tool_name} missing required argument(s) in payload_json: "
                + ", ".join(missing)
            )
        return fn(**call_kwargs)

    adapted.__name__ = tool_name
    adapted.__qualname__ = getattr(fn, "__qualname__", tool_name)
    adapted.__doc__ = (
        f"(auto-adapted) Single-argument MCP wrapper.\n\n"
        f"Pass JSON string in payload_json, keys map to: {', '.join(p.name for p in params)}."
    )
    return adapted


_fastmcp_tool_orig = None


def install_fastmcp_tool_logging() -> None:
    """Patch ``FastMCP.tool`` so bare ``@mcp.tool`` handlers get pipeline tracing.

    Call after ``from fastmcp import FastMCP``, before registering tools. Idempotent.
    """
    global _fastmcp_tool_orig
    from fastmcp import FastMCP

    if _fastmcp_tool_orig is not None:
        return
    _fastmcp_tool_orig = FastMCP.tool

    def _patched_tool(self: Any, name_or_fn: Any = None, **kwargs: Any) -> Any:
        if callable(name_or_fn) and not kwargs:
            adapted = _make_payload_adapter(name_or_fn)
            return _fastmcp_tool_orig(self, _wrap_tool_fn(adapted))
        return _fastmcp_tool_orig(self, name_or_fn, **kwargs)

    FastMCP.tool = _patched_tool  # type: ignore[method-assign]


def log_mcp_launch(*, transport: str) -> None:
    pl = _ensure_pipeline_file_logger()
    pl.info(
        "[pipeline] phase=launch transport=%s cwd=%s pid=%s argv=%s",
        transport,
        os.getcwd(),
        os.getpid(),
        _json_preview(sys.argv, limit=800),
    )
