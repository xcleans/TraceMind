"""Capture router — select the appropriate engine based on configuration."""

from __future__ import annotations

from typing import Any

from atrace_capture.config.schema import CaptureConfig
from atrace_capture.engine import CaptureEngine, CaptureResult
from atrace_capture.engines.cpu import CpuCapture
from atrace_capture.engines.heap import HeapCapture
from atrace_capture.engines.merged import MergedCapture


class CaptureRouter:
    """Route a ``CaptureConfig`` to the correct ``CaptureEngine``."""

    def __init__(self, engine_cli: Any):
        self._engines: dict[str, CaptureEngine] = {
            "merged": MergedCapture(engine_cli),
            "cpu": CpuCapture(engine_cli),
            "heap": HeapCapture(engine_cli),
        }

    def register(self, engine: CaptureEngine) -> None:
        self._engines[engine.name] = engine

    def execute(self, config: CaptureConfig) -> CaptureResult:
        engine = self._engines.get(config.engine)
        if engine is None:
            return CaptureResult(
                success=False,
                error=f"Unknown engine: {config.engine}. "
                      f"Available: {list(self._engines.keys())}",
            )
        kwargs = config.to_engine_kwargs()
        return engine.capture(**kwargs)

    def available_engines(self) -> list[str]:
        return list(self._engines.keys())
