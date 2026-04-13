"""Unified tool registry — single entry point for all provisioning."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from atrace_provision._adb import adb_run, device_abi, tool_on_device
from atrace_provision._download import CACHE_DIR
from atrace_provision._ndk import find_ndk
from atrace_provision.providers.atrace_tool import AtraceToolProvider
from atrace_provision.providers.perfetto import PerfettoProvider
from atrace_provision.providers.simpleperf import SimpleperfProvider
from atrace_provision.providers.simpleperf_toolkit import SimpleperfToolkitProvider
from atrace_provision.providers.traceconv import TraceconvProvider


class ToolRegistry:
    """Facade over all tool providers.

    Typical usage::

        reg = ToolRegistry()
        perfetto_path = reg.ensure_perfetto(serial="emulator-5554")
        atrace_cmd    = reg.ensure_atrace_tool()
    """

    def __init__(self, project_root: Path | None = None, bundled_toolkit: Path | None = None):
        self._perfetto = PerfettoProvider()
        self._simpleperf = SimpleperfProvider()
        self._traceconv = TraceconvProvider()
        self._atrace_tool = AtraceToolProvider(project_root)
        self._toolkit = SimpleperfToolkitProvider(bundled_toolkit)

    # ── Device-side tools ────────────────────────────────────

    def ensure_perfetto(self, serial: str | None = None, *, force_push: bool = False) -> str:
        return self._perfetto.resolve_device(serial, force_push=force_push)

    def ensure_simpleperf(self, serial: str | None = None) -> str:
        return self._simpleperf.resolve_device(serial)

    # ── Host-side tools ──────────────────────────────────────

    def get_traceconv_host(self) -> Path | None:
        return self._traceconv.resolve_host()

    def ensure_atrace_tool(self) -> list[str] | None:
        return self._atrace_tool.resolve_command()

    def atrace_tool_build_hint(self) -> str:
        return AtraceToolProvider.build_hint()

    # ── Simpleperf toolkit ───────────────────────────────────

    def ensure_simpleperf_toolkit(self, serial: str | None = None) -> Path | None:
        return self._toolkit.resolve_toolkit(serial)

    def run_app_profiler(
        self,
        toolkit_root: Path,
        package: str,
        duration_s: int,
        output_perf_path: Path,
        serial: str | None = None,
    ) -> bool:
        return SimpleperfToolkitProvider.run_app_profiler(
            toolkit_root, package, duration_s, output_perf_path, serial
        )

    def run_gecko_profile_generator(
        self,
        toolkit_root: Path,
        perf_data_path: Path,
        output_gecko_path: Path,
    ) -> bool:
        return SimpleperfToolkitProvider.run_gecko_profile_generator(
            toolkit_root, perf_data_path, output_gecko_path
        )

    # ── Gecko profile conversion ─────────────────────────────

    def convert_to_gecko_profile(
        self,
        perf_data_path: Path,
        output_path: Path,
        serial: str | None = None,
    ) -> Path | None:
        """Convert simpleperf ``perf.data`` to Firefox Profiler gecko JSON.

        Steps: push perf.data → ``simpleperf report-sample --protobuf`` on
        device → pull ``.perf.trace`` → ``traceconv profile`` on host.
        """
        traceconv = self.get_traceconv_host()
        if not traceconv:
            return None

        import subprocess

        remote_tmp = "/data/local/tmp"
        remote_data = f"{remote_tmp}/_conv_perf.data"
        remote_trace = f"{remote_tmp}/_conv_perf.trace"
        simpleperf_cmd = self.ensure_simpleperf(serial)

        adb_run("push", str(perf_data_path), remote_data, serial=serial)

        r = adb_run(
            "shell", simpleperf_cmd,
            "report-sample", "--show-callchain", "--protobuf",
            "-i", remote_data, "-o", remote_trace,
            serial=serial,
        )
        if r.returncode != 0:
            print(f"[provision] report-sample failed: {r.stderr}")
            return None

        local_trace = output_path.with_suffix(".perf.trace")
        adb_run("pull", remote_trace, str(local_trace), serial=serial)
        adb_run("shell", "rm", "-f", remote_data, remote_trace, serial=serial)

        if not local_trace.exists():
            return None

        if local_trace.stat().st_size < 64:
            print(f"[provision] perf.trace too small ({local_trace.stat().st_size} bytes)")
            return None

        gecko_path = output_path.with_suffix(".json.gz")
        r2 = subprocess.run(
            [str(traceconv), "profile", "--output", str(gecko_path), str(local_trace)],
            capture_output=True, text=True,
        )
        if r2.returncode != 0 or not gecko_path.exists():
            stderr = (r2.stderr or "").strip()
            print(f"[provision] traceconv failed: {stderr[:200]}")
            return None

        print(f"[provision] Gecko profile: {gecko_path}")
        return gecko_path

    # ── Device capability info ───────────────────────────────

    def device_info(self, serial: str | None = None) -> dict[str, Any]:
        def prop(key: str) -> str:
            r = adb_run("shell", "getprop", key, serial=serial)
            return r.stdout.strip()

        abi = prop("ro.product.cpu.abi")
        sdk = prop("ro.build.version.sdk")
        sdk_int = int(sdk) if sdk.isdigit() else 0
        ndk = find_ndk()

        return {
            "abi": abi,
            "sdk": sdk_int,
            "android_version": prop("ro.build.version.release"),
            "has_simpleperf": tool_on_device("simpleperf", serial),
            "has_perfetto": tool_on_device("perfetto", serial),
            "simpleperf_needs_push": not tool_on_device("simpleperf", serial),
            "perfetto_needs_download": not tool_on_device("perfetto", serial),
            "heapprofd_supported": sdk_int >= 28,
            "ndk_found": str(ndk) if ndk else None,
            "cache_dir": str(CACHE_DIR),
        }
