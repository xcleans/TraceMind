"""atrace-service — Standalone FastAPI HTTP service for Perfetto trace analysis.

Start with:
    cd atrace-service
    uv run uvicorn atrace_service.main:app --reload --port 7788

Or via the entry-point (after `pip install -e .`):
    atrace-service --port 7788

Interactive API docs: http://localhost:7788/docs
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from atrace_service.engine import get_analyzer
from atrace_service.routes.ai import router as ai_router
from atrace_service.routes.analysis import router as analysis_router
from atrace_service.routes.capture import router as capture_router
from atrace_service.routes.trace import router as trace_router
from atrace_service.routes.ui import router as ui_router

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="ATrace Analysis Service",
    description=(
        "Standalone HTTP wrapper around TraceAnalyzer — no MCP / Cursor required.\n\n"
        "Use this service as the backend for:\n"
        "- A Perfetto UI plugin (call `/analyze/{trace_id}/scroll/stream` for SSE)\n"
        "- CI regression gates (diff two `verdict` dicts)\n"
        "- Custom dashboards / Jupyter notebooks\n"
        "- The MCP server itself (optional — MCP can also import TraceAnalyzer directly)\n\n"
        "**Quick start**\n"
        "1. `POST /trace/load` with `{\"trace_path\": \"/path/to/file.perfetto\"}`\n"
        "2. Copy `trace_path` from the response, URL-encode it → `trace_id`\n"
        "3. Call any `/trace/{trace_id}/*` or `/analyze/{trace_id}/*` endpoint"
    ),
    version="0.1.0",
    license_info={"name": "Apache-2.0"},
)

# ── CORS (allow Perfetto UI at any origin during development) ─────────────────
# In production, restrict `allow_origins` to your Perfetto UI host.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(ui_router)
app.include_router(ai_router)
app.include_router(capture_router)
app.include_router(trace_router)
app.include_router(analysis_router)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "atrace-service"}


@app.get("/sessions", tags=["meta"], summary="List currently loaded trace sessions")
def sessions() -> dict[str, list[str]]:
    analyzer = get_analyzer()
    return {"loaded_traces": list(analyzer._sessions.keys())}


# ── Environment check ────────────────────────────────────────────────────────


def _probe_tool(name: str, args: list[str]) -> dict:
    binary = shutil.which(name)
    if not binary:
        return {"installed": False, "binary": None, "version": None}
    try:
        out = subprocess.check_output(
            [binary] + args, stderr=subprocess.STDOUT, timeout=5,
        ).decode(errors="replace").strip().splitlines()
        ver = out[0][:120] if out else ""
    except Exception as exc:
        ver = f"(error: {exc})"
    return {"installed": True, "binary": binary, "version": ver}


@app.get("/env-check", tags=["meta"], summary="Check required / optional tool availability")
def env_check() -> dict:
    """Probe adb, cursor CLI, perfetto, and workspace config.
    Returns install instructions for any missing tools."""

    tools: dict[str, dict] = {}

    tools["adb"] = _probe_tool("adb", ["version"])
    tools["adb"]["required_for"] = "device capture & trace pull"
    tools["adb"]["install"] = (
        "macOS:  brew install android-platform-tools\n"
        "Linux:  sudo apt install android-tools-adb\n"
        "All:    https://developer.android.com/tools/releases/platform-tools"
    )

    tools["cursor"] = _probe_tool("cursor", ["--version"])
    tools["cursor"]["required_for"] = "AI agent + MCP multi-step analysis"
    tools["cursor"]["install"] = (
        "1. Install Cursor IDE: https://cursor.sh\n"
        "2. Open Cursor → Cmd+Shift+P → 'Install cursor command'\n"
        "3. Verify: cursor --version"
    )

    tools["perfetto"] = _probe_tool("perfetto", ["--version"])
    if not tools["perfetto"]["installed"]:
        tools["perfetto"] = _probe_tool("trace_processor_shell", ["--version"])
    tools["perfetto"]["required_for"] = "trace processor (bundled via Python, usually auto-resolved)"
    tools["perfetto"]["install"] = (
        "Usually not needed — TraceAnalyzer uses the Python perfetto package.\n"
        "If needed:  pip install perfetto\n"
        "Or:         https://perfetto.dev/docs/quickstart/traceconv"
    )

    perfetto_pkg: dict = {"installed": False, "version": None}
    try:
        import importlib.metadata
        perfetto_pkg["version"] = importlib.metadata.version("perfetto")
        perfetto_pkg["installed"] = True
    except Exception:
        pass
    perfetto_pkg["required_for"] = "TraceProcessor SQL engine (core)"
    perfetto_pkg["install"] = "pip install perfetto"
    tools["perfetto_python"] = perfetto_pkg

    service_root = Path(__file__).resolve().parent.parent
    repo_root = service_root.parent
    mcp_json = repo_root / ".cursor" / "mcp.json"
    cli_json = repo_root / ".cursor" / "cli.json"

    workspace = {
        "repo_root": str(repo_root),
        "mcp_json": {"exists": mcp_json.is_file(), "path": str(mcp_json)},
        "cli_json": {"exists": cli_json.is_file(), "path": str(cli_json)},
    }

    missing = [name for name, info in tools.items() if not info.get("installed")]

    return {
        "all_ready": len(missing) == 0,
        "missing": missing,
        "tools": tools,
        "workspace": workspace,
    }


# ── Startup / Shutdown ────────────────────────────────────────────────────────

@app.on_event("shutdown")
def _on_shutdown() -> None:
    """Close all TraceProcessor sessions on graceful shutdown."""
    get_analyzer().close_all()


# ── CLI entry-point ───────────────────────────────────────────────────────────

def start() -> None:
    """Entry-point used by `atrace-service` script defined in pyproject.toml."""
    parser = argparse.ArgumentParser(description="ATrace HTTP analysis service")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=7788, help="Bind port (default: 7788)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev mode)")
    args = parser.parse_args()

    uvicorn.run(
        "atrace_service.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    start()
