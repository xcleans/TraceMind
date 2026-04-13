"""
ATrace MCP Server — AI-driven Android performance analysis.

Slim entry point: sets up FastMCP, creates core objects,
delegates tool registration to tools/ subpackage.

Usage:
  python server.py                    # stdio mode (for Cursor/Claude Desktop)
  python server.py --transport http   # HTTP mode (for testing)
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from fastmcp import FastMCP

# Unified logging bootstrap
_repo_root = Path(__file__).resolve().parent.parent
_logging_path = _repo_root / "_logging.py"
if _logging_path.is_file():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from _logging import get_logger as _get_logger
    _get_logger("atrace.mcp", log_file="atrace-mcp.log")

from device_controller import DeviceController
from trace_analyzer import TraceAnalyzer
from prompts import register_prompts
from tools import register_all_tools

_log = logging.getLogger("atrace.mcp")
_log.info("atrace-mcp server starting, cwd=%s", os.getcwd())

mcp = FastMCP(
    name="ATrace",
    instructions="""You are an Android performance analysis agent.
You have tools to capture Perfetto traces, query them with SQL,
analyze startup/jank/memory issues, control tracing at runtime,
profile CPU with simpleperf, and profile heap memory with heapprofd.

Workflow:
1. Load a trace file with load_trace, or capture a new one with capture_trace
2. Use trace_overview to understand the high-level picture
3. Use query_slices / execute_sql to drill into specifics
4. Use analyze_startup / analyze_jank / analyze_scroll_performance for structured analysis

MCP Resources:
- atrace://configs/* — Perfetto scenario configs (.txtpb)
- atrace://perfetto-sql-reference — SQL tables + common queries
- atrace://sql-patterns — PerfettoSQL snippets

AI-driven Strategy:
- Jank / UI slowness → capture_trace + analyze_jank + query_slices
- Startup regression → capture_trace(cold_start=True) + analyze_startup
- Native CPU hotspot → capture_cpu_profile + report_cpu_profile + generate_flamegraph
- Memory leak / OOM → capture_heap_profile + analyze_heap_profile

Always start by understanding what process the user cares about.""",
)

analyzer = TraceAnalyzer()
controller = DeviceController()
register_prompts(mcp)
register_all_tools(mcp, analyzer, controller)


if __name__ == "__main__":
    transport = "stdio"
    if "--transport" in sys.argv:
        idx = sys.argv.index("--transport")
        if idx + 1 < len(sys.argv):
            transport = sys.argv[idx + 1]

    if transport == "http":
        mcp.run(transport="streamable-http", host="0.0.0.0", port=8090, show_banner=False)
    else:
        logging.getLogger("fastmcp").setLevel(logging.ERROR)
        logging.getLogger("mcp").setLevel(logging.ERROR)
        mcp.run(show_banner=False)
