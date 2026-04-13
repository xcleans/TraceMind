"""CPU profiling capture engine — delegates to atrace-tool cpu."""

from __future__ import annotations

from typing import Any

from atrace_capture.engine import CaptureEngine, CaptureResult


class CpuCapture(CaptureEngine):
    """CPU profiling via ``atrace-tool cpu --json``."""

    def __init__(self, engine_cli: Any):
        self._cli = engine_cli

    @property
    def name(self) -> str:
        return "cpu"

    def supported_scenarios(self) -> list[str]:
        return ["cpu_profile"]

    def capture(self, **kwargs: Any) -> CaptureResult:
        result = self._cli.cpu(**kwargs)
        if result.success:
            from pathlib import Path
            perf_data = result.data.get("perf_data")
            return CaptureResult(
                success=True,
                trace_path=Path(perf_data) if perf_data else None,
                metadata={**result.data, "method": "atrace-tool cpu"},
            )
        return CaptureResult(
            success=False,
            error=result.data.get("message", result.message or "cpu capture failed"),
            metadata=result.data,
        )
