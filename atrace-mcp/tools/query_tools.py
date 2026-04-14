"""Query tools — load, inspect, and SQL-query traces."""

from __future__ import annotations

import json
from typing import Any

from tools._helpers import (
    LOG,
    TRACE_VIEWER_HINT,
    log_tool_call,
    normalize_optional_process_name,
    normalize_trace_path_arg,
    require_trace_path,
    resolve_trace_path,
    safe_repr,
    validate_process,
)


def register_query_tools(mcp, analyzer) -> None:
    def _parse_payload_json(payload_json: str) -> tuple[dict[str, Any], str | None]:
        raw = (payload_json or '').strip()
        if not raw:
            return {}, None
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            return {}, f"payload_json is not valid JSON ({e})."
        if not isinstance(obj, dict):
            return {}, 'payload_json must be a JSON object.'
        return obj, None

    def _to_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _to_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            v = value.strip().lower()
            if v in {'1', 'true', 'yes', 'y', 'on'}:
                return True
            if v in {'0', 'false', 'no', 'n', 'off'}:
                return False
        return default

    def _load_trace_run(resolved: str, process_name: str | None, source: str | None) -> str:
        try:
            path = analyzer.load(resolved, process_name)
            overview = analyzer.overview(path)
            if source and source != 'argument':
                overview = {**overview, 'trace_path_source': source}
            return json.dumps(overview, indent=2, default=str)
        except Exception as e:
            LOG.exception('trace load failed path=%s', safe_repr(resolved, limit=400))
            msg = f'Error loading trace: {e}'
            if 'Trace processor' in str(e) or 'failed to start' in str(e).lower():
                msg += TRACE_VIEWER_HINT
            return msg

    @mcp.tool
    def load_trace(payload_json: str = '{}') -> str:
        """Load a Perfetto trace file for analysis.

        Args:
            payload_json: JSON string object.
                - trace_path: string, required when env/session cannot infer
                - process_name: string, optional default process

        Example:
            {"trace_path":"/tmp/a.perfetto","process_name":"com.example.app"}
        """
        log_tool_call('load_trace', payload_json=payload_json)
        obj, err = _parse_payload_json(payload_json)
        if err:
            return f'Error loading trace: {err}'
        trace_path = normalize_trace_path_arg(obj.get('trace_path'))
        process_name = normalize_optional_process_name(obj.get('process_name'))
        resolved, source = resolve_trace_path(trace_path, analyzer)
        if not resolved:
            return (
                'Error loading trace: missing required argument `trace_path`.\n'
                'Pass trace_path explicitly, or set env `ATRACE_DEFAULT_TRACE_PATH`, '
                'or ensure exactly one trace session is already loaded.'
            )
        return _load_trace_run(resolved, process_name, source)

    @mcp.tool
    def trace_overview(payload_json: str = '{}') -> str:
        """Get a high-level overview of a loaded trace.

        Args:
            payload_json: JSON string object.
                - trace_path: string, optional (fallback supported)

        Example:
            {"trace_path":"/tmp/a.perfetto"}
        """
        log_tool_call('trace_overview', payload_json=payload_json)
        obj, err_payload = _parse_payload_json(payload_json)
        if err_payload:
            return f'Error: {err_payload}'
        resolved, err = require_trace_path(obj.get('trace_path'), analyzer)
        if err:
            return err
        try:
            result = analyzer.overview(resolved)
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return f'Error: {e}'

    @mcp.tool
    def query_slices(payload_json: str = '{}') -> str:
        """Query function call slices from the trace.

        Args:
            payload_json: JSON string object.
                - trace_path: string, optional (fallback supported)
                - process: string, optional
                - thread: string, optional
                - name_pattern: string, optional
                - min_dur_ms: number, optional
                - limit: integer, optional
                - main_thread_only: boolean, optional
        """
        obj, err_payload = _parse_payload_json(payload_json)
        if err_payload:
            return f'Error: {err_payload}'
        trace_path = obj.get('trace_path')
        process = obj.get('process')
        thread = obj.get('thread')
        name_pattern = obj.get('name_pattern')
        min_dur_ms = _to_float(obj.get('min_dur_ms'), 0.0)
        limit = _to_int(obj.get('limit'), 20)
        main_thread_only = _to_bool(obj.get('main_thread_only'), False)
        log_tool_call(
            'query_slices',
            trace_path=trace_path,
            process=process,
            thread=thread,
            name_pattern=name_pattern,
            min_dur_ms=min_dur_ms,
            limit=limit,
            main_thread_only=main_thread_only,
        )
        resolved, err = require_trace_path(trace_path, analyzer)
        if err:
            return err
        process, proc_err = validate_process(process, analyzer, resolved)
        if proc_err:
            return proc_err
        try:
            rows = analyzer.top_slices(
                resolved,
                process=process,
                thread=thread,
                name_pattern=name_pattern,
                min_dur_ms=min_dur_ms,
                limit=limit,
                main_thread_only=main_thread_only,
            )
            return json.dumps(rows, indent=2, default=str)
        except Exception as e:
            return f'Error: {e}'

    @mcp.tool
    def execute_sql(payload_json: str = '{}') -> str:
        """Execute arbitrary PerfettoSQL.

        Args:
            payload_json: JSON string object.
                - trace_path: string, optional (fallback supported)
                - sql: string, required
        """
        obj, err_payload = _parse_payload_json(payload_json)
        if err_payload:
            return f'SQL Error: {err_payload}'
        trace_path = obj.get('trace_path')
        sql = str(obj.get('sql', '') or '')
        log_tool_call('execute_sql', trace_path=trace_path, sql=sql)
        if not sql.strip():
            return 'SQL Error: missing required argument `sql`.'
        resolved, err = require_trace_path(trace_path, analyzer)
        if err:
            return err
        try:
            rows = analyzer.query(resolved, sql)
            if len(rows) > 100:
                return json.dumps(
                    {'row_count': len(rows), 'rows': rows[:100], 'note': 'Truncated to 100 rows'},
                    indent=2,
                    default=str,
                )
            return json.dumps(rows, indent=2, default=str)
        except Exception as e:
            return f'SQL Error: {e}'

    @mcp.tool
    def call_chain(payload_json: str = '{}') -> str:
        """Get the call chain for a specific slice.

        Args:
            payload_json: JSON string object.
                - trace_path: string, optional (fallback supported)
                - slice_id: integer, required (>0)
        """
        obj, err_payload = _parse_payload_json(payload_json)
        if err_payload:
            return f'Error: {err_payload}'
        trace_path = obj.get('trace_path')
        slice_id = _to_int(obj.get('slice_id'), 0)
        log_tool_call('call_chain', trace_path=trace_path, slice_id=slice_id)
        if slice_id <= 0:
            return 'Error: missing or invalid required argument `slice_id`.'
        resolved, err = require_trace_path(trace_path, analyzer)
        if err:
            return err
        try:
            rows = analyzer.call_chain(resolved, slice_id)
            return json.dumps(rows, indent=2, default=str)
        except Exception as e:
            return f'Error: {e}'

    @mcp.tool
    def slice_children(payload_json: str = '{}') -> str:
        """Get direct children of a slice.

        Args:
            payload_json: JSON string object.
                - trace_path: string, optional (fallback supported)
                - slice_id: integer, required (>0)
                - limit: integer, optional
        """
        obj, err_payload = _parse_payload_json(payload_json)
        if err_payload:
            return f'Error: {err_payload}'
        trace_path = obj.get('trace_path')
        slice_id = _to_int(obj.get('slice_id'), 0)
        limit = _to_int(obj.get('limit'), 20)
        log_tool_call('slice_children', trace_path=trace_path, slice_id=slice_id, limit=limit)
        if slice_id <= 0:
            return 'Error: missing or invalid required argument `slice_id`.'
        resolved, err = require_trace_path(trace_path, analyzer)
        if err:
            return err
        try:
            rows = analyzer.children(resolved, slice_id, limit)
            return json.dumps(rows, indent=2, default=str)
        except Exception as e:
            return f'Error: {e}'

    @mcp.tool
    def thread_states(payload_json: str = '{}') -> str:
        """Analyze thread state distribution.

        Args:
            payload_json: JSON string object.
                - trace_path: string, optional (fallback supported)
                - thread_name: string, required
                - ts_start: integer, optional
                - ts_end: integer, optional
        """
        obj, err_payload = _parse_payload_json(payload_json)
        if err_payload:
            return f'Error: {err_payload}'
        trace_path = obj.get('trace_path')
        thread_name = str(obj.get('thread_name', '') or '')
        ts_start = _to_int(obj.get('ts_start'), 0)
        ts_end = _to_int(obj.get('ts_end'), 0)
        log_tool_call('thread_states', trace_path=trace_path, thread_name=thread_name, ts_start=ts_start, ts_end=ts_end)
        if not thread_name.strip():
            return 'Error: missing required argument `thread_name`.'
        resolved, err = require_trace_path(trace_path, analyzer)
        if err:
            return err
        try:
            rows = analyzer.thread_states(resolved, thread_name, ts_start=ts_start, ts_end=ts_end)
            return json.dumps(rows, indent=2, default=str)
        except Exception as e:
            return f'Error: {e}'
