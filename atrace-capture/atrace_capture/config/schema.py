"""Capture configuration schema — Pydantic models for structured config."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Action(BaseModel):
    """An action executed before, during, or after capture."""
    type: str                      # cold_start / hot_start / scroll / tap / wait / custom_adb
    params: dict[str, Any] = {}


class PerfettoConfig(BaseModel):
    """Perfetto-specific capture configuration."""
    template: str | None = None        # preset txtpb name (e.g. "startup")
    template_path: str | None = None   # explicit txtpb file path
    buffer_size_kb: int = 65536
    categories: list[str] = []
    extra_data_sources: list[dict[str, Any]] = []


class SimpleperfConfig(BaseModel):
    event: str = "cpu-cycles"
    frequency: int = 1000
    call_graph: str = "dwarf"


class HeapConfig(BaseModel):
    mode: str = "native"               # native | java-dump
    sampling_interval_bytes: int = 4096
    block_client: bool = True


class CaptureConfig(BaseModel):
    """Top-level capture configuration."""
    name: str = ""
    scenario: str = "general"          # startup / scroll / memory / animation / binder / general
    engine: str = "merged"             # merged / cpu / heap
    duration_sec: int = 10
    package: str | None = None

    perfetto: PerfettoConfig | None = None
    simpleperf: SimpleperfConfig | None = None
    heap: HeapConfig | None = None

    pre_actions: list[Action] = []
    capture_actions: list[Action] = []
    post_actions: list[Action] = []

    output_dir: str = "/tmp/atrace"

    @staticmethod
    def _resolve_template(name: str) -> str | None:
        """Resolve a template short name to an absolute config path."""
        try:
            import _monorepo
            return _monorepo.resolve_perfetto_config(name)
        except (ImportError, AttributeError):
            pass
        pkg_dir = Path(__file__).resolve().parent / "perfetto"
        for suffix in (f"{name}.txtpb", name):
            candidate = pkg_dir / suffix
            if candidate.is_file():
                return str(candidate)
        return None

    def to_engine_kwargs(self) -> dict[str, Any]:
        """Convert to keyword arguments suitable for EngineCLI methods."""
        base: dict[str, Any] = {}
        if self.package:
            base["package"] = self.package
        base["duration_s"] = self.duration_sec

        if self.engine == "merged":
            base["output_file"] = str(
                Path(self.output_dir) / f"{self.package or 'trace'}_{self.scenario}.perfetto"
            )
            if self.perfetto:
                config_path = self.perfetto.template_path
                if not config_path and self.perfetto.template:
                    config_path = self._resolve_template(self.perfetto.template)
                if config_path:
                    base["perfetto_config"] = config_path
                base["buffer_size"] = f"{self.perfetto.buffer_size_kb // 1024}mb"
        elif self.engine == "cpu":
            base["output_dir"] = self.output_dir
            if self.simpleperf:
                base["event"] = self.simpleperf.event
                base["freq"] = self.simpleperf.frequency
                base["call_graph"] = self.simpleperf.call_graph
        elif self.engine == "heap":
            base["output_file"] = str(
                Path(self.output_dir) / f"heap_{self.package or 'trace'}.perfetto"
            )
            if self.heap:
                base["mode"] = self.heap.mode
                base["sampling_bytes"] = self.heap.sampling_interval_bytes
                base["no_block"] = not self.heap.block_client

        return base
