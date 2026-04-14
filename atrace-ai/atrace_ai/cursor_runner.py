"""CursorAgentRunner — subprocess facade for cursor CLI agent.

Architecture follows simpleperf/scripts patterns:
  - _find_binary  ← ToolFinder (cursor CLI resolution)
  - _iter_jsonl   ← ipc.py     (line-by-line streaming parse)
  - _parse_events ← JSONL event semantics (assistant + tool_call + tool + result)
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
    """Single parsed event from cursor agent JSONL stream.

    Kinds align with Cursor CLI ``stream-json`` (and optional
    ``--stream-partial-output``): ``init``, ``text``, ``tool_use``,
    ``tool_result``, ``done``, ``error``, ``unknown``.

    Native ``assistant`` blocks (``tool_use`` / ``text``) and IDE-style
    ``tool_call`` events (``subtype`` ``started`` / ``completed``) are
    normalized to ``tool_use`` + ``tool_result`` for a single consumer API.
    """
    kind: str
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
    def _tool_use_summary_from_input(inp: dict[str, Any]) -> str:
        summary_parts: list[str] = []
        for key in (
            "trace_path",
            "sql",
            "slice_id",
            "package",
            "process",
            "thread_name",
            "duration_seconds",
            "path",
            "command",
            "query",
        ):
            if key in inp:
                summary_parts.append(f"{key}={str(inp[key])[:80]}")
        return ", ".join(summary_parts) or str(inp)[:120]

    @staticmethod
    def _assistant_message_events(message: dict[str, Any]) -> list[AgentEvent]:
        """One JSON line may include multiple content blocks (text + tool_use)."""
        events: list[AgentEvent] = []
        for blk in message.get("content", []) or []:
            btype = blk.get("type")
            if btype == "text":
                text = blk.get("text", "")
                if text:
                    events.append(AgentEvent("text", {"text": text}))
            elif btype == "tool_use":
                inp = blk.get("input", {}) or {}
                events.append(AgentEvent("tool_use", {
                    "name": blk.get("name", "?"),
                    "summary": CursorAgentRunner._tool_use_summary_from_input(
                        inp if isinstance(inp, dict) else {}
                    ),
                    "input": inp if isinstance(inp, dict) else {},
                }))
        return events

    @staticmethod
    def _parse_cursor_mcp_tool_call(
        node: dict[str, Any],
    ) -> tuple[str, dict[str, Any], str] | None:
        """Parse Cursor ``mcpToolCall`` wire shape.

        Cursor nests the real MCP tool arguments under ``mcpToolCall.args.args``::

            mcpToolCall: {
              "args": {
                "name": "atrace-load_trace",
                "args": { "trace_path": "...", ... },  // actual MCP params
                "toolCallId": "...",
                "providerIdentifier": "atrace",
                "toolName": "load_trace"
              },
              "result": { ... }   // on completed events
            }

        Legacy flat shape (``mcpToolCall.name`` + ``mcpToolCall.args`` = params only)
        is handled in the caller when this returns None.
        """
        envelope = node.get("args")
        if not isinstance(envelope, dict):
            return None
        if not any(
            k in envelope for k in ("toolCallId", "toolName", "providerIdentifier")
        ):
            return None
        nested = envelope.get("args")
        tool_params: dict[str, Any] = nested if isinstance(nested, dict) else {}
        tn = str(envelope.get("toolName") or "").strip()
        if not tn:
            raw = str(envelope.get("name") or "").strip()
            if raw.startswith("atrace-"):
                tn = raw[7:]
            else:
                tn = raw or "mcp"
        tid = str(envelope.get("toolCallId") or "")
        return tn, tool_params, tid

    @staticmethod
    def _mcp_success_text_preview(success: dict[str, Any], limit: int = 600) -> str:
        """Flatten ``success.content[].text`` (including nested ``{text: {text: "..."}}``)."""
        content = success.get("content")
        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                t = item.get("text")
                if isinstance(t, dict):
                    inner = t.get("text")
                    if isinstance(inner, str):
                        chunks.append(inner)
                    elif isinstance(inner, dict) and "text" in inner:
                        chunks.append(str(inner.get("text", "")))
                elif isinstance(t, str):
                    chunks.append(t)
            if chunks:
                out = "\n".join(chunks)
                return out if len(out) <= limit else f"{out[: limit - 3]}..."
        try:
            s = json.dumps(success, ensure_ascii=False)
        except Exception:
            s = str(success)
        return s if len(s) <= limit else f"{s[: limit - 3]}..."

    @staticmethod
    def _parse_tool_call_started(ev: dict[str, Any]) -> AgentEvent | None:
        tc = ev.get("tool_call")
        if not isinstance(tc, dict):
            return None
        if "readToolCall" in tc:
            node = tc["readToolCall"]
            args = node.get("args", {}) if isinstance(node, dict) else {}
            path = args.get("path", "") if isinstance(args, dict) else ""
            return AgentEvent("tool_use", {
                "name": "readToolCall",
                "summary": f"path={str(path)[:200]}",
                "input": {"path": path},
            })
        if "writeToolCall" in tc:
            node = tc["writeToolCall"]
            args = node.get("args", {}) if isinstance(node, dict) else {}
            path = args.get("path", "") if isinstance(args, dict) else ""
            return AgentEvent("tool_use", {
                "name": "writeToolCall",
                "summary": f"path={str(path)[:200]}",
                "input": {"path": path},
            })
        if "mcpToolCall" in tc:
            node = tc["mcpToolCall"]
            if not isinstance(node, dict):
                return None
            parsed_mcp = CursorAgentRunner._parse_cursor_mcp_tool_call(node)
            if parsed_mcp:
                tool_name, tool_params, tid = parsed_mcp
                summary = CursorAgentRunner._tool_use_summary_from_input(tool_params)
                if not summary:
                    summary = (
                        "(MCP args empty in stream — model/host did not supply "
                        "trace_path/process_name)"
                        if not tool_params
                        else ""
                    )
                return AgentEvent("tool_use", {
                    "name": tool_name,
                    "summary": f"{tool_name} {summary}".strip(),
                    "input": tool_params,
                    "toolCallId": tid,
                })
            mcp_name = str(node.get("name", "") or "mcp")
            args = node.get("args")
            if not isinstance(args, dict):
                args = {}
            raw_args = node.get("arguments")
            if isinstance(raw_args, str) and raw_args.strip():
                try:
                    parsed = json.loads(raw_args)
                    if isinstance(parsed, dict):
                        args = {**args, **parsed}
                except (json.JSONDecodeError, TypeError):
                    args = {**args, "arguments_raw": raw_args[:500]}
            summary = (
                CursorAgentRunner._tool_use_summary_from_input(args)
                or ("(no args in started event)" if not args else "")
            )
            return AgentEvent("tool_use", {
                "name": mcp_name,
                "summary": f"{mcp_name} {summary}".strip(),
                "input": args,
                "toolCallId": node.get("toolCallId", ""),
            })
        for key, node in tc.items():
            if not isinstance(node, dict):
                continue
            args = node.get("args", {})
            summary = (
                CursorAgentRunner._tool_use_summary_from_input(args)
                if isinstance(args, dict)
                else str(node)[:160]
            )
            inner_name = node.get("name") if isinstance(node.get("name"), str) else None
            display_name = inner_name or key
            return AgentEvent("tool_use", {
                "name": display_name,
                "summary": summary or str(node)[:120],
                "input": args if isinstance(args, dict) else {},
            })
        return None

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_tool_call_completed(ev: dict[str, Any]) -> AgentEvent:
        tc = ev.get("tool_call")
        if not isinstance(tc, dict):
            return AgentEvent("tool_result", {"preview": "(empty)", "line_count": 0})
        if "readToolCall" in tc:
            node = tc["readToolCall"]
            if not isinstance(node, dict):
                return AgentEvent("tool_result", {"preview": "(empty)", "line_count": 0})
            res = node.get("result", {})
            if isinstance(res, dict) and "success" in res:
                succ = res["success"]
                lines = succ.get("totalLines", 0) if isinstance(succ, dict) else 0
                preview = f"read ok, {lines} lines"
                return AgentEvent("tool_result", {
                    "preview": preview[:200],
                    "line_count": CursorAgentRunner._safe_int(lines),
                })
            err = res.get("error", "read failed") if isinstance(res, dict) else "read failed"
            return AgentEvent("tool_result", {
                "preview": str(err)[:200],
                "line_count": 0,
            })
        if "writeToolCall" in tc:
            node = tc["writeToolCall"]
            if not isinstance(node, dict):
                return AgentEvent("tool_result", {"preview": "(empty)", "line_count": 0})
            res = node.get("result", {})
            if isinstance(res, dict) and "success" in res:
                succ = res["success"]
                created = succ.get("linesCreated", 0) if isinstance(succ, dict) else 0
                preview = f"write ok, {created} lines"
                return AgentEvent("tool_result", {
                    "preview": preview[:200],
                    "line_count": CursorAgentRunner._safe_int(created),
                })
            err = res.get("error", "write failed") if isinstance(res, dict) else "write failed"
            return AgentEvent("tool_result", {
                "preview": str(err)[:200],
                "line_count": 0,
            })
        if "mcpToolCall" in tc:
            node = tc["mcpToolCall"]
            if not isinstance(node, dict):
                return AgentEvent("tool_result", {"preview": "(empty)", "line_count": 0})
            res = node.get("result", {})
            if isinstance(res, dict):
                if "success" in res:
                    succ = res["success"]
                    if isinstance(succ, dict):
                        text = CursorAgentRunner._mcp_success_text_preview(succ)
                    else:
                        text = json.dumps(succ, ensure_ascii=False)[:400]
                    lines = len(text.splitlines()) if text else 0
                    return AgentEvent("tool_result", {
                        "preview": text or "mcp ok",
                        "line_count": max(lines, 1) if text else 0,
                    })
                if "error" in res:
                    err = res["error"]
                    return AgentEvent("tool_result", {
                        "preview": str(err)[:200],
                        "line_count": 0,
                    })
            text = json.dumps(res, ensure_ascii=False)[:400] if res else ""
            return AgentEvent("tool_result", {
                "preview": text[:200] or "(empty)",
                "line_count": 0,
            })
        for _key, node in tc.items():
            if not isinstance(node, dict):
                continue
            res = node.get("result", node)
            text = json.dumps(res, ensure_ascii=False)[:500] if res is not None else ""
            lines = str(res).strip().splitlines() if res is not None else []
            return AgentEvent("tool_result", {
                "preview": text[:200] or "(empty)",
                "line_count": len(lines),
            })
        return AgentEvent("tool_result", {"preview": "(empty)", "line_count": 0})

    @staticmethod
    def _parse_events(ev: dict[str, Any]) -> list[AgentEvent]:
        """Map one JSONL object to zero or more AgentEvents (official stream-json)."""
        t = ev.get("type", "")
        subtype = ev.get("subtype") or ""

        if t == "system" and subtype == "init":
            return [AgentEvent("init", {
                "session_id": ev.get("session_id", ""),
                "model": ev.get("model", ""),
            })]

        if t == "assistant":
            msg = ev.get("message", {})
            if isinstance(msg, dict):
                parsed = CursorAgentRunner._assistant_message_events(msg)
                if parsed:
                    return parsed

        if t == "tool_call" and subtype == "started":
            started = CursorAgentRunner._parse_tool_call_started(ev)
            if started:
                return [started]
            return [AgentEvent("tool_use", {
                "name": "tool_call",
                "summary": str(ev.get("tool_call", ""))[:120],
                "input": {},
            })]

        if t == "tool_call" and subtype == "completed":
            return [CursorAgentRunner._parse_tool_call_completed(ev)]

        if t == "tool":
            content = ev.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "") for c in content if isinstance(c, dict)
                )
            lines = str(content).strip().splitlines()
            return [AgentEvent("tool_result", {
                "preview": lines[0][:120] if lines else "(empty)",
                "line_count": len(lines),
            })]

        if t == "result":
            usage = ev.get("usage", {}) or {}
            is_error = bool(ev.get("is_error", False))
            if subtype == "error":
                is_error = True
            elif subtype == "success":
                is_error = False
            return [AgentEvent("done", {
                "is_error": is_error,
                "subtype": subtype,
                "duration_ms": ev.get("duration_ms", 0),
                "input_tokens": usage.get("inputTokens", 0),
                "output_tokens": usage.get("outputTokens", 0),
            })]

        if t == "error":
            return [AgentEvent("error", {
                "message": ev.get("message", str(ev)),
            })]

        return [AgentEvent("unknown", {"raw": ev})]

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
                for parsed in self._parse_events(raw_ev):
                    if parsed.kind == "init":
                        cursor_sid = parsed.data.get("session_id", "")
                    elif parsed.kind == "text":
                        text_parts.append(parsed.data["text"])
                    elif parsed.kind == "tool_use":
                        tool_calls.append(parsed.data)
                    elif parsed.kind == "tool_result" and tool_calls:
                        tool_calls[-1]["result_preview"] = parsed.data.get(
                            "preview", "")
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
                for parsed in self._parse_events(raw_ev):
                    event_count += 1
                    if parsed.kind == "tool_use":
                        log.info(
                            "[iter_events] tool_use: %s(%s)",
                            parsed.data.get("name"),
                            parsed.data.get("summary", ""),
                        )
                    elif parsed.kind == "tool_result":
                        log.info(
                            "[iter_events] tool_result: %s (%d lines)",
                            parsed.data.get("preview", "")[:80],
                            parsed.data.get("line_count", 0),
                        )
                    elif parsed.kind == "error":
                        log.error("[iter_events] error event: %s", parsed.data)
                    elif parsed.kind == "done":
                        log.info(
                            "[iter_events] done: tokens_in=%s tokens_out=%s duration=%sms",
                            parsed.data.get("input_tokens"),
                            parsed.data.get("output_tokens"),
                            parsed.data.get("duration_ms"),
                        )
                    elif parsed.kind == "unknown":
                        log.debug("[iter_events] unknown: %s", parsed.data)
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
