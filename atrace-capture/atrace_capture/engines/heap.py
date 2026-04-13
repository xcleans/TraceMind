"""Heap profiling capture engine — delegates to atrace-tool heap."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from atrace_capture.engine import CaptureEngine, CaptureResult


class HeapCapture(CaptureEngine):
    """Heap profiling via ``atrace-tool heap --json``."""

    def __init__(self, engine_cli: Any):
        self._cli = engine_cli

    @property
    def name(self) -> str:
        return "heap"

    def supported_scenarios(self) -> list[str]:
        return ["memory", "heap_native", "heap_java_dump"]

    def capture(self, **kwargs: Any) -> CaptureResult:
        result = self._cli.heap(**kwargs)
        if result.success:
            trace = result.data.get("trace") or result.data.get("output")
            return CaptureResult(
                success=True,
                trace_path=Path(trace) if trace else None,
                metadata={**result.data, "method": "atrace-tool heap"},
            )
        return CaptureResult(
            success=False,
            error=result.data.get("message", result.message or "heap capture failed"),
            metadata=result.data,
        )
