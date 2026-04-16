"""Thin re-export — implementation lives in ``atrace_capture.perfetto_viewer``."""

from atrace_capture.perfetto_viewer import (  # noqa: F401
    PerfettoOpenResult,
    build_perfetto_deep_link,
    open_trace_in_perfetto,
    PERFETTO_ORIGIN,
    PERFETTO_LOCALHOST_PORT,
)

# Backwards-compatible aliases used by query_tools before the rename.
PerfettoLocalOpenResult = PerfettoOpenResult
open_trace_via_local_http = open_trace_in_perfetto
