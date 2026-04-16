"""Control tools — device interaction, runtime tracing, scenario replay."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import tool_provisioner
from device_controller import DeviceController

from atrace_device import AdbBridge

from tools._helpers import TRACE_VIEWER_HINT, log_tool_call

try:
    import _monorepo
    _resolve_config = _monorepo.resolve_perfetto_config
except (ImportError, AttributeError):
    _resolve_config = None


def _require_http(ctrl: DeviceController) -> dict | None:
    if not ctrl.check_http_reachable():
        return ctrl.not_reachable_error()
    return None


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
    def _worker() -> None:
        time.sleep(max(0.0, delay_seconds))
        adb = AdbBridge(serial=serial)
        n = max(1, scroll_repeat)
        for i in range(n):
            adb.scroll_screen(
                duration_ms=max(1, scroll_duration_ms),
                dy=scroll_dy,
                start_x=scroll_start_x,
                start_y=scroll_start_y,
                end_x=scroll_end_x,
                end_y=scroll_end_y,
            )
            if i < n - 1:
                time.sleep(max(0, scroll_pause_ms) / 1000.0)

    threading.Thread(target=_worker, daemon=True, name="atrace-capture-inject-scroll").start()


def register_control_tools(mcp, controller, analyzer) -> None:

    @mcp.tool
    def list_devices() -> str:
        """List connected Android devices via ADB."""
        log_tool_call("list_devices")
        try:
            devices = controller.list_devices()
            if not devices:
                return "No devices connected. Connect a device via USB or WiFi ADB."
            info_list = []
            for serial in devices:
                dev_ctrl = DeviceController(serial=serial)
                info = dev_ctrl.get_device_info()
                info["serial"] = serial
                info_list.append(info)
            return json.dumps(info_list, indent=2)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def query_app_status(
        package: str | None = None,
        serial: str | None = None,
        port: int = 9090,
    ) -> str:
        """Query the ATrace-instrumented app's current status.

        Args:
            package: App package name
            serial: Device serial (optional)
            port: ATrace HTTP port (default 9090)
        """
        log_tool_call("query_app_status", package=package, serial=serial, port=port)
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

        Args:
            package: App package name
            duration_seconds: Trace duration (default 10)
            output_dir: Directory for output files
            serial: Device serial (optional)
            port: ATrace HTTP port (default 9090)
            cold_start: Force-stop and relaunch before tracing
            activity: Launch activity for cold start
            perfetto_config: Custom Perfetto config .txtpb path
            proguard_mapping: Proguard mapping.txt path
            buffer_size: Ring buffer size (default "64mb")
            inject_scroll: Run ADB swipes during capture
            scroll_start_delay_seconds: Delay before first swipe
            scroll_repeat: Number of swipes
            scroll_dy: Vertical pixels per swipe
            scroll_duration_ms: Swipe gesture duration
            scroll_start_x / scroll_start_y: Swipe start coordinates
            scroll_end_x / scroll_end_y: Explicit swipe end
            scroll_pause_ms: Pause between swipes
        """
        log_tool_call("capture_trace", package=package, duration_seconds=duration_seconds,
                       serial=serial, cold_start=cold_start, inject_scroll=inject_scroll)
        try:
            ts = int(time.time())
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            output_file = str(out / f"{package}_{ts}.perfetto")

            if inject_scroll and (scroll_end_x is None) ^ (scroll_end_y is None):
                return json.dumps({
                    "error": "inject_scroll: scroll_end_x and scroll_end_y must both be set or both omitted",
                    "package": package,
                }, indent=2)

            inject_meta: dict[str, Any] | None = None
            if inject_scroll:
                inject_meta = {
                    "inject_scroll": True,
                    "scroll_start_delay_seconds": scroll_start_delay_seconds,
                    "scroll_repeat": max(1, scroll_repeat),
                    "scroll_mode": "explicit_end" if scroll_end_x is not None and scroll_end_y is not None else "dy",
                }

            resolved_config = _resolve_config(perfetto_config) if _resolve_config else perfetto_config
            if perfetto_config and not resolved_config:
                LOG.warning("perfetto_config=%r not found, falling back to default", perfetto_config)
            elif resolved_config and resolved_config != perfetto_config:
                LOG.info("perfetto_config resolved: %s → %s", perfetto_config, resolved_config)

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
                    perfetto_config=resolved_config,
                    proguard_mapping=proguard_mapping,
                    buffer_size=buffer_size,
                )
                if result.get("status") != "success":
                    return json.dumps({**result, "build_hint": tool_provisioner.atrace_tool_build_hint()}, indent=2, default=str)

                merged_path = result.get("merged_trace")
                if not merged_path:
                    return json.dumps({"status": "error", "message": "merged_trace missing", "raw": result}, indent=2, default=str)

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
                }
                if inject_meta is not None:
                    payload["inject_scroll_meta"] = inject_meta
                return json.dumps(payload, indent=2, default=str)

        except Exception as e:
            return f"Error capturing trace: {e}"

    @mcp.tool
    def pause_tracing(package: str | None = None, serial: str | None = None, port: int = 9090) -> str:
        """Pause sampling without uninstalling hooks.

        Args:
            package: App package name
            serial: Device serial (optional)
            port: ATrace HTTP port (default 9090)
        """
        log_tool_call("pause_tracing", package=package, serial=serial, port=port)
        try:
            ctrl = DeviceController(serial=serial, port=port, package=package)
            if err := _require_http(ctrl):
                return json.dumps(err, indent=2)
            return json.dumps(ctrl.pause_trace(), indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def resume_tracing(package: str | None = None, serial: str | None = None, port: int = 9090) -> str:
        """Resume sampling after a pause.

        Args:
            package: App package name
            serial: Device serial (optional)
            port: ATrace HTTP port (default 9090)
        """
        log_tool_call("resume_tracing", package=package, serial=serial, port=port)
        try:
            ctrl = DeviceController(serial=serial, port=port, package=package)
            if err := _require_http(ctrl):
                return json.dumps(err, indent=2)
            return json.dumps(ctrl.resume_trace(), indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def list_plugins(package: str | None = None, serial: str | None = None, port: int = 9090) -> str:
        """List all loaded trace plugins and their current state.

        Args:
            package: App package name
            serial: Device serial (optional)
            port: ATrace HTTP port (default 9090)
        """
        log_tool_call("list_plugins", package=package, serial=serial, port=port)
        try:
            ctrl = DeviceController(serial=serial, port=port, package=package)
            if err := _require_http(ctrl):
                return json.dumps(err, indent=2)
            return json.dumps(ctrl.list_plugins(), indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def toggle_plugin(plugin_id: str, enable: bool, package: str | None = None, serial: str | None = None, port: int = 9090) -> str:
        """Enable or disable a specific trace plugin at runtime.

        Args:
            plugin_id: Plugin ID (e.g. "binder", "gc", "lock", "io")
            enable: True to enable, False to disable
            package: App package name
            serial: Device serial (optional)
            port: ATrace HTTP port (default 9090)
        """
        log_tool_call("toggle_plugin", plugin_id=plugin_id, enable=enable, package=package, serial=serial, port=port)
        try:
            ctrl = DeviceController(serial=serial, port=port, package=package)
            if err := _require_http(ctrl):
                return json.dumps(err, indent=2)
            return json.dumps(ctrl.toggle_plugin(plugin_id, enable), indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def get_sampling_config(package: str | None = None, serial: str | None = None, port: int = 9090) -> str:
        """Get current sampling interval configuration.

        Args:
            package: App package name
            serial: Device serial (optional)
            port: ATrace HTTP port (default 9090)
        """
        log_tool_call("get_sampling_config", package=package, serial=serial, port=port)
        try:
            ctrl = DeviceController(serial=serial, port=port, package=package)
            if err := _require_http(ctrl):
                return json.dumps(err, indent=2)
            return json.dumps(ctrl.get_sampling_config(), indent=2, default=str)
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

        Args:
            main_interval_ns: Main thread interval in nanoseconds (0 = no change)
            other_interval_ns: Other threads interval (0 = no change)
            package: App package name
            serial: Device serial (optional)
            port: ATrace HTTP port (default 9090)
        """
        log_tool_call(
            "set_sampling_interval",
            main_interval_ns=main_interval_ns,
            other_interval_ns=other_interval_ns,
            package=package,
            serial=serial,
            port=port,
        )
        try:
            ctrl = DeviceController(serial=serial, port=port, package=package)
            if err := _require_http(ctrl):
                return json.dumps(err, indent=2)
            return json.dumps(ctrl.set_sampling_interval(main_interval_ns, other_interval_ns), indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def list_watch_patterns(package: str | None = None, serial: str | None = None, port: int = 9090) -> str:
        """List ArtMethod WatchList substring patterns.

        Args:
            package: App package name
            serial: Device serial (optional)
            port: ATrace HTTP port (default 9090)
        """
        log_tool_call("list_watch_patterns", package=package, serial=serial, port=port)
        try:
            ctrl = DeviceController(serial=serial, port=port, package=package)
            if err := _require_http(ctrl):
                return json.dumps(err, indent=2)
            return json.dumps(ctrl.list_watch_patterns(), indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def add_watch_rule(scope: str, value: str, package: str | None = None, serial: str | None = None, port: int = 9090) -> str:
        """Add one semantic WatchList rule.

        Args:
            scope: package | class | method | substring
            value: Pattern value
            package: App package name
            serial: Device serial (optional)
            port: ATrace HTTP port (default 9090)
        """
        log_tool_call("add_watch_rule", scope=scope, value=value, package=package, serial=serial, port=port)
        try:
            ctrl = DeviceController(serial=serial, port=port, package=package)
            if err := _require_http(ctrl):
                return json.dumps(err, indent=2)
            return json.dumps(ctrl.add_watch_rule(scope, value), indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def add_watch_entries(entries: str, package: str | None = None, serial: str | None = None, port: int = 9090) -> str:
        """Batch semantic rules: scope:value pairs separated by |.

        Args:
            entries: Pipe-separated scope:value segments
            package: App package name
            serial: Device serial (optional)
            port: ATrace HTTP port (default 9090)
        """
        log_tool_call("add_watch_entries", entries=entries, package=package, serial=serial, port=port)
        try:
            ctrl = DeviceController(serial=serial, port=port, package=package)
            if err := _require_http(ctrl):
                return json.dumps(err, indent=2)
            return json.dumps(ctrl.add_watch_entries(entries), indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def add_watch_patterns(patterns: list[str], scope: str | None = None, package: str | None = None, serial: str | None = None, port: int = 9090) -> str:
        """Add WatchList patterns.

        Args:
            patterns: Non-empty strings
            scope: Optional package | class | method | substring
            package: App package name
            serial: Device serial (optional)
            port: ATrace HTTP port (default 9090)
        """
        log_tool_call("add_watch_patterns", patterns=patterns, scope=scope, package=package, serial=serial, port=port)
        try:
            ctrl = DeviceController(serial=serial, port=port, package=package)
            if err := _require_http(ctrl):
                return json.dumps(err, indent=2)
            return json.dumps(ctrl.add_watch_patterns(patterns, scope=scope), indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def remove_watch_pattern(pattern: str, package: str | None = None, serial: str | None = None, port: int = 9090) -> str:
        """Remove one WatchList entry.

        Args:
            pattern: The pattern to remove
            package: App package name
            serial: Device serial (optional)
            port: ATrace HTTP port (default 9090)
        """
        log_tool_call("remove_watch_pattern", pattern=pattern, package=package, serial=serial, port=port)
        try:
            ctrl = DeviceController(serial=serial, port=port, package=package)
            if err := _require_http(ctrl):
                return json.dumps(err, indent=2)
            return json.dumps(ctrl.remove_watch_pattern(pattern), indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def remove_watch_entry(entry: str | None = None, scope: str | None = None, value: str | None = None, package: str | None = None, serial: str | None = None, port: int = 9090) -> str:
        """Remove a watch rule by storage key or scope+value.

        Args:
            entry: Storage key (e.g. pkg:com.a.)
            scope: Scope for removal
            value: Value for removal
            package: App package name
            serial: Device serial (optional)
            port: ATrace HTTP port (default 9090)
        """
        log_tool_call(
            "remove_watch_entry",
            entry=entry,
            scope=scope,
            value=value,
            package=package,
            serial=serial,
            port=port,
        )
        try:
            ctrl = DeviceController(serial=serial, port=port, package=package)
            if err := _require_http(ctrl):
                return json.dumps(err, indent=2)
            return json.dumps(ctrl.remove_watch_entry(entry=entry, scope=scope, value=value), indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def clear_watch_patterns(package: str | None = None, serial: str | None = None, port: int = 9090) -> str:
        """Clear all ArtMethod WatchList patterns.

        Args:
            package: App package name
            serial: Device serial (optional)
            port: ATrace HTTP port (default 9090)
        """
        log_tool_call("clear_watch_patterns", package=package, serial=serial, port=port)
        try:
            ctrl = DeviceController(serial=serial, port=port, package=package)
            if err := _require_http(ctrl):
                return json.dumps(err, indent=2)
            return json.dumps(ctrl.clear_watch_patterns(), indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def hook_method(class_name: str, method_name: str, signature: str, is_static: bool = False, package: str | None = None, serial: str | None = None, port: int = 9090) -> str:
        """Hook a specific Java method.

        Args:
            class_name: JNI class name
            method_name: Method name
            signature: JNI method signature
            is_static: Whether the method is static
            package: App package name
            serial: Device serial (optional)
            port: ATrace HTTP port (default 9090)
        """
        log_tool_call(
            "hook_method",
            class_name=class_name,
            method_name=method_name,
            signature=signature,
            is_static=is_static,
            package=package,
            serial=serial,
            port=port,
        )
        try:
            ctrl = DeviceController(serial=serial, port=port, package=package)
            if err := _require_http(ctrl):
                return json.dumps(err, indent=2)
            return json.dumps(ctrl.hook_method(class_name, method_name, signature, is_static), indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def unhook_method(class_name: str, method_name: str, signature: str, is_static: bool = False, package: str | None = None, serial: str | None = None, port: int = 9090) -> str:
        """Remove a hook from a previously hooked method.

        Args:
            class_name: JNI class name
            method_name: Method name
            signature: JNI method signature
            is_static: Whether the method is static
            package: App package name
            serial: Device serial (optional)
            port: ATrace HTTP port (default 9090)
        """
        log_tool_call(
            "unhook_method",
            class_name=class_name,
            method_name=method_name,
            signature=signature,
            is_static=is_static,
            package=package,
            serial=serial,
            port=port,
        )
        try:
            ctrl = DeviceController(serial=serial, port=port, package=package)
            if err := _require_http(ctrl):
                return json.dumps(err, indent=2)
            return json.dumps(ctrl.unhook_method(class_name, method_name, signature, is_static), indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def query_threads(package: str | None = None, serial: str | None = None, port: int = 9090) -> str:
        """List all threads in the traced app process (via ATrace HTTP API).

        Args:
            package: App package name
            serial: Device serial (optional)
            port: ATrace HTTP port (default 9090)
        """
        log_tool_call("query_threads", package=package, serial=serial, port=port)
        try:
            ctrl = DeviceController(serial=serial, port=port, package=package)
            if err := _require_http(ctrl):
                return json.dumps(err, indent=2)
            return json.dumps(ctrl.list_threads(), indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def list_process_threads(package: str, serial: str | None = None) -> str:
        """List all threads of a process by package name (via ADB).

        Args:
            package: App package name
            serial: Device serial (optional)
        """
        log_tool_call("list_process_threads", package=package, serial=serial)
        try:
            ctrl = DeviceController(serial=serial)
            return json.dumps(ctrl.list_process_threads(package), indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def add_trace_mark(name: str, package: str | None = None, serial: str | None = None, port: int = 9090) -> str:
        """Insert a custom mark/label into the running trace.

        Args:
            name: Mark name/label
            package: App package name
            serial: Device serial (optional)
            port: ATrace HTTP port (default 9090)
        """
        log_tool_call("add_trace_mark", name=name, package=package, serial=serial, port=port)
        try:
            ctrl = DeviceController(serial=serial, port=port, package=package)
            if err := _require_http(ctrl):
                return json.dumps(err, indent=2)
            return json.dumps(ctrl.add_mark(name), indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def capture_stack(force: bool = False, package: str | None = None, serial: str | None = None, port: int = 9090) -> str:
        """Trigger an immediate stack sample capture.

        Args:
            force: Force capture even if interval hasn't elapsed
            package: App package name
            serial: Device serial (optional)
            port: ATrace HTTP port (default 9090)
        """
        log_tool_call("capture_stack", force=force, package=package, serial=serial, port=port)
        try:
            ctrl = DeviceController(serial=serial, port=port, package=package)
            if err := _require_http(ctrl):
                return json.dumps(err, indent=2)
            return json.dumps(ctrl.capture_stack(force), indent=2, default=str)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def replay_scenario(
        scenario: str,
        package: str,
        serial: str | None = None,
        activity: str | None = None,
        scroll_repeat: int = 5,
        scroll_dy: int = 600,
        scroll_duration_ms: int = 200,
        scroll_start_x: int = 540,
        scroll_start_y: int = 1200,
        scroll_end_x: int | None = None,
        scroll_end_y: int | None = None,
        scroll_pause_ms: int = 300,
        tap_x: int = 540,
        tap_y: int = 960,
        cold_start_wait_ms: int = 500,
        hot_start_home_wait_ms: int = 300,
    ) -> str:
        """Trigger a specific app scenario on the device.

        Args:
            scenario: One of "cold_start", "hot_start", "scroll", "tap_center"
            package: App package name
            serial: Device serial (optional)
            activity: Launch activity for cold_start
            scroll_repeat / scroll_dy / scroll_duration_ms: Scroll parameters
            scroll_start_x / scroll_start_y / scroll_end_x / scroll_end_y: Coordinates
            scroll_pause_ms: Pause between swipes
            tap_x / tap_y: Tap coordinates
            cold_start_wait_ms: Delay after force-stop
            hot_start_home_wait_ms: Delay after HOME key
        """
        log_tool_call(
            "replay_scenario",
            scenario=scenario,
            package=package,
            serial=serial,
            activity=activity,
            scroll_repeat=scroll_repeat,
            tap_x=tap_x,
            tap_y=tap_y,
        )
        try:
            ctrl = DeviceController(serial=serial)
            result = ""
            params_used: dict[str, Any]

            if scenario == "cold_start":
                result = ctrl.cold_start_app(package, activity, force_stop_wait_ms=max(0, cold_start_wait_ms))
                params_used = {"cold_start_wait_ms": max(0, cold_start_wait_ms), "activity": activity}
            elif scenario == "hot_start":
                result = ctrl.hot_start_app(package, home_wait_ms=max(0, hot_start_home_wait_ms))
                params_used = {"hot_start_home_wait_ms": max(0, hot_start_home_wait_ms)}
            elif scenario == "scroll":
                if (scroll_end_x is None) ^ (scroll_end_y is None):
                    return json.dumps({"error": "scroll_end_x and scroll_end_y must both be set or both omitted", "scenario": scenario}, indent=2)
                n = max(1, scroll_repeat)
                explicit_end = scroll_end_x is not None and scroll_end_y is not None
                for i in range(n):
                    ctrl.scroll_screen(duration_ms=max(1, scroll_duration_ms), dy=scroll_dy, start_x=scroll_start_x, start_y=scroll_start_y, end_x=scroll_end_x, end_y=scroll_end_y)
                    if i < n - 1:
                        time.sleep(max(0, scroll_pause_ms) / 1000.0)
                result = f"Scrolled {n} times"
                params_used = {"scroll_repeat": n, "scroll_mode": "explicit_end" if explicit_end else "dy", "scroll_duration_ms": scroll_duration_ms}
            elif scenario == "tap_center":
                result = ctrl.tap(tap_x, tap_y)
                params_used = {"tap_x": tap_x, "tap_y": tap_y}
            else:
                return f"Unknown scenario: {scenario}. Use: cold_start, hot_start, scroll, tap_center"

            current = ctrl.get_current_activity()
            return json.dumps({"scenario": scenario, "package": package, "result": result.strip() if result else "ok", "current_activity": current, "params_used": params_used}, indent=2)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def list_capture_presets() -> str:
        """List available capture configuration presets.

        Returns preset names (e.g. startup, scroll, memory) that can be
        used with ``capture_with_preset``.
        """
        log_tool_call("list_capture_presets")
        try:
            ctrl = DeviceController()
            presets = ctrl.config_registry.list_presets()
            templates = ctrl.config_registry.list_perfetto_templates()
            engines = ctrl.capture_router.available_engines()
            return json.dumps({
                "presets": presets,
                "perfetto_templates": templates,
                "engines": engines,
            }, indent=2)
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool
    def capture_with_preset(
        preset: str,
        package: str | None = None,
        duration_seconds: int | None = None,
        output_dir: str = "/tmp/atrace",
        serial: str | None = None,
    ) -> str:
        """Run a capture using a named preset configuration.

        Args:
            preset: Preset name (from ``list_capture_presets``)
            package: Override the package in the preset
            duration_seconds: Override duration
            output_dir: Output directory
            serial: Device serial (optional)
        """
        log_tool_call("capture_with_preset", preset=preset, package=package,
                       duration_seconds=duration_seconds, serial=serial)
        try:
            ctrl = DeviceController(serial=serial, package=package)
            config = ctrl.config_registry.load_preset(preset)
            if package:
                config.package = package
            if duration_seconds is not None:
                config.duration_sec = duration_seconds
            config.output_dir = output_dir

            result = ctrl.capture_with_config(config)

            if result.get("status") == "success" and result.get("trace"):
                try:
                    analyzer.load(result["trace"], process_name=package)
                    result["overview"] = analyzer.overview(result["trace"])
                except Exception as load_err:
                    result["load_error"] = str(load_err)

            return json.dumps(result, indent=2, default=str)
        except FileNotFoundError:
            ctrl = DeviceController()
            available = ctrl.config_registry.list_presets()
            return json.dumps({
                "error": f"Preset not found: {preset}",
                "available_presets": available,
            }, indent=2)
        except Exception as e:
            return f"Error: {e}"
