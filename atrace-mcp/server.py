"""
ATrace MCP Server — AI-driven Android performance analysis.

Provides tools for:
  1. Query: Load and analyze Perfetto traces with SQL
  2. Analyze: Pre-built startup/jank/memory analysis
  3. Control: Runtime trace capture and device interaction
  4. Explore: AI can iteratively drill down into performance issues

Usage:
  python server.py                    # stdio mode (for Cursor/Claude Desktop)
  python server.py --transport http   # HTTP mode (for testing)
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from device_controller import DeviceController
from trace_analyzer import TraceAnalyzer
from prompts import register_prompts
import tool_provisioner


def _spawn_scroll_during_capture(
    *,
    serial: str | None,
    delay_seconds: float,
    scroll_repeat: int,
    scroll_dy: int,
    scroll_duration_ms: int,
    scroll_start_x: int,
    scroll_start_y: int,
    scroll_end_x: int | None,
    scroll_end_y: int | None,
    scroll_pause_ms: int,
) -> None:
    """Fire-and-forget thread: wait, then ADB swipes (same semantics as replay_scenario scroll)."""

    def _worker() -> None:
        time.sleep(max(0.0, delay_seconds))
        ctrl = DeviceController(serial=serial)
        n = max(1, scroll_repeat)
        for i in range(n):
            ctrl.scroll_screen(
                duration_ms=max(1, scroll_duration_ms),
                dy=scroll_dy,
                start_x=scroll_start_x,
                start_y=scroll_start_y,
                end_x=scroll_end_x,
                end_y=scroll_end_y,
            )
            if i < n - 1:
                time.sleep(max(0, scroll_pause_ms) / 1000.0)

    threading.Thread(
        target=_worker,
        daemon=True,
        name="atrace-capture-inject-scroll",
    ).start()


mcp = FastMCP(
    name="ATrace",
    instructions="""You are an Android performance analysis agent.
You have tools to capture Perfetto traces, query them with SQL,
analyze startup/jank/memory issues, control tracing at runtime,
profile CPU with simpleperf, and profile heap memory with heapprofd.

═══ Workflow ═══
1. Load a trace file with load_trace, or capture a new one with capture_trace
2. capture_trace uses atrace-tool to produce a MERGED Perfetto trace:
   system trace (ftrace/sched/frametimeline/logcat) + app Java/native sampling
   → single .perfetto file fully queryable with PerfettoSQL
3. Use trace_overview to understand the high-level picture
4. Use query_slices / execute_sql to drill into specifics
5. Use analyze_startup / analyze_jank for structured analysis
6. If you need more data, use capture_trace with different parameters

═══ atrace-tool Setup ═══
capture_trace requires atrace-tool to be built. If not built, it falls back to
app-only capture (no Perfetto merge). To build:
  cd atrace-tool && ./gradlew installDist

═══ CPU Profiling (simpleperf) ═══
- capture_cpu_profile: Record native CPU call stacks via simpleperf
  → Best for: native crashes, JNI hot paths, C++ performance
  → Captures: per-function CPU time with full call stacks
- report_cpu_profile: Text report from perf.data (top functions by overhead)
- generate_flamegraph: SVG flamegraph from perf.data (requires NDK inferno.sh)

Simpleperf strategy:
- Start with capture_cpu_profile(package, duration_seconds=10)
- Use report_cpu_profile to identify the hottest functions
- Use generate_flamegraph for visual call-stack analysis
- event="cpu-cycles" for CPU hotspots, "task-clock" for wall-clock time
- call_graph="dwarf" for accuracy, "fp" for lower overhead

═══ Heap Memory Profiling (Perfetto) ═══
- capture_heap_profile: Native (heapprofd) or Java heap dump (java_hprof)
  → native: malloc/free callstack sampling, best for leaks/OOM/native growth
  → java-dump: full Java heap dump at trace end (retention graph)
  → https://perfetto.dev/docs/getting-started/memory-profiling
- analyze_heap_profile: SQL-based top allocator analysis (native traces)
  → If "Trace processor failed to start", open trace in ui.perfetto.dev

Requirements: Android 10+ (API 29+), app Profileable or Debuggable.
- capture_heap_profile(package, mode="native") or mode="java-dump"
- analyze_heap_profile(trace_path) for native flamegraph / top allocators

═══ ATrace Runtime Control ═══
- pause_tracing / resume_tracing: pause/resume sampling without overhead
- list_plugins / toggle_plugin: binder/gc/lock/io/alloc/jni/loadlib/msgqueue
- get_sampling_config / set_sampling_interval: tune precision vs overhead
- query_threads: enumerate app threads (requires ATrace HTTP)
- list_process_threads: list threads by package via ADB (no ATrace needed)
- add_trace_mark: inject labeled markers into the running trace
- capture_stack: force an immediate stack capture

═══ AI-driven Strategy ═══
- Jank / UI slowness → capture_trace + analyze_jank + query_slices
- Startup regression → capture_trace(cold_start=True) + analyze_startup
- Native CPU hotspot → capture_cpu_profile + report_cpu_profile + generate_flamegraph
- Memory leak / OOM → capture_heap_profile + analyze_heap_profile
- Binder bottleneck → toggle_plugin("binder", True) + capture_trace
- If overhead too high → set_sampling_interval to increase intervals

Common PerfettoSQL tables: slice, thread, process, counter, thread_state, sched,
heap_profile_allocation, experimental_flamegraph.

When load_trace or analyze_heap_profile fail with "Trace processor failed to start",
suggest the user open the trace file in https://ui.perfetto.dev (Open trace file);
the file is often still valid and viewable there.

