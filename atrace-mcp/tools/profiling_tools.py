"""Profiling tools — simpleperf CPU + heapprofd memory profiling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import tool_provisioner
from device_controller import DeviceController

from tools._helpers import TRACE_VIEWER_HINT, log_tool_call


def register_profiling_tools(mcp, controller, analyzer) -> None:

    @mcp.tool
    def check_device_tools(serial: str | None = None) -> str:
        """Check if simpleperf, perfetto, and atrace-tool are available on the device.

        Args:
            serial: Device serial (optional)
        """
        log_tool_call("check_device_tools", serial=serial)
        try:
            info = tool_provisioner.device_info(serial)
            traceconv = tool_provisioner.get_traceconv_host()
            info["traceconv_host"] = str(traceconv) if traceconv else None
            info["firefox_profiler_export"] = traceconv is not None

            atrace_cmd = tool_provisioner.ensure_atrace_tool()
            info["atrace_tool_available"] = atrace_cmd is not None
            info["atrace_tool_cmd"] = " ".join(atrace_cmd) if atrace_cmd else None

            plan = []
            if atrace_cmd:
                plan.append(f"atrace-tool: available")
            else:
                plan.append("atrace-tool: NOT BUILT — cd atrace-tool && ./gradlew installDist")
            if not info.get("has_simpleperf"):
                plan.append("simpleperf: " + ("will push from NDK" if info.get("ndk_found") else "NDK not found"))
            else:
                plan.append("simpleperf: system binary available")
            if not info.get("has_perfetto"):
                plan.append(f"perfetto: will auto-download prebuilt ({tool_provisioner.PERFETTO_VERSION})")
            else:
                plan.append("perfetto: system binary available")
            plan.append(f"heapprofd: {'supported' if info.get('heapprofd_supported') else 'NOT supported'} (API {info.get('sdk', '?')})")

            info["provisioning_plan"] = plan
            return json.dumps(info, indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def convert_to_firefox_profile(perf_data_path: str, output_dir: str = "/tmp/atrace", serial: str | None = None) -> str:
        """Convert a simpleperf perf.data file to Firefox Profiler format.

        Args:
            perf_data_path: Local path to perf.data
            output_dir: Directory to save the gecko profile
            serial: Device serial (optional)
        """
        log_tool_call("convert_to_firefox_profile", perf_data_path=perf_data_path, output_dir=output_dir, serial=serial)
        try:
            local = Path(perf_data_path)
            if not local.exists():
                return json.dumps({"error": f"File not found: {perf_data_path}"})
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            gecko = tool_provisioner.convert_to_gecko_profile(local, out / local.stem, serial=serial)
            if gecko:
                return json.dumps({"status": "success", "gecko_profile": str(gecko)}, indent=2)
            else:
                return json.dumps({"error": "Conversion failed"})
        except Exception as e:
            return f"Error: {e}"

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
        """Capture a CPU profile using simpleperf.

        Args:
            package: App package name
            duration_seconds: Recording duration (default 10s)
            output_dir: Directory for output files
            serial: Device serial (optional)
            event: Perf event type
            call_graph: Unwinding method ("dwarf" or "fp")
            freq: Sampling frequency in Hz
            gecko_profile: Convert to Firefox Profiler format
        """
        log_tool_call("capture_cpu_profile", package=package, duration_seconds=duration_seconds,
                       serial=serial, event=event, freq=freq)
        try:
            ctrl = DeviceController(serial=serial)
            result = ctrl.simpleperf_record(
                package=package, duration_s=duration_seconds, output_dir=output_dir,
                event=event, call_graph=call_graph, freq=freq, gecko_profile=gecko_profile,
            )
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def report_cpu_profile(perf_data_path: str, sort_keys: str = "comm,dso,symbol", percent_limit: float = 0.5, serial: str | None = None) -> str:
        """Generate a text report from a simpleperf perf.data file.

        Args:
            perf_data_path: Local path to perf.data
            sort_keys: Sort dimensions
            percent_limit: Min overhead % (default 0.5)
            serial: Device serial (optional)
        """
        log_tool_call(
            "report_cpu_profile",
            perf_data_path=perf_data_path,
            sort_keys=sort_keys,
            percent_limit=percent_limit,
            serial=serial,
        )
        try:
            ctrl = DeviceController(serial=serial)
            result = ctrl.simpleperf_report(perf_data_path=perf_data_path, sort_keys=sort_keys, percent_limit=percent_limit)
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def generate_flamegraph(perf_data_path: str, output_dir: str = "/tmp/atrace", ndk_path: str | None = None, serial: str | None = None, firefox_profiler: bool = True) -> str:
        """Generate a flamegraph from a simpleperf perf.data file.

        Args:
            perf_data_path: Local path to perf.data
            output_dir: Directory for output
            ndk_path: Android NDK root path (optional)
            serial: Device serial (optional)
            firefox_profiler: Try Firefox Profiler format first
        """
        log_tool_call(
            "generate_flamegraph",
            perf_data_path=perf_data_path,
            output_dir=output_dir,
            ndk_path=ndk_path,
            serial=serial,
            firefox_profiler=firefox_profiler,
        )
        try:
            ctrl = DeviceController(serial=serial)
            result = ctrl.simpleperf_flamegraph(perf_data_path=perf_data_path, output_dir=output_dir, ndk_path=ndk_path, firefox_profiler=firefox_profiler)
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

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

        Args:
            package: App package name
            duration_seconds: Recording duration
            output_dir: Directory for output
            serial: Device serial (optional)
            sampling_interval_bytes: Sampling interval (native mode)
            block_client: Block malloc until sampled (native mode)
            mode: "native" (heapprofd) or "java-dump"
        """
        log_tool_call(
            "capture_heap_profile",
            package=package,
            duration_seconds=duration_seconds,
            output_dir=output_dir,
            serial=serial,
            sampling_interval_bytes=sampling_interval_bytes,
            block_client=block_client,
            mode=mode,
        )
        try:
            ctrl = DeviceController(serial=serial)
            result = ctrl.heapprofd_capture(
                package=package, duration_s=duration_seconds, output_dir=output_dir,
                sampling_interval_bytes=sampling_interval_bytes, block_client=block_client, mode=mode,
            )
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def analyze_heap_profile(trace_path: str, top_n: int = 20) -> str:
        """Analyze a heapprofd Perfetto trace for allocation hot spots.

        Args:
            trace_path: Path to heapprofd .perfetto trace
            top_n: Number of top allocators (default 20)
        """
        log_tool_call("analyze_heap_profile", trace_path=trace_path, top_n=top_n)
        try:
            path = analyzer.load(trace_path)
            retained_sql = f"SELECT HEX(callsite_id) AS callsite, SUM(size)/1024.0 AS retained_kb, SUM(count) AS alloc_count FROM heap_profile_allocation WHERE size>0 GROUP BY callsite_id ORDER BY retained_kb DESC LIMIT {top_n}"
            flamegraph_sql = f"SELECT name, value/1024.0 AS size_kb, cumulative_size/1024.0 AS cumulative_kb FROM experimental_flamegraph WHERE profile_type='native' ORDER BY value DESC LIMIT {top_n}"
            summary_sql = "SELECT ct.name, c.value/1024.0 AS kb FROM counter c JOIN counter_track ct ON c.track_id=ct.id WHERE ct.name LIKE '%heap%' OR ct.name LIKE '%mem%' ORDER BY c.ts DESC LIMIT 30"

            retained_rows: list = []
            flamegraph_rows: list = []
            summary_rows: list = []
            try:
                retained_rows = analyzer.query(path, retained_sql)
            except Exception:
                pass
            try:
                flamegraph_rows = analyzer.query(path, flamegraph_sql)
            except Exception:
                pass
            try:
                summary_rows = analyzer.query(path, summary_sql)
            except Exception:
                pass

            return json.dumps({
                "trace": trace_path,
                "top_retained_allocations": retained_rows,
                "flamegraph_nodes": flamegraph_rows,
                "memory_counters": summary_rows,
            }, indent=2, default=str)
        except Exception as e:
            msg = f"Error analyzing heap profile: {e}"
            if "Trace processor" in str(e) or "failed to start" in str(e).lower():
                msg += TRACE_VIEWER_HINT
            return msg

    @mcp.tool
    def trace_viewer_hint(trace_path: str) -> str:
        """Get instructions to open a trace in the browser (ui.perfetto.dev).

        Args:
            trace_path: Path to the .perfetto file
        """
        log_tool_call("trace_viewer_hint", trace_path=trace_path)
        path = Path(trace_path).resolve()
        return (
            f"Trace file: {path}\n"
            "Open https://ui.perfetto.dev → click 'Open trace file' → select this file."
        )
