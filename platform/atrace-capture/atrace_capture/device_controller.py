"""DeviceController — composition facade over ``atrace-device`` + capture routing.

Delegates ADB / HTTP / atrace-tool interactions to ``atrace-device``,
routes config-driven capture through ``CaptureRouter``, and adds
profiling orchestration (simpleperf, heapprofd) via ``provision_bridge``
(``atrace-provision`` / ``ToolRegistry``).

Lives in ``atrace-capture`` (L1) so ``atrace-service`` and ``atrace-mcp`` do not
cross-import each other (Phase 6).

Design:
  DeviceController
    ├── AdbBridge          (ADB commands)
    ├── AppHttpClient      (in-app HTTP API)
    ├── FileTransfer       (trace download)
    ├── EngineCLI          (atrace-tool JSON protocol)
    └── CaptureRouter      (config-driven capture routing)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from . import provision_bridge
from .config.registry import ConfigRegistry
from .config.schema import CaptureConfig
from .repo_paths import monorepo_root
from .router import CaptureRouter

_repo_root = monorepo_root()
_monorepo_path = _repo_root / "platform" / "_monorepo.py"
if _monorepo_path.is_file():
    _module_dir = _monorepo_path.parent
    if str(_module_dir) not in sys.path:
        sys.path.insert(0, str(_module_dir))
    import _monorepo; _monorepo.bootstrap()  # noqa: E702

from atrace_device import (  # noqa: E402
    AdbBridge,
    AppHttpClient,
    EngineCLI,
    FileTransfer,
    get_device_info_dict,
)
from atrace_provision.bundled_paths import record_android_trace_script_path  # noqa: E402


def _record_android_trace_script() -> Path | None:
    return record_android_trace_script_path()


class DeviceController:
    """Facade over atrace-device + atrace-capture with profiling orchestration."""

    def __init__(
        self,
        serial: str | None = None,
        port: int = 9090,
        package: str | None = None,
    ):
        self.serial = serial
        self.port = port
        self.package = package

        self.adb = AdbBridge(serial=serial)
        self.app = AppHttpClient(self.adb, port=port, package=package)
        self.transfer = FileTransfer(self.adb, self.app)

        atrace_tool_cmd = provision_bridge.ensure_atrace_tool()
        self.engine = EngineCLI(
            atrace_tool_cmd=atrace_tool_cmd, serial=serial,
        )

        self.capture_router = CaptureRouter(self.engine)
        self.config_registry = ConfigRegistry()

    # ══════════════════════════════════════════════════════════════
    # Delegates → AdbBridge
    # ══════════════════════════════════════════════════════════════

    def list_devices(self) -> list[str]:
        return self.adb.list_device_serials()

    def cold_start_app(
        self, package: str, activity: str | None = None,
        force_stop_wait_ms: int = 500,
    ) -> str:
        return self.adb.cold_start_app(package, activity, force_stop_wait_ms)

    def hot_start_app(self, package: str, home_wait_ms: int = 300) -> str:
        return self.adb.hot_start_app(package, home_wait_ms)

    def scroll_screen(self, **kwargs: Any) -> str:
        return self.adb.scroll_screen(**kwargs)

    def tap(self, x: int, y: int) -> str:
        return self.adb.tap(x, y)

    def get_current_activity(self) -> str:
        return self.adb.get_current_activity()

    def get_pid(self, package: str) -> int | None:
        return self.adb.get_pid(package)

    def list_process_threads(self, package: str) -> dict:
        return self.adb.list_process_threads(package)

    def get_device_info(self, timeout: int = 10) -> dict:
        return get_device_info_dict(self.adb, timeout=timeout)

    # ══════════════════════════════════════════════════════════════
    # Delegates → AppHttpClient
    # ══════════════════════════════════════════════════════════════

    def setup_forward(self) -> None:
        self.app.setup_forward()

    def try_setup_forward(self) -> bool:
        return self.app.try_setup_forward()

    def check_http_reachable(self) -> bool:
        return self.app.check_http_reachable()

    def not_reachable_error(self) -> dict:
        return self.app.not_reachable_error()

    def app_status(self) -> dict:
        return self.app.app_status()

    def app_debug_info(self) -> dict:
        return self.app.app_debug_info()

    def app_info(self) -> dict:
        return self.app.app_info()

    def is_ready(self) -> bool:
        return self.app.is_ready()

    def start_trace(self) -> dict:
        return self.app.start_trace()

    def stop_trace(self) -> dict:
        return self.app.stop_trace()

    def pause_trace(self) -> dict:
        return self.app.pause_trace()

    def resume_trace(self) -> dict:
        return self.app.resume_trace()

    def clean_traces(self) -> dict:
        return self.app.clean_traces()

    def list_plugins(self) -> dict:
        return self.app.list_plugins()

    def toggle_plugin(self, plugin_id: str, enable: bool) -> dict:
        return self.app.toggle_plugin(plugin_id, enable)

    def list_watch_patterns(self) -> dict:
        return self.app.list_watch_patterns()

    def add_watch_pattern(self, pattern: str) -> dict:
        return self.app.add_watch_pattern(pattern)

    def add_watch_rule(self, scope: str, value: str) -> dict:
        return self.app.add_watch_rule(scope, value)

    def add_watch_entries(self, entries: str) -> dict:
        return self.app.add_watch_entries(entries)

    def add_watch_patterns(self, patterns: list[str], scope: str | None = None) -> dict:
        return self.app.add_watch_patterns(patterns, scope=scope)

    def remove_watch_pattern(self, pattern: str) -> dict:
        return self.app.remove_watch_pattern(pattern)

    def remove_watch_entry(self, **kwargs: Any) -> dict:
        return self.app.remove_watch_entry(**kwargs)

    def clear_watch_patterns(self) -> dict:
        return self.app.clear_watch_patterns()

    def hook_method(self, class_name: str, method_name: str, signature: str, is_static: bool = False) -> dict:
        return self.app.hook_method(class_name, method_name, signature, is_static)

    def unhook_method(self, class_name: str, method_name: str, signature: str, is_static: bool = False) -> dict:
        return self.app.unhook_method(class_name, method_name, signature, is_static)

    def get_sampling_config(self) -> dict:
        return self.app.get_sampling_config()

    def set_sampling_interval(self, main_interval_ns: int = 0, other_interval_ns: int = 0) -> dict:
        return self.app.set_sampling_interval(main_interval_ns, other_interval_ns)

    def list_threads(self) -> dict:
        return self.app.list_threads()

    def add_mark(self, name: str) -> dict:
        return self.app.add_mark(name)

    def capture_stack(self, force: bool = False) -> dict:
        return self.app.capture_stack(force)

    # ══════════════════════════════════════════════════════════════
    # Delegates → FileTransfer
    # ══════════════════════════════════════════════════════════════

    def download_trace(self, output_dir: str) -> dict[str, str]:
        return self.transfer.download_trace(output_dir)

    # ══════════════════════════════════════════════════════════════
    # Delegates → EngineCLI  (atrace-tool JSON protocol)
    # ══════════════════════════════════════════════════════════════

    def run_atrace_subcommand(
        self,
        subcommand: str,
        extra_args: list[str],
        timeout: int = 300,
        atrace_tool_cmd: list[str] | None = None,
    ) -> dict:
        if atrace_tool_cmd:
            cli = EngineCLI(atrace_tool_cmd=atrace_tool_cmd, serial=self.serial)
        else:
            cli = self.engine
        result = cli.invoke(subcommand, extra_args, timeout=timeout)
        return result.data if result.success else {
            "status": result.status,
            "message": result.message,
            **({"stderr_tail": result.raw_stderr[-1000:]} if result.raw_stderr else {}),
        }

    def capture_with_config(self, config: CaptureConfig) -> dict:
        """Config-driven capture via ``CaptureRouter``.

        Accepts a ``CaptureConfig`` (from preset YAML or programmatic
        construction) and routes it to the appropriate engine (merged / cpu / heap).
        """
        result = self.capture_router.execute(config)
        return result.to_dict()

    def run_atrace_tool(
        self,
        atrace_tool_cmd: list[str],
        package: str,
        duration_s: int,
        output_file: str,
        cold_start: bool = False,
        activity: str | None = None,
        port: int = 9090,
        perfetto_config: str | None = None,
        proguard_mapping: str | None = None,
        buffer_size: str = "64mb",
        extra_args: list[str] | None = None,
    ) -> dict:
        """Capture merged Perfetto + ATrace trace via ``atrace-tool capture``."""
        cli = EngineCLI(atrace_tool_cmd=atrace_tool_cmd, serial=self.serial)
        result = cli.capture(
            package=package,
            duration_s=duration_s,
            output_file=output_file,
            port=port,
            buffer_size=buffer_size,
            cold_start=cold_start,
            activity=activity,
            perfetto_config=perfetto_config,
            proguard_mapping=proguard_mapping,
            extra_args=extra_args,
        )

        data = result.data if result.success else {
            "status": result.status,
            "message": result.message,
            "hint": (
                "Common causes:\n"
                "  • App not running or ATrace SDK not initialised\n"
                "  • ADB disconnected during capture\n"
                "  • record_android_trace missing — install atrace-provision (bundled_record_android_trace) or rebuild JAR: ./gradlew deployMcp"
            ),
        }

        if result.success:
            merged = Path(data.get("merged_trace", output_file))
            app_trace = merged.parent / "app_trace.pb"
            if app_trace.exists():
                data["app_trace_pb"] = str(app_trace)
                data["app_trace_kb"] = app_trace.stat().st_size // 1024

        return data

    # ══════════════════════════════════════════════════════════════
    # Profiling orchestration (simpleperf / heapprofd)
    #   — value-add that requires tool_provisioner
    # ══════════════════════════════════════════════════════════════

    def simpleperf_record(
        self,
        package: str,
        duration_s: int = 10,
        output_dir: str = "/tmp/atrace",
        event: str = "cpu-cycles",
        call_graph: str = "dwarf",
        freq: int = 1000,
        gecko_profile: bool = False,
    ) -> dict:
        """CPU profiling: atrace-tool cpu → AOSP app_profiler → device simpleperf."""
        # ── Preferred: atrace-tool cpu ──
        if self.engine.available:
            result = self.engine.cpu(package, duration_s, output_dir, event, freq, call_graph)
            if result.success:
                return {**result.data, "method": "atrace-tool cpu"}

        # ── Fallback: Python implementation ──
        pid = self.adb.get_pid(package)
        if pid is None:
            return {"error": f"Process not found: {package}"}

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        local_perf = out / f"perf_{ts}.data"
        local_report = out / f"perf_{ts}_report.txt"

        # AOSP app_profiler.py path
        toolkit = provision_bridge.ensure_simpleperf_toolkit()
        if toolkit and provision_bridge.run_app_profiler(
            toolkit, package, duration_s, local_perf, self.serial
        ):
            report_res = self.simpleperf_report(str(local_perf), "comm,dso,symbol", 0.5, 9999)
            report_text = report_res.get("report") or report_res.get("error", "(report failed)")
            local_report.write_text(report_text)

            result_dict: dict[str, Any] = {
                "pid": pid, "event": "cpu-clock:u", "duration_s": duration_s,
                "perf_data": str(local_perf), "report": str(local_report),
                "report_preview": report_text[:3000], "method": "app_profiler",
            }
            if gecko_profile:
                self._try_gecko(local_perf, out, ts, toolkit, result_dict)
            return result_dict

        # Device simpleperf fallback
        try:
            simpleperf_cmd = provision_bridge.ensure_simpleperf(self.serial)
        except RuntimeError as e:
            return {"error": str(e)}

        remote_path = f"/data/local/tmp/perf_{ts}.data"
        fallback_events = ["cpu-cycles", "task-clock", "instructions", "cpu-clock"]
        if event not in fallback_events:
            fallback_events.insert(0, event)
        last_stderr = ""

        for try_event in fallback_events:
            r = self.adb.run(
                "shell", simpleperf_cmd, "record",
                "-p", str(pid), "-e", try_event, "-f", str(freq),
                "--call-graph", call_graph, "--duration", str(duration_s),
                "-o", remote_path, check=False, timeout=duration_s + 60,
            )
            if r.returncode == 0:
                event = try_event
                break
            last_stderr = (r.stderr or "").strip()
            if "Permission denied" in last_stderr:
                return {"error": f"simpleperf record failed: {last_stderr}"}
            if "is not supported" not in last_stderr:
                return {"error": f"simpleperf record failed: {last_stderr}"}
            self.adb.run("shell", "rm", "-f", remote_path, check=False)
        else:
            return {"error": f"simpleperf record failed (no supported event): {last_stderr}"}

        self.adb.pull(remote_path, str(local_perf))
        if not local_perf.exists():
            return {"error": "Failed to pull perf.data from device"}

        rep_r = self.adb.run(
            "shell", simpleperf_cmd, "report", "-i", remote_path,
            "--sort", "comm,dso,symbol", "-n", "--percent-limit", "0.5",
            check=False, timeout=60,
        )
        report_text = rep_r.stdout or "(empty report)"
        local_report.write_text(report_text)
        self.adb.run("shell", "rm", "-f", remote_path, check=False)

        result_dict = {
            "pid": pid, "event": event, "duration_s": duration_s,
            "perf_data": str(local_perf), "report": str(local_report),
            "report_preview": report_text[:3000],
        }
        if gecko_profile:
            gecko = provision_bridge.convert_to_gecko_profile(
                local_perf, out / f"perf_{ts}", serial=self.serial,
            )
            if gecko:
                result_dict["gecko_profile"] = str(gecko)
                result_dict["firefox_profiler_hint"] = f"Load {gecko} at https://profiler.firefox.com"
        return result_dict

    def _try_gecko(
        self, local_perf: Path, out: Path, ts: int,
        toolkit: Any, result_dict: dict,
    ) -> None:
        gecko_path = out / f"perf_{ts}.json.gz"
        if provision_bridge.run_gecko_profile_generator(toolkit, local_perf, gecko_path):
            result_dict["gecko_profile"] = str(gecko_path)
            result_dict["firefox_profiler_hint"] = f"Load {gecko_path} at https://profiler.firefox.com"
        else:
            gecko = provision_bridge.convert_to_gecko_profile(
                local_perf, out / f"perf_{ts}", serial=self.serial,
            )
            if gecko:
                result_dict["gecko_profile"] = str(gecko)
                result_dict["firefox_profiler_hint"] = f"Load {gecko} at https://profiler.firefox.com"

    def simpleperf_report(
        self,
        perf_data_path: str,
        sort_keys: str = "comm,dso,symbol",
        percent_limit: float = 0.5,
        max_lines: int = 80,
    ) -> dict:
        local = Path(perf_data_path)
        if not local.exists():
            return {"error": f"File not found: {perf_data_path}"}

        try:
            simpleperf_cmd = provision_bridge.ensure_simpleperf(self.serial)
        except RuntimeError as e:
            return {"error": str(e)}

        remote = "/data/local/tmp/_tmp_perf_report.data"
        self.adb.push(str(local), remote)
        r = self.adb.run(
            "shell", simpleperf_cmd, "report", "-i", remote,
            "--sort", sort_keys, "-n", "--percent-limit", str(percent_limit),
            check=False, timeout=60,
        )
        self.adb.run("shell", "rm", "-f", remote, check=False)
        lines = (r.stdout or "").splitlines()
        return {
            "total_lines": len(lines),
            "report": "\n".join(lines[:max_lines]),
            "truncated": len(lines) > max_lines,
        }

    def simpleperf_flamegraph(
        self,
        perf_data_path: str,
        output_dir: str = "/tmp/atrace",
        ndk_path: str | None = None,
        firefox_profiler: bool = True,
    ) -> dict:
        local = Path(perf_data_path)
        if not local.exists():
            return {"error": f"File not found: {perf_data_path}"}

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        result: dict[str, Any] = {"perf_data": str(local)}

        if firefox_profiler:
            try:
                gecko = provision_bridge.convert_to_gecko_profile(
                    local, out / local.stem, serial=self.serial,
                )
                if gecko:
                    result.update(
                        gecko_profile=str(gecko),
                        firefox_profiler_hint="Load at https://profiler.firefox.com",
                        method="traceconv → gecko JSON",
                    )
                    return result
            except Exception as e:
                result["gecko_error"] = str(e)

        svg_path = out / (local.stem + "_flamegraph.svg")
        candidates: list[Path] = []
        for base in [ndk_path, os.environ.get("ANDROID_NDK_HOME"), os.environ.get("NDK_HOME")]:
            if base:
                candidates += [
                    Path(base) / "simpleperf" / "inferno.sh",
                    Path(base) / "simpleperf" / "inferno.py",
                ]
        which = shutil.which("inferno.sh") or shutil.which("inferno")
        if which:
            candidates.insert(0, Path(which))
        inferno = next((p for p in candidates if p.exists()), None)
        if inferno:
            r = subprocess.run(
                ["bash", str(inferno), "-sc", "--record_file", str(local), "-o", str(svg_path)],
                capture_output=True, text=True, check=False,
            )
            if r.returncode == 0 and svg_path.exists():
                result.update(flamegraph=str(svg_path), method="inferno.sh SVG")
                return result

        fl_pl = shutil.which("flamegraph.pl")
        if fl_pl:
            try:
                simpleperf_cmd = provision_bridge.ensure_simpleperf(self.serial)
                remote = "/data/local/tmp/_tmp_flame.data"
                self.adb.push(str(local), remote)
                stacks_r = self.adb.run(
                    "shell", simpleperf_cmd, "report-sample",
                    "-i", remote, "--print-event-count", check=False, timeout=60,
                )
                self.adb.run("shell", "rm", "-f", remote, check=False)
                r2 = subprocess.run(
                    ["flamegraph.pl"], input=stacks_r.stdout,
                    capture_output=True, text=True, check=False,
                )
                if r2.returncode == 0:
                    svg_path.write_text(r2.stdout)
                    result.update(flamegraph=str(svg_path), method="flamegraph.pl SVG")
                    return result
            except Exception as e:
                result["flamegraph_pl_error"] = str(e)

        result["warning"] = "Could not generate flamegraph automatically."
        result["hint"] = (
            "Alternatives:\n"
            "  • profiler.firefox.com: use convert_to_firefox_profile tool\n"
            "  • Android Studio: open perf.data via CPU Profiler"
        )
        return result

    # ── heapprofd ────────────────────────────────────────────

    def heapprofd_capture(
        self,
        package: str,
        duration_s: int = 10,
        output_dir: str = "/tmp/atrace",
        sampling_interval_bytes: int = 4096,
        block_client: bool = True,
        mode: str = "native",
    ) -> dict:
        # ── Preferred: atrace-tool heap ──
        if self.engine.available:
            ts = int(time.time())
            suffix = "heap_dump" if mode == "java-dump" else "heap"
            out_file = str(Path(output_dir) / f"{suffix}_{ts}.perfetto")
            result = self.engine.heap(
                package, duration_s, out_file,
                mode=mode if mode in ("native", "java-dump") else "native",
                sampling_bytes=sampling_interval_bytes,
                no_block=not block_client,
            )
            if result.success:
                return {**result.data, "method": "atrace-tool heap"}
            if mode == "java-dump":
                return {"status": result.status, "message": result.message}

        # ── Fallback: Python heapprofd (native only) ──
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        local_trace = out / f"heap_{ts}.perfetto"
        block_str = "true" if block_client else "false"
        config = (
            f'duration_ms: {duration_s * 1000}\n'
            f'buffers {{ size_kb: 262144  fill_policy: RING_BUFFER }}\n'
            f'data_sources {{ config {{ name: "android.heapprofd" target_buffer: 0\n'
            f'  heapprofd_config {{ sampling_interval_bytes: {sampling_interval_bytes}\n'
            f'    process_cmdline: "{package}" block_client: {block_str}\n'
            f'    shmem_size_bytes: 8388608 all_heaps: true }} }} }}\n'
        )

        script = _record_android_trace_script()
        if script is not None:
            return self._heapprofd_via_script(
                script, config, local_trace, duration_s, package,
                sampling_interval_bytes,
            )

        return self._heapprofd_via_perfetto(
            config, local_trace, duration_s, package,
            sampling_interval_bytes,
        )

    def _heapprofd_via_script(
        self, script: Path, config: str, local_trace: Path,
        duration_s: int, package: str, sampling_bytes: int,
    ) -> dict:
        with tempfile.NamedTemporaryFile("w", suffix=".pbtxt", delete=False) as tf:
            tf.write(config)
            config_path = tf.name
        try:
            cmd = [sys.executable, str(script), "-c", config_path, "-o", str(local_trace), "-n"]
            if self.serial:
                cmd += ["-s", self.serial]
            env = os.environ.copy()
            if self.serial:
                env["ANDROID_SERIAL"] = self.serial
            r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=duration_s + 120)
        finally:
            try:
                os.unlink(config_path)
            except OSError:
                pass

        if r.returncode != 0:
            return {"error": f"record_android_trace failed: {r.stderr or r.stdout or 'unknown'}"}
        if local_trace.exists() and local_trace.stat().st_size > 0:
            return {
                "package": package, "duration_s": duration_s,
                "sampling_interval_bytes": sampling_bytes,
                "trace": str(local_trace),
                "size_kb": local_trace.stat().st_size // 1024,
                "method": "record_android_trace",
            }
        return {"error": "Heap trace file missing or empty. App must be Profileable/Debuggable (Android 10+)."}

    def _heapprofd_via_perfetto(
        self, config: str, local_trace: Path,
        duration_s: int, package: str, sampling_bytes: int,
    ) -> dict:
        try:
            perfetto_cmd = provision_bridge.ensure_perfetto(self.serial, force_push=True)
        except RuntimeError as e:
            return {"error": str(e)}

        ts = int(time.time())
        remote_trace = f"/data/local/tmp/heap_{ts}.perfetto"
        with tempfile.NamedTemporaryFile("w", suffix=".pbtxt", delete=False) as tf:
            tf.write(config)
            config_local = tf.name
        remote_cfg = f"/data/local/tmp/heap_cfg_{ts}.pbtxt"

        self.adb.push(config_local, remote_cfg)
        os.unlink(config_local)

        r = self.adb.run(
            "shell", perfetto_cmd, "--config", remote_cfg, "--txt",
            "-o", remote_trace, check=False, timeout=duration_s + 120,
        )
        self.adb.run("shell", "rm", "-f", remote_cfg, check=False)

        stderr = (r.stderr or "").strip()
        if r.returncode != 0 and "Tracing session" not in stderr:
            return {"error": f"heapprofd failed: {stderr}"}

        self.adb.pull(remote_trace, str(local_trace))
        self.adb.run("shell", "rm", "-f", remote_trace, check=False)

        if not local_trace.exists() or local_trace.stat().st_size == 0:
            return {"error": "Heap trace empty. App must be Profileable/Debuggable (Android 10+)."}

        return {
            "package": package, "duration_s": duration_s,
            "sampling_interval_bytes": sampling_bytes,
            "trace": str(local_trace),
            "size_kb": local_trace.stat().st_size // 1024,
            "perfetto_binary": perfetto_cmd,
        }

    def heapprofd_analyze(self, trace_path: str, top_n: int = 20) -> dict:
        return {"trace": trace_path, "action": "analyze_heap", "top_n": top_n}
