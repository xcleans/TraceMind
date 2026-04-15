"""Local HTTP serving + Perfetto UI deep-link.

Mirrors the ``record_android_trace`` approach: start a one-shot HTTP server on
``127.0.0.1:9001`` with CORS headers so ``https://ui.perfetto.dev`` can fetch the
trace, then (optionally) open a browser tab with a deep-link URL.

Shared by ``atrace-mcp`` and ``atrace-service``.
"""

from __future__ import annotations

import http.server
import json
import logging
import os
import socketserver
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path

LOG = logging.getLogger("atrace.capture")

PERFETTO_ORIGIN = "https://ui.perfetto.dev"
PERFETTO_LOCALHOST_PORT = 9001


# ── HTTP handler ─────────────────────────────────────────────────────────────

class _TraceHttpHandler(http.server.SimpleHTTPRequestHandler):
    """Serve exactly one file with CORS for the Perfetto UI origin."""

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", self.server.allow_origin)
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/" + self.server.expected_fname:
            self.send_error(404, "File not found")
            return
        self.server.fname_get_completed = True
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        self.send_error(404, "File not found")

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: ARG002
        LOG.debug("TraceHttpHandler: %s", fmt % args)


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PerfettoOpenResult:
    """Outcome of an ``open_trace_in_perfetto`` call."""
    perfetto_url: str
    local_http_url: str
    opened_browser: bool
    fetched_by_ui: bool
    timed_out: bool
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "perfetto_url": self.perfetto_url,
            "local_http_url": self.local_http_url,
            "opened_browser": self.opened_browser,
            "fetched_by_ui": self.fetched_by_ui,
            "timed_out": self.timed_out,
            "error": self.error,
        }


# ── URL builder (no server, no blocking) ─────────────────────────────────────

def build_perfetto_deep_link(
    trace_download_url: str,
    *,
    origin: str = PERFETTO_ORIGIN,
) -> str:
    """Return a ui.perfetto.dev deep-link that loads the trace from *trace_download_url*."""
    return (
        f"{origin.rstrip('/')}/#!/?url={urllib.parse.quote(trace_download_url, safe='')}"
    )


# ── Full flow: local HTTP + browser open ─────────────────────────────────────

def open_trace_in_perfetto(
    trace_path: str,
    *,
    open_browser: bool = True,
    origin: str = PERFETTO_ORIGIN,
    port: int = PERFETTO_LOCALHOST_PORT,
    ui_url_params: list[str] | None = None,
    startup_commands_json: str | None = None,
    wait_for_ui_fetch: bool = True,
    wait_timeout_seconds: float = 120.0,
) -> PerfettoOpenResult:
    """Start a one-shot localhost server and optionally open the Perfetto UI.

    This is the same flow as ``record_android_trace``:
    1. ``http://127.0.0.1:9001/<file>`` serves the trace with CORS.
    2. Browser opens ``https://ui.perfetto.dev/#!/?url=http://127.0.0.1:9001/<file>``.
    3. (Optional) Wait until the UI fetches the file, then shut down.
    """
    path = Path(trace_path).expanduser().resolve()
    if not path.is_file():
        return PerfettoOpenResult(
            perfetto_url="", local_http_url="",
            opened_browser=False, fetched_by_ui=False, timed_out=False,
            error=f"Not a file: {path}",
        )

    listen_port = port if 0 < port <= 65535 else PERFETTO_LOCALHOST_PORT
    fname = path.name
    prev_cwd = os.getcwd()
    socketserver.TCPServer.allow_reuse_address = True

    try:
        os.chdir(path.parent)
        with socketserver.TCPServer(("127.0.0.1", listen_port), _TraceHttpHandler) as httpd:
            httpd.timeout = 1.0
            httpd.expected_fname = fname
            httpd.fname_get_completed = None
            httpd.allow_origin = origin.rstrip("/")

            address = (
                f"{origin.rstrip('/')}/#!/?url=http://127.0.0.1:{listen_port}/{fname}"
                "&referrer=record_android_trace"
            )

            params: list[str] = []
            if ui_url_params:
                params.extend(ui_url_params)
            if startup_commands_json:
                try:
                    json.loads(startup_commands_json)
                except (json.JSONDecodeError, TypeError) as exc:
                    return PerfettoOpenResult(
                        perfetto_url=address,
                        local_http_url=f"http://127.0.0.1:{listen_port}/{fname}",
                        opened_browser=False, fetched_by_ui=False, timed_out=False,
                        error=f"startup_commands_json is not valid JSON: {exc}",
                    )
                encoded = urllib.parse.quote(startup_commands_json)
                params.append(f"startupCommands={encoded}")
            if params:
                address += "&" + "&".join(params)

            opened = False
            if open_browser:
                try:
                    opened = bool(webbrowser.open_new_tab(address))
                except Exception:
                    LOG.exception("webbrowser.open_new_tab failed url=%s", address)

            timed_out = False
            fetched = False
            if wait_for_ui_fetch:
                deadline = time.monotonic() + max(5.0, wait_timeout_seconds)
                while httpd.fname_get_completed is None:
                    httpd.handle_request()
                    if time.monotonic() >= deadline:
                        timed_out = True
                        break
                fetched = httpd.fname_get_completed is True

            return PerfettoOpenResult(
                perfetto_url=address,
                local_http_url=f"http://127.0.0.1:{listen_port}/{fname}",
                opened_browser=opened,
                fetched_by_ui=fetched,
                timed_out=timed_out,
            )
    except OSError as exc:
        return PerfettoOpenResult(
            perfetto_url="", local_http_url="",
            opened_browser=False, fetched_by_ui=False, timed_out=False,
            error=f"Could not bind HTTP server on 127.0.0.1:{listen_port}: {exc}",
        )
    finally:
        os.chdir(prev_cwd)
