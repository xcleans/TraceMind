"""CaptureEngine abstract base — unified contract for all capture backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CaptureHandle:
    """Opaque handle returned by ``CaptureEngine.start``."""
    engine_name: str
    trace_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CaptureResult:
    """Structured capture result."""
    success: bool
    trace_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"status": "success" if self.success else "error"}
        if self.trace_path:
            d["trace"] = str(self.trace_path)
        d.update(self.metadata)
        if self.error:
            d["error"] = self.error
        return d


class CaptureEngine(ABC):
    """Abstract contract for a capture backend.

    Implementations wrap a specific capture method (Perfetto system trace,
    app sampling merge, simpleperf CPU, heapprofd, etc.) behind a uniform
    interface.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Engine identifier (e.g. ``merged``, ``cpu``, ``heap``)."""

    @abstractmethod
    def capture(self, **kwargs: Any) -> CaptureResult:
        """Run the full capture lifecycle synchronously and return the result."""

    def supported_scenarios(self) -> list[str]:
        """Scenarios this engine is designed for (informational)."""
        return []
