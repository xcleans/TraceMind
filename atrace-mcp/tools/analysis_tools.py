"""Analysis tools — structured startup / jank / scroll analysis."""

from __future__ import annotations

import json
from typing import Any

from tools._helpers import log_tool_call, require_trace_path, validate_process


def register_analysis_tools(mcp, analyzer) -> None:
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

    @mcp.tool
    def analyze_startup(payload_json: str = '{}') -> str:
        """Analyze app cold startup performance.

        Args:
            payload_json: JSON string object.
                - trace_path: string, optional (fallback supported)
                - process: string, optional
        """
        obj, err_payload = _parse_payload_json(payload_json)
        if err_payload:
            return f'Error: {err_payload}'
        trace_path = obj.get('trace_path')
        process = obj.get('process')
        log_tool_call('analyze_startup', trace_path=trace_path, process=process)
        resolved, err = require_trace_path(trace_path, analyzer)
        if err:
            return err
        process, proc_err = validate_process(process, analyzer, resolved)
        if proc_err:
            return proc_err
        try:
            result = analyzer.analyze_startup(resolved, process)
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return f'Error: {e}'

    @mcp.tool
    def analyze_jank(payload_json: str = '{}') -> str:
        """Quick jank smoke-check for one trace.

        Args:
            payload_json: JSON string object.
                - trace_path: string, optional (fallback supported)
                - process: string, optional
        """
        obj, err_payload = _parse_payload_json(payload_json)
        if err_payload:
            return f'Error: {err_payload}'
        trace_path = obj.get('trace_path')
        process = obj.get('process')
        log_tool_call('analyze_jank', trace_path=trace_path, process=process)
        resolved, err = require_trace_path(trace_path, analyzer)
        if err:
            return err
        process, proc_err = validate_process(process, analyzer, resolved)
        if proc_err:
            return proc_err
        try:
            result = analyzer.analyze_jank(resolved, process)
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return f'Error: {e}'

    @mcp.tool
    def analyze_scroll_performance(payload_json: str = '{}') -> str:
        """Scroll smoothness analysis.

        Args:
            payload_json: JSON string object.
                - trace_path: string, optional (fallback supported)
                - process: string, optional
                - layer_name_hint: string, optional
        """
        obj, err_payload = _parse_payload_json(payload_json)
        if err_payload:
            return f'Error: {err_payload}'
        trace_path = obj.get('trace_path')
        process = obj.get('process')
        layer_name_hint = obj.get('layer_name_hint')
        log_tool_call('analyze_scroll_performance', trace_path=trace_path, process=process, layer_name_hint=layer_name_hint)
        resolved, err = require_trace_path(trace_path, analyzer)
        if err:
            return err
        process, proc_err = validate_process(process, analyzer, resolved)
        if proc_err:
            return proc_err
        try:
            result = analyzer.scroll_performance_metrics(
                resolved, process=process, layer_name_hint=layer_name_hint
            )
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return f'Error: {e}'
