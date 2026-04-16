"""atrace-provision — Tool provisioner for TraceMind.

Discover, download, and cache external binaries (simpleperf, perfetto,
traceconv, atrace-tool) needed by the capture and analysis layers.
"""

from atrace_provision.registry import ToolRegistry
from atrace_provision.providers.perfetto import PerfettoProvider
from atrace_provision.providers.simpleperf import SimpleperfProvider
from atrace_provision.providers.traceconv import TraceconvProvider
from atrace_provision.providers.atrace_tool import AtraceToolProvider
from atrace_provision.providers.simpleperf_toolkit import SimpleperfToolkitProvider

__all__ = [
    "ToolRegistry",
    "PerfettoProvider",
    "SimpleperfProvider",
    "TraceconvProvider",
    "AtraceToolProvider",
    "SimpleperfToolkitProvider",
]
