"""CursorAgentRunner — subprocess facade for cursor CLI agent.

Architecture follows simpleperf/scripts patterns:
  - _find_binary  ← ToolFinder (cursor CLI resolution)
  - _iter_jsonl   ← ipc.py     (line-by-line streaming parse)
  - _parse_event  ← _stream_delta.py (JSONL event semantics)
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generator

# Unified logging bootstrap (best effort — works both installed and monorepo)
_repo_root = Path(__file__).resolve().parent.parent.parent
_logging_path = _repo_root / "_logging.py"
if _logging_path.is_file():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    try:
        from _logging import get_logger as _get_logger
        _get_logger("atrace.ai", log_file="atrace-ai.log")
    except Exception:
        pass

log = logging.getLogger("atrace.ai")


@dataclass
class AgentEvent:
    """Single parsed event from cursor agent JSONL stream."""
    kind: str       # init | text | tool_use | tool_result | done | error
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    text: str
    tool_calls: list[dict[str, Any]]
    cursor_session_id: str
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    is_error: bool = False


class CursorAgentRunner:
    """Manage cursor agent subprocess lifecycle.

    Binary resolution: shutil.which → known paths → None.
    Synchronous run: Popen → iterate stdout → parse JSONL → collect results.
    Streaming run: Popen → yield parsed events as they arrive.
    """

    def __init__(self, workspace_root: str | None = None) -> None:
        self._binary = self._find_binary()
        self._workspace = workspace_root or str(
            Path(__file__).resolve().parents[2]
        )

    @staticmethod
    def _find_binary() -> str | None:
        path = shutil.which("cursor")
        if path:
            return path
        for candidate in (
            "/usr/local/bin/cursor",
            os.path.expanduser("~/.cursor/bin/cursor"),
            "/opt/homebrew/bin/cursor",
        ):
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        return None

    @property
    def available(self) -> bool:
        return self._binary is not None

    @property
    def binary_path(self) -> str | None:
        return self._binary

    @property
    def workspace(self) -> str:
        return self._workspace

    def _build_argv(
        self,
        prompt: str,
        resume_id: str | None = None,
        *,
        stream_partial: bool = False,
    ) -> list[str]:
        assert self._binary
        args = [
            self._binary, "agent",
            "--print", "--approve-mcps", "--yolo",
            "--output-format", "stream-json",
        ]
        if stream_partial:
            args.append("--stream-partial-output")
        if resume_id:
            args += ["--resume", resume_id]
        args.append(prompt)
        return args

    def _start_process(
        self,
        argv: list[str],
        *,
        env_overrides: dict[str, str] | None = None,
    ) -> subprocess.Popen:
        log.info("cursor agent start: %s …", " ".join(argv[:8]))
        env = {**os.environ, "NO_COLOR": "1"}
        if env_overrides:
            env.update(env_overrides)
        return subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self._workspace,
            env=env,
        )

    @staticmethod
    def _iter_jsonl(stdout) -> Generator[dict[str, Any], None, None]:
        for raw in io.TextIOWrapper(stdout, encoding="utf-8", errors="replace"):
            raw = raw.rstrip("\n")
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue

    @staticmethod
    def _parse_event(ev: dict[str, Any]) -> AgentEvent:
        t = ev.get("type", "")

        if t == "system" and ev.get("subtype") == "init":
            return AgentEvent("init", {
                "session_id": ev.get("session_id", ""),
                "model": ev.get("model", ""),
            })

        if t == "assistant":
            for blk in ev.get("message", {}).get("content", []):
                btype = blk.get("type")
                if btype == "text":
                    return AgentEvent("text", {"text": blk.get("text", "")})
                if btype == "tool_use":
                    inp = blk.get("input", {})
                    summary_parts = []
                    for k in ("trace_path", "sql", "slice_id", "package",
                              "process", "thread_name", "duration_seconds"):
                        if k in inp:
                            summary_parts.append(f"{k}={str(inp[k])[:80]}")
                    return AgentEvent("tool_use", {
                        "name": blk.get("name", "?"),
                        "summary": ", ".join(summary_parts) or str(inp)[:120],
                    })

        if t == "tool":
            content = ev.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "") for c in content if isinstance(c, dict)
                )
            lines = str(content).strip().splitlines()
            return AgentEvent("tool_result", {
                "preview": lines[0][:120] if lines else "(empty)",
                "line_count": len(lines),
            })

        if t == "result":
            usage = ev.get("usage", {})
            return AgentEvent("done", {
                "is_error": ev.get("is_error", False),
                "duration_ms": ev.get("duration_ms", 0),
                "input_tokens": usage.get("inputTokens", 0),
                "output_tokens": usage.get("outputTokens", 0),
            })

        return AgentEvent("unknown", ev)

    # ── synchronous run ──────────────────────────────────────

    def run(
        self,
        prompt: str,
        resume_id: str | None = None,
        timeout: int = 180,
        trace_path_hint: str | None = None,
    ) -> AgentResult:
        if not self._binary:
            raise RuntimeError("cursor CLI not found")

        argv = self._build_argv(prompt, resume_id)
        env_overrides = (
            {"ATRACE_DEFAULT_TRACE_PATH": trace_path_hint}
            if trace_path_hint else None
        )
        proc = self._start_process(argv, env_overrides=env_overrides)

        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        cursor_sid = ""
        result_data: dict[str, Any] = {}

        try:
            for raw_ev in self._iter_jsonl(proc.stdout):
                parsed = self._parse_event(raw_ev)
                if parsed.kind == "init":
                    cursor_sid = parsed.data.get("session_id", "")
                elif parsed.kind == "text":
                    text_parts.append(parsed.data["text"])
                elif parsed.kind == "tool_use":
                    tool_calls.append(parsed.data)
                elif parsed.kind == "tool_result" and tool_calls:
                    tool_calls[-1]["result_preview"] = parsed.data.get("preview", "")
                elif parsed.kind == "done":
                    result_data = parsed.data
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            text_parts.append("\n\n[timeout: cursor agent exceeded time limit]")
            result_data["is_error"] = True
        except Exception as exc:
            proc.kill()
            proc.wait()
            raise RuntimeError(f"cursor agent process failed: {exc}") from exc

        return AgentResult(
            text="".join(text_parts),
            tool_calls=tool_calls,
            cursor_session_id=cursor_sid,
            duration_ms=result_data.get("duration_ms", 0),
            input_tokens=result_data.get("input_tokens", 0),
            output_tokens=result_data.get("output_tokens", 0),
            is_error=result_data.get("is_error", False),
        )

    # ── streaming run ────────────────────────────────────────

    def iter_events(
        self,
        prompt: str,
        resume_id: str | None = None,
        trace_path_hint: str | None = None,
    ) -> Generator[AgentEvent, None, None]:
        if not self._binary:
            log.error("[iter_events] cursor CLI binary not found")
            yield AgentEvent("error", {"message": "cursor CLI not found"})
            return

        argv = self._build_argv(prompt, resume_id, stream_partial=True)
        log.info("[iter_events] argv=%s", " ".join(argv[:10]))
        log.info("[iter_events] workspace=%s trace_hint=%s", self._workspace, trace_path_hint)
        env_overrides = (
            {"ATRACE_DEFAULT_TRACE_PATH": trace_path_hint}
            if trace_path_hint else None
        )
        proc = self._start_process(argv, env_overrides=env_overrides)
        log.info("[iter_events] process started pid=%s", proc.pid)

        event_count = 0
        try:
            for raw_ev in self._iter_jsonl(proc.stdout):
                parsed = self._parse_event(raw_ev)
                event_count += 1
                if parsed.kind == "tool_use":
                    log.info("[iter_events] tool_use: %s(%s)", parsed.data.get("name"), parsed.data.get("summary", ""))
                elif parsed.kind == "tool_result":
                    log.info("[iter_events] tool_result: %s (%d lines)", parsed.data.get("preview", "")[:80], parsed.data.get("line_count", 0))
                elif parsed.kind == "error":
                    log.error("[iter_events] error event: %s", parsed.data)
                elif parsed.kind == "done":
                    log.info("[iter_events] done: tokens_in=%s tokens_out=%s duration=%sms",
                             parsed.data.get("input_tokens"), parsed.data.get("output_tokens"), parsed.data.get("duration_ms"))
                yield parsed
            rc = proc.wait(timeout=10)
            log.info("[iter_events] process exited rc=%s events=%d", rc, event_count)
            if rc != 0:
                stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
                if stderr:
                    log.warning("[iter_events] stderr: %s", stderr[:500])
        except Exception as e:
            log.error("[iter_events] exception: %s", e)
            stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
            if stderr:
                log.warning("[iter_events] stderr on error: %s", stderr[:500])
            proc.kill()
            proc.wait()

    # ── MCP config probe ─────────────────────────────────────

    def check_mcp_config(self) -> dict[str, Any]:
        """Check .cursor/mcp.json and cli.json for atrace MCP readiness."""
        mcp_json = Path(self._workspace) / ".cursor" / "mcp.json"
        cli_json = Path(self._workspace) / ".cursor" / "cli.json"

        result: dict[str, Any] = {
            "workspace": self._workspace,
            "mcp_json_exists": mcp_json.is_file(),
            "cli_json_exists": cli_json.is_file(),
            "atrace_server_configured": False,
            "permissions_pre_approved": False,
        }

        if mcp_json.is_file():
            try:
                cfg = json.loads(mcp_json.read_text())
                servers = cfg.get("mcpServers", {})
                result["atrace_server_configured"] = "atrace" in servers
                result["mcp_servers"] = list(servers.keys())
            except Exception as exc:
                result["mcp_json_error"] = str(exc)

        if cli_json.is_file():
            try:
                cfg = json.loads(cli_json.read_text())
                perms = cfg.get("permissions", {}).get("allow", [])
                atrace_perms = [p for p in perms if "atrace" in str(p)]
                result["permissions_pre_approved"] = len(atrace_perms) > 0
                result["atrace_permission_count"] = len(atrace_perms)
            except Exception as exc:
                result["cli_json_error"] = str(exc)

        return result

    def full_status(self) -> dict[str, Any]:
        """Full readiness report for cursor-agent + MCP."""
        mcp_info = self.check_mcp_config()
        cursor_ok = self._binary is not None
        mcp_ok = mcp_info.get("atrace_server_configured", False)
        perms_ok = mcp_info.get("permissions_pre_approved", False)
        all_ready = cursor_ok and mcp_ok and perms_ok

        return {
            "ready": all_ready,
            "engine": "cursor-agent" if all_ready else "local-trace-analyzer",
            "cursor_cli": {"available": cursor_ok, "binary": self._binary},
            "mcp": mcp_info,
            "capabilities": {
                "multi_step_reasoning": all_ready,
                "tool_calling": all_ready,
                "slice_children_drill": True,
                "call_chain": True,
                "thread_states": True,
                "custom_sql": True,
                "analyze_startup": True,
                "analyze_jank": True,
                "scroll_performance": True,
            },
        }