Always start by understanding what process the user cares about.""",
)

analyzer = TraceAnalyzer()
controller = DeviceController()
register_prompts(mcp)

# 当本机 Trace Processor 无法解析 trace 时，提示用户在浏览器中打开（trace 可能仍有效）
TRACE_VIEWER_HINT = (
    "\n\n若需确认或分析该 trace：打开 https://ui.perfetto.dev → 点击 Open trace file "
    "（或拖拽文件到页面）→ 选择上述 trace 文件即可在浏览器中正确加载并查看。"
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Query Tools — Observe and explore trace data
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@mcp.tool
def load_trace(trace_path: str, process_name: str | None = None) -> str:
    """Load a Perfetto trace file for analysis.
    Must be called before using other query/analysis tools.

    Args:
        trace_path: Path to .pb or .perfetto trace file
        process_name: Optional default process name for subsequent queries
    """
    try:
        path = analyzer.load(trace_path, process_name)
        overview = analyzer.overview(path)
        return json.dumps(overview, indent=2, default=str)
    except Exception as e:
        msg = f"Error loading trace: {e}"
        if "Trace processor" in str(e) or "failed to start" in str(e).lower():
            msg += TRACE_VIEWER_HINT
        return msg


@mcp.tool
def trace_overview(trace_path: str) -> str:
    """Get a high-level overview of a loaded trace:
    duration, process list, thread count, slice count.

    Args:
        trace_path: Path to the loaded trace file
    """
    try:
        result = analyzer.overview(trace_path)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def query_slices(
    trace_path: str,
    process: str | None = None,
    thread: str | None = None,
    name_pattern: str | None = None,
    min_dur_ms: float = 0,
    limit: int = 20,
) -> str:
    """Query function call slices from the trace, sorted by duration.
    Use this to find slow functions.

    Args:
        trace_path: Path to the loaded trace file
        process: Filter by process name (supports wildcards)
        thread: Filter by thread name (e.g. "main")
        name_pattern: Filter by slice name pattern (e.g. "onCreate")
        min_dur_ms: Minimum duration in milliseconds
        limit: Max results (default 20)
    """
    try:
        rows = analyzer.top_slices(
            trace_path, process, thread, name_pattern, min_dur_ms, limit
        )
        return json.dumps(rows, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def execute_sql(trace_path: str, sql: str) -> str:
    """Execute arbitrary PerfettoSQL on a loaded trace.
    Use this for custom exploration when pre-built tools aren't enough.

    Common tables:
      - slice: function call spans (name, dur, ts, track_id, depth, parent_id)
      - thread: thread metadata (utid, tid, name, upid, is_main_thread)
      - process: process metadata (upid, pid, name)
      - thread_track: maps tracks to threads
      - thread_state: thread scheduling states (Running/Sleeping/Blocked)
      - counter: time-series counters (CPU freq, memory, etc.)
      - sched: kernel scheduling events

    Tips:
      - Join slice → thread_track → thread → process for full context
      - dur is in nanoseconds, divide by 1e6 for milliseconds
      - Use LIKE for pattern matching on names

    Args:
        trace_path: Path to the loaded trace file
        sql: PerfettoSQL query string
    """
    try:
        rows = analyzer.query(trace_path, sql)
        if len(rows) > 100:
            return json.dumps(
                {"row_count": len(rows), "rows": rows[:100],
                 "note": "Truncated to 100 rows"},
                indent=2, default=str,
            )
        return json.dumps(rows, indent=2, default=str)
    except Exception as e:
        return f"SQL Error: {e}"


@mcp.tool
def call_chain(trace_path: str, slice_id: int) -> str:
    """Get the full call chain (ancestors) for a specific slice.
    Use after finding an interesting slice via query_slices.

    Args:
        trace_path: Path to the loaded trace file
        slice_id: The slice ID to trace upward from
    """
    try:
        rows = analyzer.call_chain(trace_path, slice_id)
        return json.dumps(rows, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def slice_children(trace_path: str, slice_id: int, limit: int = 20) -> str:
    """Get direct children of a slice, sorted by duration.
    Use to drill down into what a slow function is doing.

    Args:
        trace_path: Path to the loaded trace file
        slice_id: Parent slice ID
        limit: Max results (default 20)
    """
    try:
        rows = analyzer.children(trace_path, slice_id, limit)
        return json.dumps(rows, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def thread_states(
    trace_path: str,
    thread_name: str,
    ts_start: int = 0,
    ts_end: int = 0,
) -> str:
    """Analyze thread state distribution (Running/Sleeping/Blocked).
    Use to understand if a thread is CPU-bound, IO-bound, or lock-contended.

    Args:
        trace_path: Path to the loaded trace file
        thread_name: Thread name to analyze
        ts_start: Optional start timestamp (nanoseconds)
        ts_end: Optional end timestamp (nanoseconds)
    """
    try:
        rows = analyzer.thread_states(trace_path, thread_name, ts_start, ts_end)
        return json.dumps(rows, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Analysis Tools — Pre-built structured analysis
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@mcp.tool
def analyze_startup(trace_path: str, process: str | None = None) -> str:
    """Analyze app cold startup performance.
    Returns top slow functions, blocking calls, and startup phases.

    Args:
        trace_path: Path to the loaded trace file
        process: Process name (uses default if not specified)
    """
    try:
        result = analyzer.analyze_startup(trace_path, process)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def analyze_jank(trace_path: str, process: str | None = None) -> str:
    """Quick jank smoke-check for one trace.

    What it does:
      - Detects obvious jank frames (legacy threshold around >16.6ms)
      - Returns long main-thread operations for fast triage

    When to use:
      - Use as a fast first pass when you only need "is there clear jank?"
      - Use for startup/general traces without full scroll-quality reporting

    When NOT to use as the only source:
      - If you need precise frame over-budget stats (60/90/120Hz)
      - If you need jank-type distribution (FrameTimeline categories)
      In those cases, prefer analyze_scroll_performance (and optional SQL).

    Args:
        trace_path: Path to the loaded trace file
        process: Process name (uses default if not specified)
    """
    try:
        result = analyzer.analyze_jank(trace_path, process)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def analyze_scroll_performance(
    trace_path: str,
    process: str | None = None,
    layer_name_hint: str | None = None,
) -> str:
    """Primary tool for scroll smoothness and precise frame-quality analysis.

    Returns structured data covering:
      • frame_quality  — FrameTimeline jank-type/tag distribution + % (No Jank / Buffer Stuffing /
                         App Deadline Missed / Self Jank / Late Present)
      • frame_duration — P50 / P90 / P95 / P99 / max frame durations (ms) from actual_frame_timeline_slice
      • worst_frames   — Top-10 slowest frames with jank context
      • main_thread_top — Top-N slowest meaningful slices on main thread (idle-wait excluded)
      • compose_slices  — Recomposer / compose:lazy:prefetch per-name call count, avg/max/total ms
      • blocking_calls  — Binder / Lock / GC / IO on main thread ≥ 2ms (grouped + summed)
      • verdict         — Machine-readable summary: no_jank_pct, p95_frame_ms, assessment
                          (excellent ≥95% / good ≥85% / fair ≥70% / poor)

    Default recommendation:
      - For scroll/jank diagnostics, call this tool first.
      - This is the preferred tool for "precise over-frame count + jank types".

    Use this tool to:
      1. Get a single-shot scroll quality snapshot for one trace.
      2. Compare two traces (baseline vs optimised) by diffing their `verdict` dicts.
      3. Feed the `verdict` into a report or CI gate.

    Args:
        trace_path:       Path to .pb / .perfetto trace (must be loaded first with load_trace)
        process:          App package name (e.g. com.example.app); uses session default if omitted
        layer_name_hint:  Substring to match the FrameTimeline layer (e.g. "MainActivity").
                          Auto-detected from process name if omitted.
    """
    try:
        result = analyzer.scroll_performance_metrics(
            trace_path, process, layer_name_hint
        )
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Control Tools — Runtime trace capture and device interaction
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@mcp.tool
def list_devices() -> str:
    """List connected Android devices via ADB."""
    try:
        devices = controller.list_devices()
        if not devices:
            return "No devices connected. Connect a device via USB or WiFi ADB."
        info_list = []
        for serial in devices:
            controller.serial = serial
            info = controller.get_device_info()
            info["serial"] = serial
            info_list.append(info)
        return json.dumps(info_list, indent=2)
    except Exception as e:
        return f"Error: {e}"


def _require_http(ctrl: DeviceController) -> dict | None:
    """Return a structured error dict if the ATrace HTTP server is not reachable, else None.

    Call this at the start of every MCP tool that depends on the app HTTP server.
    Pattern::

        ctrl = DeviceController(serial=serial, port=port, package=package)
        if err := _require_http(ctrl):
            return json.dumps(err, indent=2)
        ...
    """
    if not ctrl.check_http_reachable():
        return ctrl.not_reachable_error()
    return None


@mcp.tool
def query_app_status(
    package: str | None = None,
    serial: str | None = None,
    port: int = 9090,
) -> str:
    """Query the ATrace-instrumented app's current status.
    Shows whether tracing is active, buffer usage, enabled plugins, etc.

    Requires atrace-core to be integrated and ATrace.init() called in the app.
    If the HTTP server is not reachable, returns a structured error with setup hints.

    Args:
        package: App package name — used to discover the actual HTTP port via
                 ContentProvider (content://<package>.atrace/atrace/port).
                 Required for release builds; optional for debug where port is fixed.
        serial: Device serial (optional if single device)
        port: Local ADB-forwarded port to reach the app (default 9090)
    """
    try:
        ctrl = DeviceController(serial=serial, port=port, package=package)
        if err := _require_http(ctrl):
            return json.dumps(err, indent=2)
        status = ctrl.app_status()
        debug = ctrl.app_debug_info()
        return json.dumps({"status": status, "debug": debug}, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def capture_trace(
    package: str,
    duration_seconds: int = 10,
    output_dir: str = "/tmp/atrace",
    serial: str | None = None,
    port: int = 9090,
    cold_start: bool = False,
    activity: str | None = None,
    perfetto_config: str | None = None,
    proguard_mapping: str | None = None,
    buffer_size: str = "64mb",
    # ── optional: inject vertical swipes while capture runs (page already open) ──
    inject_scroll: bool = False,
    scroll_start_delay_seconds: float = 1.5,
    scroll_repeat: int = 5,
    scroll_dy: int = 600,
    scroll_duration_ms: int = 200,
    scroll_start_x: int = 540,
    scroll_start_y: int = 1200,
    scroll_end_x: int | None = None,
    scroll_end_y: int | None = None,
    scroll_pause_ms: int = 300,
) -> str:
    """Capture a unified performance trace merging Perfetto system trace and ATrace app sampling.

    Uses atrace-tool for the complete pipeline:
      1. Starts Perfetto system trace via record_android_trace:
           ftrace (sched/freq/binder), android slices, SurfaceFlinger frametimeline,
           logcat, process stats, sys_stats (CPU/mem counters)
      2. Connects to ATrace SDK HTTP server → starts Java/native stack sampling
      3. Waits for duration_seconds
      4. Stops both traces and downloads ATrace sampling data (ATRC binary format)
      5. Decodes ATRC → Perfetto proto packets (preserving call trees, CPU time,
         block time, alloc stats, message IDs) and appends to system trace
      6. Auto-loads the merged .perfetto file for SQL analysis

    The merged trace can be queried with all standard PerfettoSQL tables:
    slice, thread, process, thread_state, sched, counter, actual_frame_timeline_slice, etc.

    Falls back to app-only capture (no Perfetto merge) if atrace-tool is not built.
    Build atrace-tool: cd atrace-tool && ./gradlew installDist

    Args:
        package: App package name (e.g. "com.example.app")
        duration_seconds: Trace duration in seconds (default 10)
        output_dir: Local directory to save trace files
        serial: ADB device serial (optional if single device connected)
        port: ATrace HTTP server port (default 9090)
        cold_start: Force-stop and relaunch app before tracing (-r flag)
        activity: Launch activity for cold start (e.g. ".MainActivity")
        perfetto_config: Path to custom Perfetto config .txtpb file (-c flag).
                         If omitted, a rich default config is auto-generated.
        proguard_mapping: Path to Proguard mapping.txt for deobfuscation (-m flag)
        buffer_size: Perfetto ring buffer size, e.g. "64mb", "128mb" (default "64mb")

        inject_scroll: If True, run ADB swipes in a background thread after
            scroll_start_delay_seconds so scroll/jank is recorded inside the capture window.
            Use when the target screen is already open (set cold_start=False).
            Same coordinate rules as replay_scenario (scroll_end_x/y must both be set or both omitted).
        scroll_start_delay_seconds: Seconds to wait after capture begins before first swipe
        scroll_repeat / scroll_dy / scroll_duration_ms / scroll_start_x/y / scroll_end_x/y /
        scroll_pause_ms: Same as replay_scenario "scroll" scenario
    """
    try:
        import time as _time
        ts = int(_time.time())
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        output_file = str(out / f"{package}_{ts}.perfetto")

        if inject_scroll and (scroll_end_x is None) ^ (scroll_end_y is None):
            return json.dumps(
                {
                    "error": "inject_scroll: scroll_end_x and scroll_end_y must both be set "
                    "together, or omit both to use scroll_dy mode",
                    "package": package,
                },
                indent=2,
            )

        inject_meta: dict[str, Any] | None = None
        if inject_scroll:
            inject_meta = {
                "inject_scroll": True,
                "scroll_start_delay_seconds": scroll_start_delay_seconds,
                "scroll_repeat": max(1, scroll_repeat),
                "scroll_mode": "explicit_end"
                if scroll_end_x is not None and scroll_end_y is not None
                else "dy",
            }

        # ── Path A: atrace-tool available → full system + app merged pipeline ──
        # Port discovery is handled by atrace-tool itself; package is passed via CLI args.
        atrace_tool_cmd = tool_provisioner.ensure_atrace_tool()
        if atrace_tool_cmd:
            ctrl = DeviceController(serial=serial, port=port, package=package)
            if inject_scroll:
                _spawn_scroll_during_capture(
                    serial=serial,
                    delay_seconds=scroll_start_delay_seconds,
                    scroll_repeat=scroll_repeat,
                    scroll_dy=scroll_dy,
                    scroll_duration_ms=scroll_duration_ms,
                    scroll_start_x=scroll_start_x,
                    scroll_start_y=scroll_start_y,
                    scroll_end_x=scroll_end_x,
                    scroll_end_y=scroll_end_y,
                    scroll_pause_ms=scroll_pause_ms,
                )
            result = ctrl.run_atrace_tool(
                atrace_tool_cmd=atrace_tool_cmd,
                package=package,
                duration_s=duration_seconds,
                output_file=output_file,
                cold_start=cold_start,
                activity=activity,
                port=port,
                perfetto_config=perfetto_config,
                proguard_mapping=proguard_mapping,
                buffer_size=buffer_size,
            )

            # atrace-tool --json uses status/message (not a top-level "error" key)
            if result.get("status") != "success":
                return json.dumps({
                    **result,
                    "build_hint": tool_provisioner.atrace_tool_build_hint(),
                }, indent=2, default=str)

            merged_path = result.get("merged_trace")
            if not merged_path:
                return json.dumps(
                    {
                        "status": "error",
                        "message": "capture succeeded but merged_trace missing in JSON",
                        "raw": result,
                        "build_hint": tool_provisioner.atrace_tool_build_hint(),
                    },
                    indent=2,
                    default=str,
                )

            # Load into TraceAnalyzer for subsequent SQL queries
            try:
                analyzer.load(merged_path, process_name=package)
                overview = analyzer.overview(merged_path)
            except Exception as load_err:
                overview = {"error": str(load_err), "hint": TRACE_VIEWER_HINT}

            payload: dict[str, Any] = {
                "status": "success",
                "method": "atrace-tool (Perfetto system trace + ATrace app sampling merged)",
                "merged_trace": merged_path,
                "size_kb": result["size_kb"],
                "overview": overview,
                "separate_files": {
                    k: v for k, v in result.items()
                    if k in ("app_trace_pb", "app_trace_kb")
                },
                "hint": (
                    "Merged Perfetto trace loaded and ready for analysis.\n"
                    "  • query_slices — find slow functions\n"
                    "  • analyze_startup / analyze_jank — structured analysis\n"
                    "  • execute_sql — PerfettoSQL on all tables (slice, thread_state,\n"
                    "    actual_frame_timeline_slice, counter, sched, …)\n"
                    "  • trace_viewer_hint — open in ui.perfetto.dev"
                ),
            }
            if inject_meta is not None:
                payload["inject_scroll_meta"] = inject_meta
            return json.dumps(payload, indent=2, default=str)

    except Exception as e:
        return f"Error capturing trace: {e}"


@mcp.tool
def pause_tracing(
    package: str | None = None,
    serial: str | None = None,
    port: int = 9090,
) -> str:
    """Pause sampling without uninstalling hooks.
    The app continues running normally but no samples are collected.
    Use resume_tracing to continue. Useful for reducing overhead during
    non-interesting periods.

    Args:
        package: App package name for ContentProvider port discovery (release builds)
        serial: Device serial (optional if single device)
        port: ATrace HTTP port (default 9090)
    """
    try:
        ctrl = DeviceController(serial=serial, port=port, package=package)
        if err := _require_http(ctrl):
            return json.dumps(err, indent=2)
        result = ctrl.pause_trace()
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def resume_tracing(
    package: str | None = None,
    serial: str | None = None,
    port: int = 9090,
) -> str:
    """Resume sampling after a pause. Hooks remain installed so
    resume is instant (no reinstall overhead).

    Args:
        package: App package name for ContentProvider port discovery (release builds)
        serial: Device serial (optional if single device)
        port: ATrace HTTP port (default 9090)
    """
    try:
        ctrl = DeviceController(serial=serial, port=port, package=package)
        if err := _require_http(ctrl):
            return json.dumps(err, indent=2)
        result = ctrl.resume_trace()
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def list_plugins(
    package: str | None = None,
    serial: str | None = None,
    port: int = 9090,
) -> str:
    """List all loaded trace plugins and their current state.
    Each plugin represents a category of hooks (binder, gc, lock, io, etc.).

    Args:
        package: App package name for ContentProvider port discovery (release builds)
        serial: Device serial (optional if single device)
        port: ATrace HTTP port (default 9090)
    """
    try:
        ctrl = DeviceController(serial=serial, port=port, package=package)
        if err := _require_http(ctrl):
            return json.dumps(err, indent=2)
        result = ctrl.list_plugins()
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def toggle_plugin(
    plugin_id: str,
    enable: bool,
    package: str | None = None,
    serial: str | None = None,
    port: int = 9090,
) -> str:
    """Enable or disable a specific trace plugin at runtime.
    This toggles the plugin's hook callbacks without reinstalling hooks.

    Available plugins: binder, gc, lock, jni, loadlib, alloc, msgqueue, io

    Args:
        plugin_id: Plugin ID (e.g. "binder", "gc", "lock", "io")
        enable: True to enable, False to disable
        package: App package name for ContentProvider port discovery (release builds)
        serial: Device serial (optional)
        port: ATrace HTTP port (default 9090)
    """
    try:
        ctrl = DeviceController(serial=serial, port=port, package=package)
        if err := _require_http(ctrl):
            return json.dumps(err, indent=2)
        result = ctrl.toggle_plugin(plugin_id, enable)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def get_sampling_config(
    package: str | None = None,
    serial: str | None = None,
    port: int = 9090,
) -> str:
    """Get current sampling interval configuration.
    Returns main thread and other thread sampling intervals in nanoseconds.

    Args:
        package: App package name for ContentProvider port discovery (release builds)
        serial: Device serial (optional)
        port: ATrace HTTP port (default 9090)
    """
    try:
        ctrl = DeviceController(serial=serial, port=port, package=package)
        if err := _require_http(ctrl):
            return json.dumps(err, indent=2)
        result = ctrl.get_sampling_config()
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def set_sampling_interval(
    main_interval_ns: int = 0,
    other_interval_ns: int = 0,
    package: str | None = None,
    serial: str | None = None,
    port: int = 9090,
) -> str:
    """Dynamically adjust sampling intervals at runtime.
    Lower intervals = more detail but higher overhead.
    Higher intervals = less overhead but coarser data.

    Common values:
      - 500,000 ns (0.5ms) — high detail, ~5% overhead
      - 1,000,000 ns (1ms) — default, ~2% overhead
      - 5,000,000 ns (5ms) — low overhead
      - 10,000,000 ns (10ms) — minimal overhead

    Args:
        main_interval_ns: Main thread interval in nanoseconds (0 = no change)
        other_interval_ns: Other threads interval in nanoseconds (0 = no change)
        serial: Device serial (optional)
        port: ATrace HTTP port (default 9090)
    """
    try:
        ctrl = DeviceController(serial=serial, port=port, package=package)
        if err := _require_http(ctrl):
            return json.dumps(err, indent=2)
        result = ctrl.set_sampling_interval(main_interval_ns, other_interval_ns)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def list_watch_patterns(
    package: str | None = None,
    serial: str | None = None,
    port: int = 9090,
) -> str:
    """List ArtMethod WatchList substring patterns (runtime-configured).
    Matches against ART PrettyMethod strings when invoke-stub hook fires.

    Args:
        package: App package name for ContentProvider port discovery (release builds)
        serial: Device serial (optional)
        port: ATrace HTTP port (default 9090)
    """
    try:
        ctrl = DeviceController(serial=serial, port=port, package=package)
        if err := _require_http(ctrl):
            return json.dumps(err, indent=2)
        result = ctrl.list_watch_patterns()
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def add_watch_rule(
    scope: str,
    value: str,
    package: str | None = None,
    serial: str | None = None,
    port: int = 9090,
) -> str:
    """Add one semantic WatchList rule (parsed against PrettyMethod FQCN).

    Args:
        scope: package | class | method | substring
        value: package prefix (e.g. com.third.), FQCN, or Fqcn.methodName
        package: App package name for ContentProvider port discovery (release builds)
        serial: Device serial (optional)
        port: ATrace HTTP port (default 9090)
    """
    try:
        ctrl = DeviceController(serial=serial, port=port, package=package)
        if err := _require_http(ctrl):
            return json.dumps(err, indent=2)
        result = ctrl.add_watch_rule(scope, value)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def add_watch_entries(
    entries: str,
    package: str | None = None,
    serial: str | None = None,
    port: int = 9090,
) -> str:
    """Batch semantic rules: scope:value pairs separated by |.
    Example: package:com.sdk.|class:com.sdk.Foo|method:com.sdk.Foo.bar

    Args:
        entries: Pipe-separated scope:value segments
        package: App package name for ContentProvider port discovery (release builds)
        serial: Device serial (optional)
        port: ATrace HTTP port (default 9090)
    """
    try:
        ctrl = DeviceController(serial=serial, port=port, package=package)
        if err := _require_http(ctrl):
            return json.dumps(err, indent=2)
        result = ctrl.add_watch_entries(entries)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def add_watch_patterns(
    patterns: list[str],
    scope: str | None = None,
    package: str | None = None,
    serial: str | None = None,
    port: int = 9090,
) -> str:
    """Add WatchList patterns. Default: substring match each string on PrettyMethod.
    If scope is set (package/class/method/substring), each pattern is interpreted as
    the value for that scope (multiple HTTP rules in one call).

    Args:
        patterns: Non-empty strings
        scope: Optional package | class | method | substring
        package: App package name for ContentProvider port discovery (release builds)
        serial: Device serial (optional)
        port: ATrace HTTP port (default 9090)
    """
    try:
        ctrl = DeviceController(serial=serial, port=port, package=package)
        if err := _require_http(ctrl):
            return json.dumps(err, indent=2)
        result = ctrl.add_watch_patterns(patterns, scope=scope)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def remove_watch_pattern(
    pattern: str,
    package: str | None = None,
    serial: str | None = None,
    port: int = 9090,
) -> str:
    """Remove one WatchList entry by legacy substring or raw storage key (e.g. pkg:com.a.)."""
    try:
        ctrl = DeviceController(serial=serial, port=port, package=package)
        if err := _require_http(ctrl):
            return json.dumps(err, indent=2)
        result = ctrl.remove_watch_pattern(pattern)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def remove_watch_entry(
    entry: str | None = None,
    scope: str | None = None,
    value: str | None = None,
    package: str | None = None,
    serial: str | None = None,
    port: int = 9090,
) -> str:
    """Remove a watch rule by storage key (entry=pkg:...) or scope+value (same as add)."""
    try:
        ctrl = DeviceController(serial=serial, port=port, package=package)
        if err := _require_http(ctrl):
            return json.dumps(err, indent=2)
        result = ctrl.remove_watch_entry(entry=entry, scope=scope, value=value)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def clear_watch_patterns(
    package: str | None = None,
    serial: str | None = None,
    port: int = 9090,
) -> str:
    """Clear all ArtMethod WatchList patterns.

    Args:
        package: App package name for ContentProvider port discovery (release builds)
        serial: Device serial (optional)
        port: ATrace HTTP port (default 9090)
    """
    try:
        ctrl = DeviceController(serial=serial, port=port, package=package)
        if err := _require_http(ctrl):
            return json.dumps(err, indent=2)
        result = ctrl.clear_watch_patterns()
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def hook_method(
    class_name: str,
    method_name: str,
    signature: str,
    is_static: bool = False,
    package: str | None = None,
    serial: str | None = None,
    port: int = 9090,
) -> str:
    """Hook a specific Java method by replacing its entry_point_from_quick_compiled_code_.
    Method entry will be recorded as a SectionBegin event in the trace (tag: ArtHook:methodName).
    Works for both native and non-native methods on all devices (no ShadowHook dependency).

    Args:
        class_name: JNI class name (e.g. "com/example/Foo")
        method_name: Method name (e.g. "onCreate")
        signature: JNI method signature (e.g. "(Landroid/os/Bundle;)V")
        is_static: Whether the method is static (default False)
        package: App package name for ContentProvider port discovery
        serial: Device serial (optional)
        port: ATrace HTTP port (default 9090)
    """
    try:
        ctrl = DeviceController(serial=serial, port=port, package=package)
        if err := _require_http(ctrl):
            return json.dumps(err, indent=2)
        result = ctrl.hook_method(class_name, method_name, signature, is_static)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def unhook_method(
    class_name: str,
    method_name: str,
    signature: str,
    is_static: bool = False,
    package: str | None = None,
    serial: str | None = None,
    port: int = 9090,
) -> str:
    """Remove a hook from a previously hooked method, restoring its original entry point.

    Args:
        class_name: JNI class name (e.g. "com/example/Foo")
        method_name: Method name (e.g. "onCreate")
        signature: JNI method signature (e.g. "(Landroid/os/Bundle;)V")
        is_static: Whether the method is static (default False)
        package: App package name for ContentProvider port discovery
        serial: Device serial (optional)
        port: ATrace HTTP port (default 9090)
    """
    try:
        ctrl = DeviceController(serial=serial, port=port, package=package)
        if err := _require_http(ctrl):
            return json.dumps(err, indent=2)
        result = ctrl.unhook_method(class_name, method_name, signature, is_static)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def query_threads(
    package: str | None = None,
    serial: str | None = None,
    port: int = 9090,
) -> str:
    """List all threads in the traced app process (via ATrace HTTP API).
    Returns thread ID, name, and whether it's the main thread.
    Requires the app to have ATrace SDK integrated and HTTP server running.

    Args:
        package: App package name for ContentProvider port discovery (release builds)
        serial: Device serial (optional)
        port: ATrace HTTP port (default 9090)
    """
    try:
        ctrl = DeviceController(serial=serial, port=port, package=package)
        if err := _require_http(ctrl):
            return json.dumps(err, indent=2)
        result = ctrl.list_threads()
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def list_process_threads(package: str, serial: str | None = None) -> str:
    """List all threads of a process by package name (via ADB).
    No ATrace SDK required. Returns tid, name, is_main for each thread.

    Args:
        package: App package name (e.g. com.qiyi.trace)
        serial: Device serial (optional if single device)
    """
    try:
        ctrl = DeviceController(serial=serial)
        result = ctrl.list_process_threads(package)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def add_trace_mark(
    name: str,
    package: str | None = None,
    serial: str | None = None,
    port: int = 9090,
) -> str:
    """Insert a custom mark/label into the running trace.
    Marks appear as named events in the trace timeline, useful for
    annotating specific moments (e.g. "user_tap_login", "api_response_received").

    Args:
        name: Mark name/label to insert
        package: App package name for ContentProvider port discovery (release builds)
        serial: Device serial (optional)
        port: ATrace HTTP port (default 9090)
    """
    try:
        ctrl = DeviceController(serial=serial, port=port, package=package)
        if err := _require_http(ctrl):
            return json.dumps(err, indent=2)
        result = ctrl.add_mark(name)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def capture_stack(
    force: bool = False,
    package: str | None = None,
    serial: str | None = None,
    port: int = 9090,
) -> str:
    """Trigger an immediate stack sample capture.
    Normally sampling happens at configured intervals; this forces
    an immediate capture regardless of interval.

    Args:
        force: Force capture even if interval hasn't elapsed
        package: App package name for ContentProvider port discovery (release builds)
        serial: Device serial (optional)
        port: ATrace HTTP port (default 9090)
    """
    try:
        ctrl = DeviceController(serial=serial, port=port, package=package)
        if err := _require_http(ctrl):
            return json.dumps(err, indent=2)
        result = ctrl.capture_stack(force)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def replay_scenario(
    scenario: str,
    package: str,
    serial: str | None = None,
    activity: str | None = None,
    # ── scroll (scenario == "scroll") ─────────────────────────
    scroll_repeat: int = 5,
    scroll_dy: int = 600,
    scroll_duration_ms: int = 200,
    scroll_start_x: int = 540,
    scroll_start_y: int = 1200,
    scroll_end_x: int | None = None,
    scroll_end_y: int | None = None,
    scroll_pause_ms: int = 300,
    # ── tap (scenario == "tap_center") ────────────────────────
    tap_x: int = 540,
    tap_y: int = 960,
    # ── cold_start / hot_start timing ─────────────────────────
    cold_start_wait_ms: int = 500,
    hot_start_home_wait_ms: int = 300,
) -> str:
    """Trigger a specific app scenario on the device.
    Use with capture_trace to reproduce performance issues.

    Args:
        scenario: One of "cold_start", "hot_start", "scroll", "tap_center"
        package: App package name
        serial: Device serial (optional)
        activity: Launch activity class for cold_start (optional; else launcher monkey)

        scroll_repeat: Number of swipe gestures for "scroll" (default 5, min 1)
        scroll_dy: Vertical distance per swipe in pixels (positive = finger moves up, list scrolls down)
        scroll_duration_ms: Duration passed to `input swipe` per gesture
        scroll_start_x / scroll_start_y: Swipe start pixel coordinates
        scroll_end_x / scroll_end_y: Optional explicit swipe end. If BOTH are set, they override
            scroll_dy (full control of swipe vector). If either is unset, use dy mode.
        scroll_pause_ms: Sleep between repeated swipes (milliseconds)

        tap_x / tap_y: Screen coordinates for "tap_center"

        cold_start_wait_ms: Sleep after force-stop before launch (cold_start)
        hot_start_home_wait_ms: Sleep after HOME before resume (hot_start)
    """
    try:
        ctrl = DeviceController(serial=serial)
        result = ""
        params_used: dict[str, Any]

        if scenario == "cold_start":
            result = ctrl.cold_start_app(
                package,
                activity,
                force_stop_wait_ms=max(0, cold_start_wait_ms),
            )
            params_used = {
                "cold_start_wait_ms": max(0, cold_start_wait_ms),
                "activity": activity,
            }
        elif scenario == "hot_start":
            result = ctrl.hot_start_app(
                package,
                home_wait_ms=max(0, hot_start_home_wait_ms),
            )
            params_used = {
                "hot_start_home_wait_ms": max(0, hot_start_home_wait_ms),
            }
        elif scenario == "scroll":
            if (scroll_end_x is None) ^ (scroll_end_y is None):
                return json.dumps(
                    {
                        "error": "scroll_end_x and scroll_end_y must both be set together, "
                        "or omit both to use scroll_dy mode",
                        "scenario": scenario,
                        "package": package,
                    },
                    indent=2,
                )
            n = max(1, scroll_repeat)
            explicit_end = scroll_end_x is not None and scroll_end_y is not None
            for i in range(n):
                ctrl.scroll_screen(
                    duration_ms=max(1, scroll_duration_ms),
                    dy=scroll_dy,
                    start_x=scroll_start_x,
                    start_y=scroll_start_y,
                    end_x=scroll_end_x,
                    end_y=scroll_end_y,
                )
                if i < n - 1:
                    time.sleep(max(0, scroll_pause_ms) / 1000.0)
            result = f"Scrolled {n} times"
            params_used = {
                "scroll_repeat": n,
                "scroll_mode": "explicit_end" if explicit_end else "dy",
                "scroll_duration_ms": scroll_duration_ms,
                "scroll_start": [scroll_start_x, scroll_start_y],
                "scroll_pause_ms": scroll_pause_ms,
            }
            if explicit_end:
                params_used["scroll_end"] = [scroll_end_x, scroll_end_y]
            else:
                params_used["scroll_dy"] = scroll_dy
        elif scenario == "tap_center":
            result = ctrl.tap(tap_x, tap_y)
            params_used = {"tap_x": tap_x, "tap_y": tap_y}
        else:
            return f"Unknown scenario: {scenario}. Use: cold_start, hot_start, scroll, tap_center"

        current = ctrl.get_current_activity()
        payload: dict[str, Any] = {
            "scenario": scenario,
            "package": package,
            "result": result.strip() if result else "ok",
            "current_activity": current,
            "params_used": params_used,
        }
        return json.dumps(payload, indent=2)

    except Exception as e:
        return f"Error: {e}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Tool Provisioning — check/install simpleperf and perfetto
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@mcp.tool
def check_device_tools(serial: str | None = None) -> str:
    """Check if simpleperf and perfetto are available on the connected device.

    Reports:
    - ABI, SDK version, Android version
    - Whether simpleperf is pre-installed (system) or needs push from NDK
    - Whether perfetto is pre-installed or needs download from prebuilts
    - NDK location on host (if found)
    - heapprofd support (requires API 28+)
    - Host-side traceconv availability for Firefox Profiler export

    Call this first to understand what will happen when you run
    capture_cpu_profile or capture_heap_profile.

    Args:
        serial: Device serial (optional if single device)
    """
    try:
        info = tool_provisioner.device_info(serial)

        # Check host traceconv
        traceconv = tool_provisioner.get_traceconv_host()
        info["traceconv_host"] = str(traceconv) if traceconv else None
        info["firefox_profiler_export"] = traceconv is not None

        # Check atrace-tool (required for merged capture_trace)
        atrace_cmd = tool_provisioner.ensure_atrace_tool()
        info["atrace_tool_available"] = atrace_cmd is not None
        info["atrace_tool_cmd"] = " ".join(atrace_cmd) if atrace_cmd else None

        # Provisioning plan
        plan = []

        if atrace_cmd:
            plan.append(f"atrace-tool: ✅ available → {info['atrace_tool_cmd']}")
        else:
            plan.append(
                "atrace-tool: ❌ NOT BUILT — capture_trace will fall back to app-only mode\n"
                "  Fix: cd atrace-tool && ./gradlew installDist"
            )

        if not info.get("has_simpleperf"):
            if info.get("ndk_found"):
                plan.append("simpleperf: will push from NDK")
            else:
                plan.append("simpleperf: NDK not found — install NDK and set $ANDROID_NDK_HOME")
        else:
            plan.append("simpleperf: system binary available")

        if not info.get("has_perfetto"):
            plan.append(
                f"perfetto: will auto-download prebuilt "
                f"({tool_provisioner.PERFETTO_VERSION}) and push to /data/local/tmp/"
            )
        else:
            plan.append("perfetto: system binary available")

        if not info.get("heapprofd_supported"):
            plan.append(
                f"heapprofd: NOT supported (API {info.get('sdk', '?')} < 28)"
            )
        else:
            plan.append(f"heapprofd: supported (API {info.get('sdk')})")

        info["provisioning_plan"] = plan
        return json.dumps(info, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def convert_to_firefox_profile(
    perf_data_path: str,
    output_dir: str = "/tmp/atrace",
    serial: str | None = None,
) -> str:
    """Convert a simpleperf perf.data file to Firefox Profiler format.

    Based on the Firefox Profiler Android guide:
    https://profiler.firefox.com/docs/#/./guide-android-profiling

    Steps performed automatically:
    1. Push perf.data to device
    2. Run `simpleperf report-sample --protobuf` → perf.trace (on device)
    3. Pull perf.trace to host
    4. Run `traceconv` (auto-downloaded from GCS prebuilts) → gecko JSON
    5. Gzip → profile.json.gz

    The output file can be loaded in https://profiler.firefox.com
    via drag-and-drop or "Load a profile from file".

Args:
        perf_data_path: Local path to perf.data (from capture_cpu_profile)
        output_dir: Directory to save the gecko profile
        serial: Device serial (optional)
    """
    try:
        from pathlib import Path
        local = Path(perf_data_path)
        if not local.exists():
            return json.dumps({"error": f"File not found: {perf_data_path}"})

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        gecko = tool_provisioner.convert_to_gecko_profile(
            local, out / local.stem, serial=serial
        )
        if gecko:
            return json.dumps({
                "status": "success",
                "gecko_profile": str(gecko),
                "instructions": [
                    f"1. Open https://profiler.firefox.com",
                    f"2. Drag-and-drop {gecko} onto the page",
                    f"   OR click 'Load a profile from file' and select the file",
                ],
                "reference": "https://profiler.firefox.com/docs/#/./guide-android-profiling",
            }, indent=2)
        else:
            return json.dumps({
                "error": "Conversion failed",
                "hint": (
                    "Ensure the device is connected and simpleperf is available. "
                    "Run check_device_tools first."
                ),
            })
    except Exception as e:
        return f"Error: {e}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# simpleperf Tools — CPU profiling via simpleperf
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@mcp.tool
def capture_cpu_profile(
    package: str,
    duration_seconds: int = 10,
    output_dir: str = "/tmp/atrace",
    serial: str | None = None,
    event: str = "cpu-cycles",
    call_graph: str = "dwarf",
    freq: int = 1000,
    gecko_profile: bool = True,
) -> str:
    """Capture a CPU profile using simpleperf for a running app.

    Auto-provisions simpleperf on device if not present (pushes from NDK).
    Records call stacks at the given frequency, producing a perf.data file
    and a human-readable text report. By default also exports Firefox Profiler
    format (profile.json.gz) — drag-and-drop at https://profiler.firefox.com to view.

    Args:
        package: App package name (e.g. "com.example.app")
        duration_seconds: Recording duration (default 10s)
        output_dir: Local directory to save perf.data, report, and gecko profile
        serial: Device serial (optional if single device)
        event: Perf event ("cpu-cycles", "task-clock", "instructions", "cache-misses")
        call_graph: Call stack unwinding: "dwarf" (accurate) or "fp" (fast)
        freq: Sampling frequency in Hz (default 1000)
        gecko_profile: If True (default), convert to Firefox Profiler JSON
                       (profile.json.gz loadable at profiler.firefox.com)

    Returns:
        Path to perf.data, report preview, and gecko_profile path (when gecko_profile=True).
    """
    try:
        ctrl = DeviceController(serial=serial)
        result = ctrl.simpleperf_record(
            package=package,
            duration_s=duration_seconds,
            output_dir=output_dir,
            event=event,
            call_graph=call_graph,
            freq=freq,
            gecko_profile=gecko_profile,
        )
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def report_cpu_profile(
    perf_data_path: str,
    sort_keys: str = "comm,dso,symbol",
    percent_limit: float = 0.5,
    serial: str | None = None,
) -> str:
    """Generate a text report from a simpleperf perf.data file.

    Reports top functions sorted by CPU overhead. Useful for quickly
    identifying hot functions without a flamegraph.

    Args:
        perf_data_path: Local path to perf.data file
        sort_keys: Sort dimensions, comma-separated (comm, pid, tid, dso, symbol)
        percent_limit: Only show entries with overhead > this % (default 0.5)
        serial: Device serial (optional)
    """
    try:
        ctrl = DeviceController(serial=serial)
        result = ctrl.simpleperf_report(
            perf_data_path=perf_data_path,
            sort_keys=sort_keys,
            percent_limit=percent_limit,
        )
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def generate_flamegraph(
    perf_data_path: str,
    output_dir: str = "/tmp/atrace",
    ndk_path: str | None = None,
    serial: str | None = None,
    firefox_profiler: bool = True,
) -> str:
    """Generate a flamegraph from a simpleperf perf.data file.

    Priority:
      1. Firefox Profiler gecko JSON (auto-downloads traceconv from GCS,
         loadable at profiler.firefox.com — no NDK required)
      2. NDK inferno.sh → SVG flamegraph (set $ANDROID_NDK_HOME)
      3. flamegraph.pl → SVG (if on PATH)

    Args:
        perf_data_path: Local path to perf.data file
        output_dir: Directory to save output
        ndk_path: Optional Android NDK root path
                  (auto-detected from ANDROID_NDK_HOME)
        serial: Device serial (optional)
        firefox_profiler: Try Firefox Profiler gecko JSON first (default True)
    """
    try:
        ctrl = DeviceController(serial=serial)
        result = ctrl.simpleperf_flamegraph(
            perf_data_path=perf_data_path,
            output_dir=output_dir,
            ndk_path=ndk_path,
            firefox_profiler=firefox_profiler,
        )
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# heapprofd Tools — Heap memory profiling via Perfetto
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@mcp.tool
def capture_heap_profile(
    package: str,
    duration_seconds: int = 10,
    output_dir: str = "/tmp/atrace",
    serial: str | None = None,
    sampling_interval_bytes: int = 4096,
    block_client: bool = True,
    mode: str = "native",
) -> str:
    """Capture a heap memory profile via Perfetto.

    Modes (see https://perfetto.dev/docs/getting-started/memory-profiling):
      native     = heapprofd: sample malloc/free callstacks (allocation sites).
                   Not retroactive — only allocations after trace start.
      java-dump  = java_hprof: full Java/Kotlin heap dump at trace end
                   (retention graph, object counts by type).

    Produces a .perfetto file. Use analyze_heap_profile for native traces, or
    open in https://ui.perfetto.dev for flame graph / heap graph.

    Requirements: Android 10+ (API 29+), app must be Profileable or Debuggable.

    Args:
        package: App package name (e.g. "com.example.app")
        duration_seconds: Recording duration (default 10s)
        output_dir: Local directory to save the trace
        serial: Device serial (optional if single device)
        sampling_interval_bytes: [native] Sampling interval bytes (default 4096)
        block_client: [native] Block malloc until sample processed (default True)
        mode: "native" (heapprofd) or "java-dump" (Java heap dump)
    """
    try:
        ctrl = DeviceController(serial=serial)
        result = ctrl.heapprofd_capture(
            package=package,
            duration_s=duration_seconds,
            output_dir=output_dir,
            sampling_interval_bytes=sampling_interval_bytes,
            block_client=block_client,
            mode=mode,
        )
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool
def analyze_heap_profile(
    trace_path: str,
    top_n: int = 20,
) -> str:
    """Analyze a heapprofd Perfetto trace for allocation hot spots.

    Queries the heap allocation data with PerfettoSQL and returns:
    - Top allocating call sites (by retained + total size)
    - Allocation count by function
    - Largest single allocations

    Use load_trace first if you also want to run custom SQL.

    Args:
        trace_path: Path to the heapprofd .perfetto trace file
        top_n: Number of top allocators to return (default 20)
    """
    try:
        path = analyzer.load(trace_path)

        # Top retained size by call site (heap_profile_allocation table)
        retained_sql = f"""
SELECT
  HEX(callsite_id) AS callsite,
  SUM(size) / 1024.0 AS retained_kb,
  SUM(count) AS alloc_count
FROM heap_profile_allocation
WHERE size > 0
GROUP BY callsite_id
ORDER BY retained_kb DESC
LIMIT {top_n}
"""
        # Fallback to native_heap or memory tables depending on trace content
        flamegraph_sql = f"""
SELECT
  name,
  value / 1024.0 AS size_kb,
  cumulative_size / 1024.0 AS cumulative_kb
FROM experimental_flamegraph
WHERE profile_type = 'native'
ORDER BY value DESC
LIMIT {top_n}
"""
        retained_rows: list = []
        flamegraph_rows: list = []
        try:
            retained_rows = analyzer.query(path, retained_sql)
        except Exception:
            pass
        try:
            flamegraph_rows = analyzer.query(path, flamegraph_sql)
        except Exception:
            pass

        # Fallback summary via counter tracks
        summary_sql = """
SELECT ct.name, c.value / 1024.0 AS kb
FROM counter c
JOIN counter_track ct ON c.track_id = ct.id
WHERE ct.name LIKE '%heap%' OR ct.name LIKE '%mem%' OR ct.name LIKE '%alloc%'
ORDER BY c.ts DESC
LIMIT 30
"""
        summary_rows: list = []
        try:
            summary_rows = analyzer.query(path, summary_sql)
        except Exception:
            pass

        return json.dumps({
            "trace": trace_path,
            "top_retained_allocations": retained_rows,
            "flamegraph_nodes": flamegraph_rows,
            "memory_counters": summary_rows,
            "hint": (
                "If results are empty, the trace may use Java heap profiling. "
                "Try execute_sql with: SELECT * FROM heap_profile_allocation LIMIT 5"
            ),
        }, indent=2, default=str)
    except Exception as e:
        msg = f"Error analyzing heap profile: {e}"
        if "Trace processor" in str(e) or "failed to start" in str(e).lower():
            msg += TRACE_VIEWER_HINT
        return msg


@mcp.tool
def trace_viewer_hint(trace_path: str) -> str:
    """Get instructions to open a trace file in the browser (ui.perfetto.dev).

    Use when load_trace or analyze_heap_profile fail with Trace processor errors
    but the trace file exists (e.g. after capture_heap_profile). The file can
    often be opened successfully in the browser.

    Args:
        trace_path: Path to the .perfetto or .pftrace file
    """
    path = Path(trace_path).resolve()
    return (
        f"Trace file: {path}\n"
        "To view in browser: open https://ui.perfetto.dev → click 'Open trace file' "
        "(or drag the file onto the page) → select this file. The trace will load for "
        "interactive analysis (heap flamegraph, slices, etc.)."
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Resource: Provide common SQL query patterns to the LLM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@mcp.resource("atrace://sql-patterns")
def sql_patterns() -> str:
    """Common PerfettoSQL query patterns for Android performance analysis."""
    return """
# PerfettoSQL Quick Reference for Android Performance

## Find slow functions on main thread
SELECT s.name, s.dur/1e6 AS ms, s.id
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%com.example%' AND t.is_main_thread = 1
ORDER BY s.dur DESC LIMIT 20

## Thread state analysis (is it CPU-bound or IO-blocked?)
SELECT state, SUM(dur)/1e6 AS total_ms, COUNT(*) AS count
FROM thread_state ts
JOIN thread t ON ts.utid = t.utid
WHERE t.name = 'main' AND ts.dur > 0
GROUP BY state ORDER BY total_ms DESC

## Find GC pauses
SELECT s.name, s.dur/1e6 AS ms, s.ts
FROM slice s WHERE s.name LIKE '%GC%' OR s.name LIKE 'concurrent%'
ORDER BY s.dur DESC LIMIT 20

## Binder transactions
SELECT s.name, s.dur/1e6 AS ms, t.name AS thread
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
WHERE s.name LIKE 'binder%' ORDER BY s.dur DESC LIMIT 20

## Lock contention
SELECT s.name, s.dur/1e6 AS ms, t.name AS thread
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
WHERE s.name LIKE '%Lock%' OR s.name LIKE '%Monitor%'
      OR s.name LIKE '%contention%'
ORDER BY s.dur DESC LIMIT 20

## Startup time: from process start to first frame
SELECT MIN(ts) AS start_ts, MAX(ts + dur) AS end_ts,
       (MAX(ts + dur) - MIN(ts))/1e6 AS total_ms
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%com.example%'

## IO on main thread
SELECT s.name, s.dur/1e6 AS ms
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
WHERE t.is_main_thread = 1
  AND (s.name LIKE '%read%' OR s.name LIKE '%write%'
       OR s.name LIKE '%open%' OR s.name LIKE '%IO%')
ORDER BY s.dur DESC LIMIT 20

## Memory counters
SELECT c.ts, c.value, ct.name
FROM counter c
JOIN counter_track ct ON c.track_id = ct.id
WHERE ct.name LIKE '%mem%' OR ct.name LIKE '%RSS%'
ORDER BY c.ts LIMIT 100

## Find custom marks (inserted via add_trace_mark)
SELECT s.name, s.ts/1e6 AS ts_ms, s.dur/1e6 AS dur_ms, t.name AS thread
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
WHERE s.name LIKE '%capture_start%' OR s.name LIKE '%diag_%'
ORDER BY s.ts ASC

## Thread overview — all threads with slice counts
SELECT t.name AS thread_name, t.tid,
       t.is_main_thread,
       COUNT(s.id) AS slice_count,
       SUM(s.dur)/1e6 AS total_dur_ms
FROM thread t
JOIN process p ON t.upid = p.upid
JOIN thread_track tt ON tt.utid = t.utid
LEFT JOIN slice s ON s.track_id = tt.id
WHERE p.name LIKE '%com.example%'
GROUP BY t.utid
ORDER BY total_dur_ms DESC LIMIT 30

## Compare two time ranges (before/after mark)
-- Use custom marks to delineate time ranges for comparison
SELECT 'before' AS phase, s.name, SUM(s.dur)/1e6 AS total_ms, COUNT(*) AS count
FROM slice s
WHERE s.ts < (SELECT ts FROM slice WHERE name = 'my_mark' LIMIT 1)
GROUP BY s.name ORDER BY total_ms DESC LIMIT 10

## heapprofd: top retained allocations by call site
SELECT
  HEX(callsite_id) AS callsite_id,
  SUM(size) / 1024.0 AS retained_kb,
  SUM(count) AS alloc_count
FROM heap_profile_allocation
WHERE size > 0
GROUP BY callsite_id
ORDER BY retained_kb DESC LIMIT 20

## heapprofd: flamegraph nodes (native heap)
SELECT name, value / 1024.0 AS size_kb, cumulative_size / 1024.0 AS cumulative_kb
FROM experimental_flamegraph
WHERE profile_type = 'native'
ORDER BY value DESC LIMIT 20

## heapprofd: Java heap flamegraph
SELECT name, value / 1024.0 AS size_kb
FROM experimental_flamegraph
WHERE profile_type = 'java'
ORDER BY value DESC LIMIT 20

## heapprofd: total retained heap over time
SELECT ts / 1e9 AS ts_s, SUM(size) / 1048576.0 AS retained_mb
FROM heap_profile_allocation
WHERE size > 0
GROUP BY ts ORDER BY ts LIMIT 200

## Memory counters (RSS, PSS, heap from heapprofd counter tracks)
SELECT ct.name, MAX(c.value) / 1024.0 AS peak_kb, AVG(c.value) / 1024.0 AS avg_kb
FROM counter c
JOIN counter_track ct ON c.track_id = ct.id
WHERE ct.name LIKE '%mem%' OR ct.name LIKE '%heap%' OR ct.name LIKE '%RSS%'
GROUP BY ct.name ORDER BY peak_kb DESC LIMIT 20
"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


if __name__ == "__main__":
    import sys

    transport = "stdio"
    if "--transport" in sys.argv:
        idx = sys.argv.index("--transport")
        if idx + 1 < len(sys.argv):
            transport = sys.argv[idx + 1]

    if transport == "http":
        mcp.run(transport="streamable-http", host="0.0.0.0", port=8090)
    else:
        mcp.run()
