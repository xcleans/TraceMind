#!/usr/bin/env python3
"""Cross-platform starter for atrace-service.

Features:
  - stale listener cleanup on target port
  - .cursor bootstrap (mcp.json / cli.json / atrace-analysis.mdc)
  - MCP dependency bootstrap (uv, deployMcp, import checks)
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


REPO_ROOT = _repo_root()
SERVICE_DIR = Path(__file__).resolve().parents[1]
CURSOR_DIR = REPO_ROOT / ".cursor"
CURSOR_RULES_DIR = CURSOR_DIR / "rules"
MCP_DIR = REPO_ROOT / "platform" / "atrace-mcp"
MCP_JAR = REPO_ROOT / "platform" / "atrace-provision" / "atrace_provision" / "bundled_bin" / "atrace-tool.jar"


def _run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=check,
        text=True,
        capture_output=True,
    )


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        backup = path.with_suffix(path.suffix + ".bak")
        try:
            path.replace(backup)
        except Exception:
            pass
        return {}


def _save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ensure_cursor_configs() -> None:
    CURSOR_RULES_DIR.mkdir(parents=True, exist_ok=True)
    rule = CURSOR_RULES_DIR / "atrace-analysis.mdc"
    if not rule.exists():
        rule.write_text(
            """---
description: ATrace / Perfetto 分析规则（启动脚本自动生成）
alwaysApply: true
---

# ATrace 性能分析规则

