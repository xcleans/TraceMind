"""Merged capture engine — system Perfetto + App ATrace sampling via atrace-tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from atrace_capture.engine import CaptureEngine, CaptureResult


class MergedCapture(CaptureEngine):
    """Delegates to ``atrace-tool capture --json`` for merged system + app trace."""

    def __init__(self, engine_cli: Any):
        self._cli = engine_cli

    @property
    def name(self) -> str:
        return "merged"

    def supported_scenarios(self) -> list[str]:
        return ["startup", "scroll", "animation", "binder", "general"]

    def capture(self, **kwargs: Any) -> CaptureResult:
        result = self._cli.capture(**kwargs)
        if result.success:
            trace_path = result.data.get("merged_trace") or result.data.get("output")
            app_trace = None
            if trace_path:
                candidate = Path(trace_path).parent / "app_trace.pb"
                if candidate.exists():
                    app_trace = str(candidate)
            return CaptureResult(
                success=True,
                trace_path=Path(trace_path) if trace_path else None,
                metadata={
                    **result.data,
                    "method": "atrace-tool capture",
                    **({"app_trace_pb": app_trace} if app_trace else {}),
                },
            )
        return CaptureResult(
            success=False,
            error=result.data.get("message", result.message or "capture failed"),
            metadata=result.data,
        )
