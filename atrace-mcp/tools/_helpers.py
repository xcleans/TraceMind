"""Shared helpers for MCP tool implementations."""

from __future__ import annotations

import functools
import json
import logging
import os
from pathlib import Path
from typing import Annotated, Any, Callable, Mapping

from pydantic import Field

LOG = logging.getLogger("atrace.mcp")

# --- MCP tool JSON hints -------------------------------------------------
# Cursor / other hosts parse tool ``arguments`` as JSON. Values like Android
# package ids contain dots; LLMs sometimes emit ``"process_name": com.foo.bar``
# without quotes, which is invalid JSON and fails with ``Unexpected token 'c'``.
# Publishing ``examples`` in the tool input schema reduces that failure mode.
_EXAMPLE_TRACE = "/tmp/trace.perfetto"
_EXAMPLE_PACKAGE = "com.example.app"

McpTracePath = Annotated[
    str,
    Field(
        description=(
            "Path to a .pb / .perfetto file. In tool JSON this MUST be a quoted string "
            f'(e.g. "{_EXAMPLE_TRACE}").'
        ),
        examples=[_EXAMPLE_TRACE],
    ),
]

McpOptionalTracePath = Annotated[
    str | None,
    Field(
        default=None,
        description=(
            "Optional trace path. If omitted, MCP will try fallback sources in order: "
            "ATRACE_DEFAULT_TRACE_PATH env → exactly one loaded trace session."
        ),
        examples=[_EXAMPLE_TRACE],
    ),
]

McpOptionalPackageId = Annotated[
    str | None,
    Field(
        default=None,
        description=(
            "Android applicationId / process name. When set, MUST be a JSON string "
            f'(e.g. "{_EXAMPLE_PACKAGE}"); never a bare dotted token.'
        ),
        examples=[_EXAMPLE_PACKAGE],
    ),
]

McpThreadName = Annotated[
    str,
    Field(
        description=(
            "Thread name substring. MUST be a JSON string "
            '(e.g. "com.example.app" or "RenderThread").'
        ),
        examples=["com.example.app", "RenderThread"],
    ),
]

TRACE_VIEWER_HINT = (
    "\n\n若需确认或分析该 trace：打开 https://ui.perfetto.dev → 点击 Open trace file "
    "（或拖拽文件到页面）→ 选择上述 trace 文件即可在浏览器中正确加载并查看。"
    "\n\n或在 MCP 中调用 `open_trace_in_perfetto_browser`（与 `record_android_trace` 相同："
    "本机 127.0.0.1:9001 临时 HTTP + CORS + `webbrowser` 打开 ui.perfetto.dev 深链）。"
)

_MIN_PROCESS_LEN = 3


def safe_repr(value: Any, limit: int = 400) -> str:
    try:
        text = repr(value)
    except Exception:
        text = f"<repr failed type={type(value)!r}>"
    if len(text) > limit:
        return f"{text[:limit - 3]}..."
    return text


def log_tool_call(tool_name: str, **kwargs: Any) -> None:
    """Log every MCP tool invocation with raw arguments."""
    args_str = ", ".join(f"{k}={safe_repr(v, 120)}" for k, v in kwargs.items())
    LOG.info("[tool-call===] %s(%s)", tool_name, args_str)


def validate_process(
    process: str | None,
    analyzer: Any,
    trace_path: str | None = None,
) -> tuple[str | None, str | None]:
    """Validate and resolve the process argument at the MCP layer.

    Returns (resolved_process, error_message).
    If error_message is not None the caller should return it directly.
    """
    if process is None:
        return None, None

    p = process.strip() if isinstance(process, str) else str(process).strip()
    if not p:
        return None, None

    if len(p) < _MIN_PROCESS_LEN:
        default = _default_process_from_session(analyzer, trace_path)
        if default and len(default) >= _MIN_PROCESS_LEN:
            LOG.warning(
                "[validate_process] process=%r too short, recovered default=%r",
                p, default,
            )
            return default, None
        LOG.error(
            "[validate_process] process=%r too short (<%d chars), "
            "no default available — rejecting",
            p, _MIN_PROCESS_LEN,
        )
        return None, (
            f'Error: process="{p}" 太短（<{_MIN_PROCESS_LEN} 字符），'
            f"会匹配到大量无关进程。请使用完整包名（如 com.example.app）。"
        )
    return p, None