1. 每次分析先 `load_trace(trace_path, process_name)`，再进行 overview / analyze / 下钻。
2. 帧预算按刷新率计算：60Hz=16.67ms，90Hz=11.11ms，120Hz=8.33ms，144Hz=6.94ms。
3. 优先使用 `analyze_scroll_performance` / `analyze_startup` / `analyze_jank`，SQL 仅用于补充。
4. 输出需包含：总览、分布、关键指标、最差帧分析、根因与可操作建议。
""",
            encoding="utf-8",
        )
        print(f"[startup] created default {rule}")

    mcp_file = CURSOR_DIR / "mcp.json"
    cli_file = CURSOR_DIR / "cli.json"

    mcp_data = _load_json(mcp_file)
    servers = mcp_data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    mcp_entry = {
        "command": "uv",
        "args": [
            "-q",
            "run",
            "--directory",
            str(MCP_DIR),
            "python",
            "run_mcp.py",
        ],
    }
    servers["atrace"] = mcp_entry
    if "atrace2" in servers:
        servers["atrace2"] = mcp_entry
    mcp_data["mcpServers"] = servers
    _save_json(mcp_file, mcp_data)

    cli_data = _load_json(cli_file)
    permissions = cli_data.get("permissions")
    if not isinstance(permissions, dict):
        permissions = {}
    allow = permissions.get("allow")
    if not isinstance(allow, list):
        allow = []
    for rule_item in ("Mcp(atrace, *)", "Mcp(atrace2, *)"):
        if rule_item not in allow:
            allow.append(rule_item)
    permissions["allow"] = allow
    deny = permissions.get("deny")
    if not isinstance(deny, list):
        permissions["deny"] = []
    cli_data["permissions"] = permissions
    _save_json(cli_file, cli_data)


def ensure_mcp_dependencies(skip: bool) -> None:
    if skip:
        print("[startup] skip MCP dependency init (--skip-mcp-init)")
        return

    if shutil.which("uv") is None:
        raise SystemExit("[startup] error: uv not found. Please install uv first.")

    if not MCP_JAR.is_file():
        print("[startup] atrace-tool.jar missing, running ./gradlew deployMcp ...")
        subprocess.run(["./gradlew", "deployMcp"], cwd=str(REPO_ROOT), check=True)

    if not MCP_JAR.is_file():
        raise SystemExit(f"[startup] error: missing {MCP_JAR} after deployMcp")

    print("[startup] checking MCP python dependencies ...")
    subprocess.run(
        [
            "uv",
            "run",
            "--directory",
            str(MCP_DIR),
            "python",
            "-c",
            (
                "import importlib; "
                "mods=['fastmcp','perfetto','atrace_capture','atrace_analyzer','atrace_device','atrace_provision']; "
                "[importlib.import_module(m) for m in mods]; "
                "print('mcp dependency check ok')"
            ),
        ],
        check=True,
    )


def _listener_pids_unix(port: int) -> list[int]:
    if shutil.which("lsof") is None:
        return []
    out = _run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], check=False).stdout
    pids: list[int] = []
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def _listener_pids_windows(port: int) -> list[int]:
    out = _run(["netstat", "-ano", "-p", "tcp"], check=False).stdout
    pids: set[int] = set()
    suffix = f":{port}"
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        local_addr = parts[1]
        state = parts[3].upper()
        pid_s = parts[4]
        if local_addr.endswith(suffix) and state == "LISTENING" and pid_s.isdigit():
            pids.add(int(pid_s))
    return sorted(pids)


def listener_pids(port: int) -> list[int]:
    if platform.system().lower().startswith("win"):
        return _listener_pids_windows(port)
    return _listener_pids_unix(port)


def _pid_cmd_unix(pid: int) -> str:
    out = _run(["ps", "-p", str(pid), "-o", "command="], check=False).stdout
    return out.strip()


def _pid_cmd_windows(pid: int) -> str:
    out = _run(
        ["powershell", "-NoProfile", "-Command", f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"],
        check=False,
    ).stdout
    return out.strip()


def pid_command(pid: int) -> str:
    if platform.system().lower().startswith("win"):
        return _pid_cmd_windows(pid)
    return _pid_cmd_unix(pid)


def _terminate_pid(pid: int, force: bool) -> None:
    if platform.system().lower().startswith("win"):
        cmd = ["taskkill", "/PID", str(pid), "/T", "/F"] if force else ["taskkill", "/PID", str(pid), "/T"]
        _run(cmd, check=False)
        return
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        return


def cleanup_port(port: int, force_clean: bool) -> None:
    pids = listener_pids(port)
    if not pids:
        return

    print(f"[startup] port {port} is occupied, checking listener(s)...")
    patterns = ("atrace-service", "atrace_service.main", "uvicorn")
    for pid in pids:
        cmd = pid_command(pid)
        if not cmd:
            continue
        allowed = force_clean or any(p in cmd for p in patterns)
        if allowed:
            print(f"[startup] terminating pid={pid} cmd={cmd}")
            _terminate_pid(pid, force=False)
        else:
            raise SystemExit(
                f"[startup] refusing to kill non-service process on port {port}:\n"
                f"          pid={pid} cmd={cmd}\n"
                "          use --force-clean to force kill."
            )

    time.sleep(1.0)
    for pid in listener_pids(port):
        print(f"[startup] forcing kill pid={pid}")
        _terminate_pid(pid, force=True)


def start_service(host: str, port: int, passthrough: list[str]) -> int:
    cmd = ["uv", "run", "atrace-service", "--host", host, "--port", str(port), *passthrough]
    print(f"[startup] starting atrace-service on {host}:{port}")
    proc = subprocess.run(cmd, cwd=str(SERVICE_DIR))
    return int(proc.returncode)


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=7788, type=int)
    parser.add_argument("--force-clean", action="store_true")
    parser.add_argument("--skip-mcp-init", action="store_true")
    return parser.parse_known_args(argv)


def main(argv: list[str] | None = None) -> int:
    args, passthrough = parse_args(argv or sys.argv[1:])
    ensure_cursor_configs()
    ensure_mcp_dependencies(skip=args.skip_mcp_init)
    cleanup_port(port=args.port, force_clean=args.force_clean)
    return start_service(host=args.host, port=args.port, passthrough=passthrough)


if __name__ == "__main__":
    raise SystemExit(main())
