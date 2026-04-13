"""App HTTP client — communicates with the ATrace SDK TraceServer embedded in the app.

Protocol: all requests are ``GET http://localhost:<port>/?action=<action>&...``
forwarded through ADB port-forward.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from atrace_device.adb_bridge import AdbBridge

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


class AppHttpClient:
    """HTTP client for the ATrace SDK in-app server."""

    def __init__(self, adb: AdbBridge, port: int = 9090, package: str | None = None):
        self._adb = adb
        self.port = port
        self.package = package
        self._forwarded = False
        self._device_port: int | None = None

    # ── Connection ───────────────────────────────────────────

    def setup_forward(self) -> None:
        if self._forwarded:
            return
        device_port = self.port
        if self.package:
            discovered = self._adb.get_http_port_from_content_provider(self.package)
            if discovered and discovered > 0:
                device_port = discovered
        self._device_port = device_port
        self._adb.forward(self.port, device_port)
        self._forwarded = True

    def try_setup_forward(self) -> bool:
        if self._forwarded:
            return True
        device_port = self.port
        if self.package:
            discovered = self._adb.get_http_port_from_content_provider(self.package)
            if discovered is None:
                pass
            elif discovered <= 0:
                return False
            else:
                device_port = discovered
        try:
            self._device_port = device_port
            self._adb.forward(self.port, device_port)
            self._forwarded = True
            return True
        except Exception:
            return False

    def check_http_reachable(self) -> bool:
        import httpx
        if not self.try_setup_forward():
            return False
        try:
            resp = httpx.get(f"http://127.0.0.1:{self.port}/?action=status", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def not_reachable_error(self) -> dict:
        pkg = self.package or "<package>"
        return {
            "error": "atrace_http_not_reachable",
            "message": _APP_NOT_REACHABLE_MSG.format(package=pkg),
            "package": pkg, "port": self.port,
        }

    def remove_forward(self) -> None:
        if self._forwarded:
            self._adb.remove_forward(self.port)
            self._forwarded = False

    # ── HTTP helpers ─────────────────────────────────────────

    def _get(self, params: dict[str, str]) -> dict | None:
        import httpx
        self.setup_forward()
        url = f"http://127.0.0.1:{self.port}/?{urlencode(params)}"
        try:
            resp = httpx.get(url, timeout=60)
            if resp.headers.get("content-type", "").startswith("application/json"):
                return resp.json()
            return {"raw": resp.text}
        except Exception as e:
            return {"error": str(e)}

    def _download(self, name: str, dest: str) -> None:
        import httpx
        self.setup_forward()
        url = f"http://127.0.0.1:{self.port}/?action=download&name={name}"
        with httpx.stream("GET", url, timeout=120) as resp:
            with open(dest, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=65536):
                    f.write(chunk)

    # ── Status / info ────────────────────────────────────────

    def app_status(self) -> dict:
        return self._get({"action": "status"}) or {}

    def app_debug_info(self) -> dict:
        return self._get({"action": "query", "name": "debug"}) or {}

    def app_info(self) -> dict:
        return self._get({"action": "info"}) or {}

    def is_ready(self) -> bool:
        return self.app_status().get("initialized", False)

    # ── Trace control ────────────────────────────────────────

    def start_trace(self) -> dict:
        return self._get({"action": "start"}) or {}

    def stop_trace(self) -> dict:
        return self._get({"action": "stop"}) or {}

    def pause_trace(self) -> dict:
        return self._get({"action": "pause"}) or {}

    def resume_trace(self) -> dict:
        return self._get({"action": "resume"}) or {}

    def clean_traces(self) -> dict:
        return self._get({"action": "clean"}) or {}

    # ── Plugin management ────────────────────────────────────

    def list_plugins(self) -> dict:
        return self._get({"action": "plugins"}) or {}

    def toggle_plugin(self, plugin_id: str, enable: bool) -> dict:
        return self._get({
            "action": "plugins", "id": plugin_id,
            "enable": str(enable).lower(),
        }) or {}

    # ── Watch patterns ───────────────────────────────────────

    def list_watch_patterns(self) -> dict:
        return self._get({"action": "watch", "op": "list"}) or {}

    def add_watch_pattern(self, pattern: str) -> dict:
        return self._get({"action": "watch", "op": "add", "pattern": pattern}) or {}

    def add_watch_rule(self, scope: str, value: str) -> dict:
        return self._get({
            "action": "watch", "op": "add", "scope": scope, "value": value,
        }) or {}

    def add_watch_entries(self, entries: str) -> dict:
        return self._get({"action": "watch", "op": "add", "entries": entries}) or {}

    def add_watch_patterns(self, patterns: list[str], scope: str | None = None) -> dict:
        cleaned = [p.strip() for p in patterns if p.strip()]
        if not cleaned:
            return {}
        if scope:
            parts = "|".join(f"{scope}:{p}" for p in cleaned)
            return self.add_watch_entries(parts)
        joined = ";".join(cleaned)
        return self._get({"action": "watch", "op": "add", "patterns": joined}) or {}

    def remove_watch_pattern(self, pattern: str) -> dict:
        return self._get({"action": "watch", "op": "remove", "pattern": pattern}) or {}

    def remove_watch_entry(
        self, entry: str | None = None,
        scope: str | None = None, value: str | None = None,
    ) -> dict:
        params: dict[str, str] = {"action": "watch", "op": "remove"}
        if entry:
            params["entry"] = entry
        if scope:
            params["scope"] = scope
        if value:
            params["value"] = value
        return self._get(params) or {}

    def clear_watch_patterns(self) -> dict:
        return self._get({"action": "watch", "op": "clear"}) or {}

    # ── Method hook ──────────────────────────────────────────

    def hook_method(
        self, class_name: str, method_name: str,
        signature: str, is_static: bool = False,
    ) -> dict:
        return self._get({
            "action": "hook", "op": "add",
            "class": class_name, "method": method_name,
            "sig": signature, "static": str(is_static).lower(),
        }) or {}

    def unhook_method(
        self, class_name: str, method_name: str,
        signature: str, is_static: bool = False,
    ) -> dict:
        return self._get({
            "action": "hook", "op": "remove",
            "class": class_name, "method": method_name,
            "sig": signature, "static": str(is_static).lower(),
        }) or {}

    # ── Sampling config ──────────────────────────────────────

    def get_sampling_config(self) -> dict:
        return self._get({"action": "sampling"}) or {}

    def set_sampling_interval(
        self, main_interval_ns: int = 0, other_interval_ns: int = 0,
    ) -> dict:
        params: dict[str, str] = {"action": "sampling"}
        if main_interval_ns > 0:
            params["main"] = str(main_interval_ns)
        if other_interval_ns > 0:
            params["other"] = str(other_interval_ns)
        return self._get(params) or {}

    # ── Threads / markers / stack capture ────────────────────

    def list_threads(self) -> dict:
        return self._get({"action": "query", "name": "threads"}) or {}

    def add_mark(self, name: str) -> dict:
        return self._get({"action": "mark", "name": name}) or {}

    def capture_stack(self, force: bool = False) -> dict:
        return self._get({"action": "capture", "force": str(force).lower()}) or {}