def _default_process_from_session(analyzer: Any, trace_path: str | None) -> str | None:
    """Try to retrieve the default process name from a loaded trace session."""
    sessions: dict = getattr(analyzer, "_sessions", {})
    if trace_path and trace_path in sessions:
        sess = sessions[trace_path]
        return getattr(sess, "process_name", None) or sess.get("process_name") if isinstance(sess, dict) else getattr(sess, "process_name", None)
    if len(sessions) == 1:
        sess = next(iter(sessions.values()))
        return getattr(sess, "process_name", None) or (sess.get("process_name") if isinstance(sess, dict) else None)
    return None


def _maybe_get(mapping: Mapping[Any, Any], key: str) -> Any:
    try:
        return mapping[key]
    except Exception:
        for k, v in mapping.items():
            if isinstance(k, str) and k.lower() == key.lower():
                return v
        return None


def _try_fix_json(raw: str) -> str | None:
    """Attempt to fix common AI-generated JSON errors.

    Handles: unquoted string values, single quotes, trailing commas.
    """
    import re
    fixed = raw
    fixed = fixed.replace("'", '"')
    fixed = re.sub(r',\s*}', '}', fixed)
    fixed = re.sub(r',\s*]', ']', fixed)
    fixed = re.sub(
        r':\s*([a-zA-Z_/][a-zA-Z0-9_./ -]*)\s*([,}])',
        lambda m: f': "{m.group(1).strip()}"{m.group(2)}',
        fixed,
    )
    if fixed != raw:
        try:
            json.loads(fixed)
            LOG.info("[json-fix] repaired malformed JSON: %s → %s",
                     safe_repr(raw, 200), safe_repr(fixed, 200))
            return fixed
        except json.JSONDecodeError:
            pass
    return None


def normalize_trace_path_arg(trace_path: Any) -> str | None:
    if trace_path is None:
        return None
    if isinstance(trace_path, Path):
        return str(trace_path).strip() or None
    if isinstance(trace_path, Mapping):
        inner = (
            trace_path.get("trace_path")
            or trace_path.get("path")
            or _maybe_get(trace_path, "tracePath")
        )
        return normalize_trace_path_arg(inner)
    if not isinstance(trace_path, str):
        trace_path = str(trace_path)
    s = trace_path.strip()
    if not s:
        return None
    if s.startswith("{") and ("trace_path" in s or "path" in s):
        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                return normalize_trace_path_arg(obj)
        except json.JSONDecodeError as e:
            LOG.warning(
                "trace_path embedded JSON parse failed: %s | snippet=%s",
                e, safe_repr(s[:240], limit=240),
            )
            fixed = _try_fix_json(s)
            if fixed:
                try:
                    obj = json.loads(fixed)
                    if isinstance(obj, dict):
                        return normalize_trace_path_arg(obj)
                except json.JSONDecodeError:
                    pass
    return s


def normalize_optional_process_name(process_name: Any) -> str | None:
    if process_name is None:
        return None
    if isinstance(process_name, Mapping):
        inner = process_name.get("process_name") or _maybe_get(process_name, "process")
        return normalize_optional_process_name(inner)
    if not isinstance(process_name, str):
        process_name = str(process_name)
    s = process_name.strip()
    return s or None


def resolve_trace_path(trace_path: str | None, analyzer) -> tuple[str | None, str | None]:
    normalized = normalize_trace_path_arg(trace_path)
    if normalized:
        return normalized, "argument"
    env_hint = os.environ.get("ATRACE_DEFAULT_TRACE_PATH", "").strip()
    if env_hint:
        return env_hint, "env:ATRACE_DEFAULT_TRACE_PATH"
    loaded = list(getattr(analyzer, "_sessions", {}).keys())
    if len(loaded) == 1:
        return loaded[0], "loaded-session"
    return None, None


def require_trace_path(trace_path: str | None, analyzer) -> tuple[str | None, str | None]:
    resolved, source = resolve_trace_path(trace_path, analyzer)
    if resolved:
        LOG.debug("trace_path ok source=%s path=%s", source, safe_repr(resolved, limit=300))
        return resolved, None
    sessions = list(getattr(analyzer, "_sessions", {}).keys())
    LOG.warning(
        "trace_path missing: raw_type=%s raw=%s session_count=%s",
        type(trace_path).__name__, safe_repr(trace_path), len(sessions),
    )
    return None, (
        "Error: missing required argument `trace_path`.\n"
        "Pass `trace_path` explicitly, or set env `ATRACE_DEFAULT_TRACE_PATH`, "
        "or ensure exactly one trace session is already loaded."
    )
