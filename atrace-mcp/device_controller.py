"""
ATrace device controller — manages ADB connection and app HTTP API.

Provides runtime control: start/stop tracing, query status,
download traces, trigger app scenarios via ADB, CPU profiling
via simpleperf, and heap profiling via Perfetto heapprofd.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import tool_provisioner

# record_android_trace 脚本（Mac/Linux/Windows），通过 stdin 传配置，避免设备端配置文件权限问题
def _record_android_trace_script() -> Path | None:
    """Return path to record_android_trace script, or None if not found."""
    base = Path(__file__).resolve().parent / "scripts"
    if sys.platform == "win32":
        script = base / "record_android_trace_win"
    else:
        script = base / "record_android_trace"
    return script if script.is_file() else None


class DeviceController:
    """Controls ATrace via ADB port-forward + HTTP API."""

    def __init__(self, serial: str | None = None, port: int = 9090, package: str | None = None):
        self.serial = serial
        self.port = port
        self.package = package
        self._forwarded = False
        self._device_port: int | None = None  # actual port on the device (may differ from self.port)

    def _adb(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        cmd = ["adb"]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += list(args)
        return subprocess.run(cmd, capture_output=True, text=True, check=check)

    # ── HTTP server availability ─────────────────────────────

    _APP_NOT_REACHABLE_MSG = (
        "ATrace HTTP server not reachable for package '{package}'. "
        "This tool requires atrace-core to be integrated into the app.\n"
        "Possible causes:\n"
        "  1. App is not running — launch it first\n"
        "  2. atrace-core not integrated — add the SDK dependency and initialise ATrace\n"
        "  3. ATrace.init() not called — call ATrace.init(context) in Application.onCreate()\n"
        "  4. Package name mismatch — ensure `-a`/package matches applicationId\n"
        "  5. ContentProvider not declared — check AndroidManifest.xml for AtracePortProvider\n"
        "Tip: `capture_trace` still works (system-only Perfetto trace, no app sampling)."
    )

    def setup_forward(self):
        """Establish ADB port-forward: localhost:self.port → device app port.

        Discovery order (mirrors atrace-tool HttpClient):
        1. ContentProvider content://<package>.atrace/atrace/port  (Release-friendly)
        2. Falls back to mapping self.port → self.port (legacy / debug build)
        """
        if self._forwarded:
            return
        device_port = self.port  # default: assume same port
        if self.package:
            discovered = self.get_http_port_from_content_provider(self.package)
            if discovered and discovered > 0:
                device_port = discovered
        self._device_port = device_port
        self._adb("forward", f"tcp:{self.port}", f"tcp:{device_port}")
        self._forwarded = True

    def try_setup_forward(self) -> bool:
        """Try to establish ADB port-forward; return False (no exception) if not reachable.

        Mirrors atrace-tool HttpClient.trySetupForward():
          - Queries ContentProvider for the actual device port
          - Returns True on success, False when the app HTTP server is not found
        """
        if self._forwarded:
            return True
        device_port = self.port
        if self.package:
            discovered = self.get_http_port_from_content_provider(self.package)
            if discovered is None:
                # ContentProvider not available — fall back to default port but warn
                pass
            elif discovered <= 0:
                return False
            else:
                device_port = discovered
        try:
            self._device_port = device_port
            self._adb("forward", f"tcp:{self.port}", f"tcp:{device_port}")
            self._forwarded = True
            return True
        except Exception:
            return False

    def check_http_reachable(self) -> bool:
        """Return True if the ATrace HTTP server responds to a status ping."""
        import httpx
        if not self.try_setup_forward():
            return False
        try:
            resp = httpx.get(
                f"http://127.0.0.1:{self.port}/?action=status",
                timeout=3,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def not_reachable_error(self) -> dict:
        """Return a structured error dict when the HTTP server is not reachable."""
        pkg = self.package or "<package>"
        return {
            "error": "atrace_http_not_reachable",
            "message": self._APP_NOT_REACHABLE_MSG.format(package=pkg),
            "package": pkg,
            "port": self.port,
        }

    def _http_get(self, params: dict[str, str]) -> dict | None:
        import httpx

        self.setup_forward()
        query = urlencode(params)
        url = f"http://127.0.0.1:{self.port}/?{query}"
        try:
            resp = httpx.get(url, timeout=60)
            if resp.headers.get("content-type", "").startswith("application/json"):
                return resp.json()
            return {"raw": resp.text}
        except Exception as e:
            return {"error": str(e)}

    def _http_download(self, name: str, dest: Path) -> Path:
        import httpx

        self.setup_forward()
        url = f"http://127.0.0.1:{self.port}/?action=download&name={name}"
        with httpx.stream("GET", url, timeout=120) as resp:
            with open(dest, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=65536):
                    f.write(chunk)
        return dest

    # ── App status / info ───────────────────────────────────

    def app_status(self) -> dict:
        return self._http_get({"action": "status"}) or {}

    def app_debug_info(self) -> dict:
        return self._http_get({"action": "query", "name": "debug"}) or {}

    def app_info(self) -> dict:
        return self._http_get({"action": "info"}) or {}

    def is_ready(self) -> bool:
        status = self.app_status()
        return status.get("initialized", False)

    def get_http_port_from_content_provider(self, package_name: str) -> int | None:
        """Read ATrace HTTP port via content://<package>.atrace/atrace/port (Release-friendly).

        Requires AtracePortProvider in the app (atrace-core manifest). Returns None if query fails.
        """
        uri = f"content://{package_name}.atrace/atrace/port"
        r = self._adb(
            "shell",
            "content",
            "query",
            "--uri",
            uri,
            check=False,
        )
        if r.returncode != 0:
            return None
        m = re.search(r"port=(-?\d+)", r.stdout)
        return int(m.group(1)) if m else None

    # ── Trace control ───────────────────────────────────────

    def start_trace(self) -> dict:
        return self._http_get({"action": "start"}) or {}

    def stop_trace(self) -> dict:
        return self._http_get({"action": "stop"}) or {}

    def pause_trace(self) -> dict:
        return self._http_get({"action": "pause"}) or {}

    def resume_trace(self) -> dict:
        return self._http_get({"action": "resume"}) or {}

    def clean_traces(self) -> dict:
        return self._http_get({"action": "clean"}) or {}

    # ── Plugin management ────────────────────────────────────

    def list_plugins(self) -> dict:
        return self._http_get({"action": "plugins"}) or {}

    def toggle_plugin(self, plugin_id: str, enable: bool) -> dict:
        return self._http_get({
            "action": "plugins",
            "id": plugin_id,
            "enable": str(enable).lower(),
        }) or {}

    # ── ArtMethod WatchList（HTTP 下发子串，匹配 PrettyMethod）────────────────

    def list_watch_patterns(self) -> dict:
        return self._http_get({"action": "watch", "op": "list"}) or {}

    def add_watch_pattern(self, pattern: str) -> dict:
        return self._http_get({"action": "watch", "op": "add", "pattern": pattern}) or {}

    def add_watch_rule(self, scope: str, value: str) -> dict:
        """Semantic rule: scope = package | class | method | substring."""
        return self._http_get({
            "action": "watch",
            "op": "add",
            "scope": scope,
            "value": value,
        }) or {}

    def add_watch_entries(self, entries: str) -> dict:
        """Batch semantic rules: 'package:com.a.|class:com.b.C|method:com.b.C.m'."""
        return self._http_get({"action": "watch", "op": "add", "entries": entries}) or {}

    def add_watch_patterns(
        self, patterns: list[str], scope: str | None = None
    ) -> dict:
        """Multiple substring patterns (semicolon), or same scope applied to each value."""
        cleaned = [p.strip() for p in patterns if p.strip()]
        if not cleaned:
            return {}
        if scope:
            parts = "|".join(f"{scope}:{p}" for p in cleaned)
            return self.add_watch_entries(parts)
        joined = ";".join(cleaned)
        return self._http_get({"action": "watch", "op": "add", "patterns": joined}) or {}

    def remove_watch_pattern(self, pattern: str) -> dict:
        return self._http_get({"action": "watch", "op": "remove", "pattern": pattern}) or {}

    def remove_watch_entry(
        self,
        entry: str | None = None,
        scope: str | None = None,
        value: str | None = None,
    ) -> dict:
        params: dict[str, str] = {"action": "watch", "op": "remove"}
        if entry:
            params["entry"] = entry
        if scope:
            params["scope"] = scope
        if value:
            params["value"] = value
        return self._http_get(params) or {}

    def clear_watch_patterns(self) -> dict:
        return self._http_get({"action": "watch", "op": "clear"}) or {}

    # ── 精确方法 Hook（entry_point 替换）────────────────────────────────────────

    def hook_method(
        self,
        class_name: str,
        method_name: str,
        signature: str,
        is_static: bool = False,
    ) -> dict:
        return self._http_get({
            "action": "hook",
            "op": "add",
            "class": class_name,
            "method": method_name,
            "sig": signature,
            "static": str(is_static).lower(),
        }) or {}

    def unhook_method(
        self,
        class_name: str,
        method_name: str,
        signature: str,
        is_static: bool = False,
    ) -> dict:
        return self._http_get({
            "action": "hook",
            "op": "remove",
            "class": class_name,
            "method": method_name,
            "sig": signature,
            "static": str(is_static).lower(),
        }) or {}

    # ── Sampling configuration ───────────────────────────────

    def get_sampling_config(self) -> dict:
        return self._http_get({"action": "sampling"}) or {}

    def set_sampling_interval(
        self, main_interval_ns: int = 0, other_interval_ns: int = 0
    ) -> dict:
        params: dict[str, str] = {"action": "sampling"}
        if main_interval_ns > 0:
            params["main"] = str(main_interval_ns)
        if other_interval_ns > 0:
            params["other"] = str(other_interval_ns)
        return self._http_get(params) or {}

    # ── Thread query ─────────────────────────────────────────

    def list_threads(self) -> dict:
        """List threads via ATrace HTTP API (requires ATrace SDK)."""
        return self._http_get({"action": "query", "name": "threads"}) or {}

    def list_process_threads(self, package: str) -> dict:
        """List threads of a process via ADB (no ATrace required).
        Returns tid, name, is_main for each thread.
        """
        pid = self.get_pid(package)
        if pid is None:
            return {"error": f"Process not found: {package}"}
        r = self._adb("shell", "ps", "-T", "-p", str(pid), check=False)
        if r.returncode != 0:
            return {"error": f"ps -T failed: {r.stderr}", "pid": pid}
        lines = (r.stdout or "").strip().split("\n")
        threads = []
        for i, line in enumerate(lines):
            parts = line.split(None, 9)  # USER PID TID PPID VSZ RSS WCHAN ADDR S CMD
            if len(parts) >= 3:
                tid_str = parts[2]  # TID column
                name = parts[9] if len(parts) > 9 else ""
                try:
                    tid_int = int(tid_str)
                    is_main = tid_int == pid
                    threads.append({"tid": tid_int, "name": name.strip(), "is_main": is_main})
                except ValueError:
                    pass
        return {"package": package, "pid": pid, "thread_count": len(threads), "threads": threads}

    # ── Runtime markers ──────────────────────────────────────

    def add_mark(self, name: str) -> dict:
        return self._http_get({"action": "mark", "name": name}) or {}

    def capture_stack(self, force: bool = False) -> dict:
        return self._http_get({
            "action": "capture",
            "force": str(force).lower(),
        }) or {}

    def download_trace(self, output_dir: str) -> dict[str, str]:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())

        sampling = out / f"sampling_{ts}.perfetto"
        mapping = out / f"sampling_{ts}.perfetto.mapping"

        self._http_download("sampling", sampling)
        self._http_download("sampling-mapping", mapping)

        return {
            "sampling": str(sampling),
            "mapping": str(mapping),
        }

    # ── ADB device control ──────────────────────────────────

    def list_devices(self) -> list[str]:
        r = self._adb("devices", check=False)
        lines = r.stdout.strip().split("\n")[1:]
        return [l.split("\t")[0] for l in lines if "\tdevice" in l]

    def cold_start_app(
        self,
        package: str,
        activity: str | None = None,
        force_stop_wait_ms: int = 500,
    ) -> str:
        self._adb("shell", "am", "force-stop", package)
        time.sleep(max(0, force_stop_wait_ms) / 1000.0)
        if activity:
            target = f"{package}/{activity}"
        else:
            target = package
        r = self._adb("shell", "monkey", "-p", package, "-c",
                       "android.intent.category.LAUNCHER", "1", check=False)
        return r.stdout + r.stderr

    def hot_start_app(self, package: str, home_wait_ms: int = 300) -> str:
        r = self._adb("shell", "input", "keyevent", "KEYCODE_HOME", check=False)
        time.sleep(max(0, home_wait_ms) / 1000.0)
        r2 = self._adb("shell", "monkey", "-p", package, "-c",
                        "android.intent.category.LAUNCHER", "1", check=False)
        return r2.stdout + r2.stderr

    def scroll_screen(
        self,
        duration_ms: int = 300,
        dy: int = 500,
        start_x: int = 540,
        start_y: int = 1200,
        end_x: int | None = None,
        end_y: int | None = None,
    ) -> str:
        """ADB `input swipe`.

        - If both ``end_x`` and ``end_y`` are set: swipe from (start_x, start_y) to (end_x, end_y).
        - Otherwise: end at (start_x, start_y - dy) — finger moves up by ``dy`` pixels.
        """
        if end_x is not None and end_y is not None:
            ex, ey = end_x, end_y
        elif end_x is not None or end_y is not None:
            raise ValueError("end_x and end_y must both be set for an explicit swipe end, or omit both")
        else:
            ex, ey = start_x, start_y - dy
        r = self._adb(
            "shell",
            "input",
            "swipe",
            str(start_x),
            str(start_y),
            str(ex),
            str(ey),
            str(max(1, duration_ms)),
            check=False,
        )
        return r.stdout or ""

    def tap(self, x: int, y: int) -> str:
        r = self._adb("shell", "input", "tap", str(x), str(y), check=False)
        return r.stdout

    def get_current_activity(self) -> str:
        r = self._adb("shell", "dumpsys", "activity", "activities",
                       check=False)
        for line in r.stdout.split("\n"):
            if "mResumedActivity" in line or "topResumedActivity" in line:
                return line.strip()
        return "unknown"

    # ── simpleperf — CPU profiling ────────────────────────────

    def get_pid(self, package: str) -> int | None:
        """Return PID of the first running process matching package."""
        r = self._adb("shell", "pidof", "-s", package, check=False)
        pid_str = r.stdout.strip()
        if pid_str.isdigit():
            return int(pid_str)
        # Fallback: ps -e
        r2 = self._adb("shell", "ps", "-e", check=False)
        for line in r2.stdout.splitlines():
            if package in line:
                parts = line.split()
                if len(parts) > 1 and parts[1].isdigit():
                    return int(parts[1])
        return None

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
        """CPU profiling via simpleperf.

        Preferred path: delegates to `atrace-tool cpu --json` which handles
        event fallback, pull, and report generation.
        Fallback: AOSP app_profiler.py, then on-device simpleperf record.
        """
        # ── Preferred: atrace-tool cpu ────────────────────────────────────────
        atrace_cmd = tool_provisioner.ensure_atrace_tool()
        if atrace_cmd:
            sub_args = [
                "-a", package,
                "-t", str(duration_s),
                "-o", output_dir,
                "-e", event,
                "-f", str(freq),
                "--call-graph", call_graph,
            ]
            result = self.run_atrace_subcommand("cpu", sub_args,
                                                timeout=duration_s + 60,
                                                atrace_tool_cmd=atrace_cmd)
            if result.get("status") == "success":
                result["method"] = "atrace-tool cpu"
                return result
            # Non-fatal: fall through to Python implementation
        # ── Fallback: Python implementation ──────────────────────────────────
        pid = self.get_pid(package)
        if pid is None:
            return {"error": f"Process not found: {package}"}

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        local_perf = out / f"perf_{ts}.data"
        local_report = out / f"perf_{ts}_report.txt"

        # ── Prefer AOSP app_profiler.py (Firefox Profiler guide) ─────────────────
        toolkit = tool_provisioner.ensure_simpleperf_toolkit()
        if toolkit and tool_provisioner.run_app_profiler(
            toolkit, package, duration_s, local_perf, self.serial
        ):
            report_res = self.simpleperf_report(
                str(local_perf), "comm,dso,symbol", 0.5, 9999
            )
            report_text = report_res.get("report", "(report failed)")
            if "error" in report_res:
                report_text = report_res["error"]
            local_report.write_text(report_text)

            result: dict = {
                "pid": pid,
                "event": "cpu-clock:u",
                "duration_s": duration_s,
                "perf_data": str(local_perf),
                "report": str(local_report),
                "report_preview": report_text[:3000],
                "method": "app_profiler",
            }
            if gecko_profile:
                gecko_path = out / f"perf_{ts}.json.gz"
                if tool_provisioner.run_gecko_profile_generator(
                    toolkit, local_perf, gecko_path
                ):
                    result["gecko_profile"] = str(gecko_path)
                    result["firefox_profiler_hint"] = (
                        f"Load {gecko_path} at https://profiler.firefox.com (drag-and-drop)"
                    )
                else:
                    gecko = tool_provisioner.convert_to_gecko_profile(
                        local_perf, out / f"perf_{ts}", serial=self.serial
                    )
                    if gecko:
                        result["gecko_profile"] = str(gecko)
                        result["firefox_profiler_hint"] = (
                            f"Load {gecko} at https://profiler.firefox.com (drag-and-drop)"
                        )
            return result

        # ── Fallback: device simpleperf record ───────────────────────────────────
        try:
            simpleperf_cmd = tool_provisioner.ensure_simpleperf(self.serial)
        except RuntimeError as e:
            return {"error": str(e)}

        remote_path = f"/data/local/tmp/perf_{ts}.data"

        # Event fallback when device/emulator doesn't support preferred event
        fallback_events = ["cpu-cycles", "task-clock", "instructions", "cpu-clock"]
        if event not in fallback_events:
            fallback_events.insert(0, event)
        last_stderr = ""

        for try_event in fallback_events:
            r = self._adb(
                "shell", simpleperf_cmd, "record",
                "-p", str(pid),
                "-e", try_event,
                "-f", str(freq),
                "--call-graph", call_graph,
                "--duration", str(duration_s),
                "-o", remote_path,
                check=False,
            )
            if r.returncode == 0:
                event = try_event
                break
            last_stderr = (r.stderr or "").strip()
            if "Permission denied" in last_stderr:
                return {"error": f"simpleperf record failed: {last_stderr}"}
            if "is not supported" not in last_stderr:
                return {"error": f"simpleperf record failed: {last_stderr}"}
            self._adb("shell", "rm", "-f", remote_path, check=False)
        else:
            return {"error": f"simpleperf record failed (no supported event): {last_stderr}"}

        self._adb("pull", remote_path, str(local_perf), check=False)
        if not local_perf.exists():
            return {"error": "Failed to pull perf.data from device"}

        rep_r = self._adb(
            "shell", simpleperf_cmd, "report",
            "-i", remote_path,
            "--sort", "comm,dso,symbol",
            "-n", "--percent-limit", "0.5",
            check=False,
        )
        report_text = rep_r.stdout or "(empty report)"
        local_report.write_text(report_text)
        self._adb("shell", "rm", "-f", remote_path, check=False)

        result = {
            "pid": pid,
            "event": event,
            "duration_s": duration_s,
            "perf_data": str(local_perf),
            "report": str(local_report),
            "report_preview": report_text[:3000],
        }
        if gecko_profile:
            gecko = tool_provisioner.convert_to_gecko_profile(
                local_perf, out / f"perf_{ts}", serial=self.serial
            )
            if gecko:
                result["gecko_profile"] = str(gecko)
                result["firefox_profiler_hint"] = (
                    f"Load {gecko} at https://profiler.firefox.com (drag-and-drop)"
                )
        return result

    def simpleperf_report(
        self,
        perf_data_path: str,
        sort_keys: str = "comm,dso,symbol",
        percent_limit: float = 0.5,
        max_lines: int = 80,
    ) -> dict:
        """Generate a text report from a local perf.data file.

        Pushes the file to device, runs simpleperf report, pulls result.
        Auto-provisions simpleperf if needed.
        """
        local = Path(perf_data_path)
        if not local.exists():
            return {"error": f"File not found: {perf_data_path}"}

        try:
            simpleperf_cmd = tool_provisioner.ensure_simpleperf(self.serial)
        except RuntimeError as e:
            return {"error": str(e)}

        remote = "/data/local/tmp/_tmp_perf_report.data"
        self._adb("push", str(local), remote, check=False)

        r = self._adb(
            "shell", simpleperf_cmd, "report",
            "-i", remote,
            "--sort", sort_keys,
            "-n", "--percent-limit", str(percent_limit),
            check=False,
        )
        self._adb("shell", "rm", "-f", remote, check=False)

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
        """Generate a flamegraph from perf.data.

        Priority:
          1. Firefox Profiler gecko JSON (via traceconv prebuilt, no NDK needed)
          2. NDK inferno.sh SVG flamegraph
          3. flamegraph.pl SVG (if on PATH)
        """
        local = Path(perf_data_path)
        if not local.exists():
            return {"error": f"File not found: {perf_data_path}"}

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        result: dict = {"perf_data": str(local)}

        # ── Option 1: Firefox Profiler gecko JSON (most portable) ──────────
        if firefox_profiler:
            try:
                gecko = tool_provisioner.convert_to_gecko_profile(
                    local, out / local.stem, serial=self.serial
                )
                if gecko:
                    result["gecko_profile"] = str(gecko)
                    result["firefox_profiler_hint"] = (
                        "Load at https://profiler.firefox.com "
                        "(drag-and-drop or 'Load a profile from file')"
                    )
                    result["method"] = "traceconv → gecko JSON"
                    return result
            except Exception as e:
                result["gecko_error"] = str(e)

        # ── Option 2: inferno.sh SVG ────────────────────────────────────────
        svg_path = out / (local.stem + "_flamegraph.svg")
        candidates = []
        for base in [ndk_path, os.environ.get("ANDROID_NDK_HOME"), os.environ.get("NDK_HOME")]:
            if base:
                candidates.extend([
                    Path(base) / "simpleperf" / "inferno.sh",
                    Path(base) / "simpleperf" / "inferno.py",
                ])
        which = shutil.which("inferno.sh") or shutil.which("inferno")
        if which:
            candidates.insert(0, Path(which))
        inferno = next((p for p in candidates if p and p.exists()), None)
        if inferno:
            r = subprocess.run(
                ["bash", str(inferno), "-sc", "--record_file", str(local), "-o", str(svg_path)],
                capture_output=True, text=True, check=False,
            )
            if r.returncode == 0 and svg_path.exists():
                result["flamegraph"] = str(svg_path)
                result["method"] = "inferno.sh SVG"
                return result

        # ── Option 3: flamegraph.pl ─────────────────────────────────────────
        fl_pl = shutil.which("flamegraph.pl")
        if fl_pl:
            try:
                simpleperf_cmd = tool_provisioner.ensure_simpleperf(self.serial)
                remote = "/data/local/tmp/_tmp_flame.data"
                self._adb("push", str(local), remote, check=False)
                stacks_r = self._adb(
                    "shell", simpleperf_cmd, "report-sample",
                    "-i", remote, "--print-event-count", check=False,
                )
                self._adb("shell", "rm", "-f", remote, check=False)
                r2 = subprocess.run(
                    ["flamegraph.pl"], input=stacks_r.stdout,
                    capture_output=True, text=True, check=False,
                )
                if r2.returncode == 0:
                    svg_path.write_text(r2.stdout)
                    result["flamegraph"] = str(svg_path)
                    result["method"] = "flamegraph.pl SVG"
                    return result
            except Exception as e:
                result["flamegraph_pl_error"] = str(e)

        result["warning"] = (
            "Could not generate flamegraph automatically. "
            "Set ANDROID_NDK_HOME or install flamegraph.pl."
        )
        result["hint"] = (
            "Alternatives:\n"
            "  • profiler.firefox.com: use convert_to_firefox_profile tool\n"
            "  • Android Studio: open perf.data via CPU Profiler\n"
            "  • adb shell simpleperf report-html -i perf.data -o report.html"
        )
        return result

    # ── heapprofd — Heap memory profiling (Perfetto) ──────────

    def heapprofd_capture(
        self,
        package: str,
        duration_s: int = 10,
        output_dir: str = "/tmp/atrace",
        sampling_interval_bytes: int = 4096,
        block_client: bool = True,
        mode: str = "native",
    ) -> dict:
        """Heap memory profiling via Perfetto.

        Modes (see https://perfetto.dev/docs/getting-started/memory-profiling):
          native     = heapprofd: sample malloc/free callstacks (not retroactive)
          java-dump  = java_hprof: full Java/Kotlin heap dump at trace end

        Requires Android 10+ (API 29+), app Profileable or Debuggable.

        Preferred path: delegates to `atrace-tool heap --json`.
        Fallback: Python record_android_trace implementation (native only).
        """
        # ── Preferred: atrace-tool heap ───────────────────────────────────────
        atrace_cmd = tool_provisioner.ensure_atrace_tool()
        if atrace_cmd:
            ts = int(time.time())
            suffix = "heap_dump" if mode == "java-dump" else "heap"
            out_file = str(Path(output_dir) / f"{suffix}_{ts}.perfetto")
            sub_args = [
                "-a", package,
                "-t", str(duration_s),
                "-o", out_file,
                "--mode", mode if mode in ("native", "java-dump") else "native",
            ]
            if mode == "native":
                sub_args += ["--sampling-bytes", str(sampling_interval_bytes)]
                if not block_client:
                    sub_args += ["--no-block"]
            result = self.run_atrace_subcommand("heap", sub_args,
                                                timeout=duration_s + 60,
                                                atrace_tool_cmd=atrace_cmd)
            if result.get("status") == "success":
                result["method"] = "atrace-tool heap"
                return result
            if mode == "java-dump":
                return result  # No Python fallback for java-dump
            # Non-fatal: fall through to Python implementation (native only)
        # ── Fallback: Python implementation (native heapprofd only) ───────────
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        local_trace = out / f"heap_{ts}.perfetto"

        # Aligned with Perfetto memory profiling doc:
        # https://perfetto.dev/docs/getting-started/memory-profiling
        # Requires Android 10+ (API 29+), app Profileable or Debuggable.
        block_str = "true" if block_client else "false"
        config = f"""\
duration_ms: {duration_s * 1000}
buffers {{
  size_kb: 262144
  fill_policy: RING_BUFFER
}}
data_sources {{
  config {{
    name: "android.heapprofd"
    target_buffer: 0
    heapprofd_config {{
      sampling_interval_bytes: {sampling_interval_bytes}
      process_cmdline: "{package}"
      block_client: {block_str}
      shmem_size_bytes: 8388608
      all_heaps: true
    }}
  }}
}}
"""

        # ── 优先使用 record_android_trace 脚本（配置经 stdin 传设备，无权限问题，支持 Mac/Windows） ──
        script = _record_android_trace_script()
        if script is not None:
            with tempfile.NamedTemporaryFile(
                "w", suffix=".pbtxt", delete=False
            ) as tf:
                tf.write(config)
                config_path = tf.name
            try:
                cmd = [
                    sys.executable,
                    str(script),
                    "-c", config_path,
                    "-o", str(local_trace),
                    "-n",
                ]
                if self.serial:
                    cmd.extend(["-s", self.serial])
                env = os.environ.copy()
                if self.serial:
                    env["ANDROID_SERIAL"] = self.serial
                r = subprocess.run(
                    cmd,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=duration_s + 120,
                )
            finally:
                try:
                    os.unlink(config_path)
                except OSError:
                    pass
            if r.returncode != 0:
                return {
                    "error": f"record_android_trace failed: {r.stderr or r.stdout or 'unknown'}",
                    "stdout": r.stdout,
                    "stderr": r.stderr,
                }
            if local_trace.exists() and local_trace.stat().st_size > 0:
                return {
                    "package": package,
                    "duration_s": duration_s,
                    "sampling_interval_bytes": sampling_interval_bytes,
                    "trace": str(local_trace),
                    "size_kb": local_trace.stat().st_size // 1024,
                    "method": "record_android_trace",
                    "hint": (
                        "Use analyze_heap_profile or load_trace to inspect. "
                        "Also openable at ui.perfetto.dev or profiler.firefox.com."
                    ),
                }
            return {
                "error": (
                    "Heap trace file missing or empty after record_android_trace. "
                    "App must be Profileable or Debuggable (Android 10+). See: "
                    "https://perfetto.dev/docs/getting-started/memory-profiling"
                ),
                "stdout": r.stdout,
                "stderr": r.stderr,
            }

        # ── Fallback: 设备上直接运行 perfetto，配置 push 到设备 ──
        try:
            perfetto_cmd = tool_provisioner.ensure_perfetto(self.serial, force_push=True)
        except RuntimeError as e:
            return {"error": str(e)}

        remote_trace = f"/data/local/tmp/heap_{ts}.perfetto"
        with tempfile.NamedTemporaryFile("w", suffix=".pbtxt", delete=False) as tf:
            tf.write(config)
            config_local = tf.name
        remote_cfg = f"/data/local/tmp/heap_cfg_{ts}.pbtxt"
        cfg_in_misc = False
        root_r = self._adb("root", check=False)
        if root_r.returncode == 0:
            misc_cfg = f"/data/misc/perfetto-configs/heap_cfg_{ts}.pbtxt"
            push_r = self._adb("push", config_local, misc_cfg, check=False)
            if push_r.returncode == 0:
                remote_cfg = misc_cfg
                cfg_in_misc = True
                perfetto_cmd = tool_provisioner.ensure_perfetto(self.serial, force_push=False)
        if not cfg_in_misc:
            self._adb("push", config_local, remote_cfg, check=False)
        os.unlink(config_local)

        r = self._adb(
            "shell", perfetto_cmd,
            "--config", remote_cfg,
            "--txt",
            "-o", remote_trace,
            check=False,
        )
        self._adb("shell", "rm", "-f", remote_cfg, check=False)
        if cfg_in_misc:
            self._adb("shell", "rm", "-f", f"/data/misc/perfetto-configs/heap_cfg_{ts}.pbtxt", check=False)

        stderr = (r.stderr or "").strip()
        if r.returncode != 0 and "Tracing session" not in stderr:
            return {"error": f"heapprofd failed: {stderr}", "stdout": r.stdout}

        self._adb("pull", remote_trace, str(local_trace), check=False)
        self._adb("shell", "rm", "-f", remote_trace, check=False)

        if not local_trace.exists() or local_trace.stat().st_size == 0:
            return {
                "error": (
                    "Heap trace file not found or empty. "
                    "App must be Profileable or Debuggable (Android 10+). "
                    "https://perfetto.dev/docs/getting-started/memory-profiling"
                ),
                "stderr": stderr,
                "perfetto_binary": perfetto_cmd,
            }

        return {
            "package": package,
            "duration_s": duration_s,
            "sampling_interval_bytes": sampling_interval_bytes,
            "trace": str(local_trace),
            "size_kb": local_trace.stat().st_size // 1024,
            "perfetto_binary": perfetto_cmd,
            "hint": (
                "Use analyze_heap_profile or load_trace to inspect. "
                "Also openable at ui.perfetto.dev or profiler.firefox.com."
            ),
        }

    def heapprofd_analyze(
        self,
        trace_path: str,
        top_n: int = 20,
    ) -> dict:
        """Quick heap allocation summary using Perfetto SQL queries.

        Extracts top allocators by retained size and allocation count.
        Delegates actual SQL to TraceAnalyzer — returns a concise summary dict.
        """
        # Defer actual query to TraceAnalyzer (circular import avoidance: return path only)
        return {
            "trace": trace_path,
            "action": "analyze_heap",
            "top_n": top_n,
        }

    # ── ADB device control ──────────────────────────────────

    def get_device_info(self) -> dict:
        def prop(key: str) -> str:
            r = self._adb("shell", "getprop", key, check=False)
            return r.stdout.strip()

        return {
            "model": prop("ro.product.model"),
            "sdk": prop("ro.build.version.sdk"),
            "android_version": prop("ro.build.version.release"),
            "abi": prop("ro.product.cpu.abi"),
            "manufacturer": prop("ro.product.manufacturer"),
        }

    # ── atrace-tool: unified JSON-protocol caller ────────────────────────────────

    def run_atrace_subcommand(
        self,
        subcommand: str,
        extra_args: list[str],
        timeout: int = 300,
        atrace_tool_cmd: list[str] | None = None,
    ) -> dict:
        """Invoke an atrace-tool subcommand with --json and return the parsed dict.

        This is the single gateway for all atrace-tool calls.  Every subcommand
        receives --json so stdout is a single well-formed JSON object that is
        easy to parse and forward to the MCP caller.

        Args:
            subcommand:      One of "capture" | "cpu" | "heap" | "devices"
            extra_args:      Subcommand-specific flags (e.g. ["-a", "pkg", "-t", "10"])
            timeout:         subprocess timeout in seconds
            atrace_tool_cmd: Override the base command; defaults to
                             tool_provisioner.ensure_atrace_tool()
        Returns:
            Parsed JSON dict, or {"status": "error", "message": ...} on failure.
        """
        base_cmd = atrace_tool_cmd or tool_provisioner.ensure_atrace_tool()
        if not base_cmd:
            return {
                "status": "error",
                "message": "atrace-tool not available",
                "hint": tool_provisioner.atrace_tool_build_hint(),
            }

        if self.serial:
            extra_args = ["-s", self.serial] + extra_args

        cmd = list(base_cmd) + ["--json", subcommand] + extra_args
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "message": f"atrace-tool {subcommand} timed out after {timeout}s",
                "cmd": " ".join(cmd),
            }
        except FileNotFoundError as e:
            return {
                "status": "error",
                "message": f"atrace-tool not found: {e}",
                "cmd": " ".join(cmd),
            }

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()

        # Try parsing JSON from stdout
        try:
            data = json.loads(stdout) if stdout else {}
            # Attach stderr tail for diagnostics if something went wrong
            if data.get("status") == "error" and stderr:
                data.setdefault("stderr_tail", stderr[-1000:])
            return data
        except json.JSONDecodeError:
            return {
                "status": "error",
                "message": f"atrace-tool {subcommand} returned non-JSON output",
                "returncode": result.returncode,
                "stdout_tail": stdout[-2000:],
                "stderr_tail": stderr[-1000:],
                "cmd": " ".join(cmd),
            }

    # ── atrace-tool: full pipeline (system trace + app trace → merged .perfetto) ─

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
        """Capture a merged Perfetto system trace + ATrace app sampling trace.

        Delegates to `atrace-tool capture --json` via run_atrace_subcommand().

        atrace-tool pipeline:
          1. record_android_trace → Perfetto (ftrace, sched, frametimeline, logcat…)
          2. HTTP start → ATrace SDK Java/native stack sampling
          3. HTTP stop → download sampling.trace + mapping
          4. Decode ATRC binary → Perfetto proto packets
          5. Concatenate system.trace + app packets → single merged .perfetto
        """
        out_path = Path(output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        sub_args: list[str] = [
            "-a", package,
            "-t", str(duration_s),
            "-o", str(out_path),
            "-port", str(port),
            "-b", buffer_size,
        ]
        if cold_start:
            sub_args += ["-r"]
            if activity:
                sub_args += ["-launcher", activity]
        if perfetto_config:
            sub_args += ["-c", perfetto_config]
        if proguard_mapping:
            sub_args += ["-m", proguard_mapping]
        if extra_args:
            sub_args += extra_args

        result = self.run_atrace_subcommand(
            "capture",
            sub_args,
            timeout=duration_s + 180,
            atrace_tool_cmd=atrace_tool_cmd,
        )

        if result.get("status") != "success":
            # Provide extra diagnostics for common capture failures
            result.setdefault("hint",
                "Common causes:\n"
                "  • App not running or ATrace SDK not initialised\n"
                "  • ADB disconnected during capture\n"
                "  • record_android_trace not bundled — rebuild: ./gradlew deployMcp"
            )
            return result

        # Enrich with separate app_trace.pb path if written
        merged = Path(result.get("merged_trace", output_file))
        app_trace = merged.parent / "app_trace.pb"
        if app_trace.exists():
            result["app_trace_pb"] = str(app_trace)
            result["app_trace_kb"] = app_trace.stat().st_size // 1024

        return result
