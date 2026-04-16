"""AI chat endpoint powered by Cursor Agent CLI.

Thin FastAPI route layer over atrace-ai package:
  - CursorAgentRunner  → subprocess lifecycle
  - SessionManager     → session store
  - PromptBuilder      → prompt templates
  - FallbackAnalyzer   → local analysis when CLI unavailable
  - ReportFormatter    → Markdown report generation
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from atrace_service.engine import TraceAnalyzer, get_analyzer
from atrace_service.models import (
    AiChatRequest,
    AiChatResponse,
    AutoAnalyzeRequest,
    ErrorResponse,
)

def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "platform" / "_monorepo.py").is_file():
            return parent
        if (parent / "_monorepo.py").is_file():
            return parent.parent if parent.name == "platform" else parent
    return here.parents[5]


_root = _find_repo_root()
_module_dir = _root / "platform"
_monorepo_path = _module_dir / "_monorepo.py"
if _monorepo_path.is_file():
    if str(_module_dir) not in sys.path:
        sys.path.insert(0, str(_module_dir))
    import _monorepo; _monorepo.bootstrap()  # noqa: E702

from atrace_ai import CursorAgentRunner, PromptBuilder, SessionManager  # noqa: E402
from atrace_ai.fallback import FallbackAnalyzer, ReportFormatter  # noqa: E402

router = APIRouter(prefix="/ai", tags=["ai"])
log = logging.getLogger("atrace.service.ai")
#需要使用更目录使用配置
_runner = CursorAgentRunner(workspace_root=str(_root))
_sessions = SessionManager()

# Playbook registry (lazy init) — custom playbooks stored under workspace
_playbook_registry = None
_CUSTOM_PLAYBOOKS_DIR = _root / "platform" / "custom-playbooks"


def _get_registry():
    global _playbook_registry
    if _playbook_registry is None:
        try:
            from atrace_orchestrator.playbook import PlaybookRegistry
            _playbook_registry = PlaybookRegistry(custom_dir=_CUSTOM_PLAYBOOKS_DIR)
        except ImportError:
            _playbook_registry = None
    return _playbook_registry


def _require_or_reload(trace_path: str, analyzer: TraceAnalyzer) -> str:
    abs_path = str(Path(trace_path).resolve())
    if abs_path not in analyzer._sessions:
        if not Path(abs_path).is_file():
            raise HTTPException(status_code=404, detail=f"Trace not found: {trace_path}")
        try:
            analyzer.load(abs_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Cannot load: {exc}") from exc
    return abs_path


# ═══════════════════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/chat",
    response_model=AiChatResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Trace-aware AI chat via Cursor Agent CLI",
)
def ai_chat(
    body: AiChatRequest,
    session_id: str | None = None,
    new_session: bool = False,
    analyzer: TraceAnalyzer = Depends(get_analyzer),
) -> AiChatResponse:
    log.info("POST /ai/chat trace=%s question=%.80s session=%s new=%s", body.trace_path, body.question, session_id, new_session)
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="question is required")

    abs_path = _require_or_reload(body.trace_path, analyzer)

    if new_session:
        session = _sessions.new_session(abs_path)
    else:
        session = _sessions.get_or_create(abs_path, session_id)

    _sessions.append_message(session, "user", body.question, "user")

    prompt = PromptBuilder.chat(abs_path, body.question, body.process)

    if _runner.available:
        try:
            result = _runner.run(
                prompt,
                resume_id=session.cursor_session_id or None,
                trace_path_hint=abs_path,
            )
            if result.cursor_session_id:
                session.cursor_session_id = result.cursor_session_id

            tool_info = ""
            if result.tool_calls:
                tools_str = "\n".join(
                    f"  [{tc['name']}] {tc.get('summary', '')}" for tc in result.tool_calls
                )
                tool_info = f"\n\n---\n工具调用:\n{tools_str}"

            answer = result.text + tool_info
            _sessions.append_message(session, "assistant", answer, "cursor-agent")
            log.info("POST /ai/chat → cursor-agent session=%s len=%d", session.session_id, len(answer))
            return AiChatResponse(
                answer=answer,
                source="cursor-agent",
                session_id=session.session_id,
            )
        except Exception as exc:
            log.warning("cursor agent failed, falling back: %s", exc)

    fb = FallbackAnalyzer(analyzer)
    ctx = fb.chat_analysis(body.question, abs_path, body.process)
    answer = ReportFormatter.evidence_report(body.question, ctx)
    _sessions.append_message(session, "assistant", answer, "fallback")
    log.info("POST /ai/chat → fallback session=%s len=%d", session.session_id, len(answer))
    return AiChatResponse(
        answer=answer,
        source="fallback",
        session_id=session.session_id,
    )


@router.post(
    "/chat/stream",
    summary="Streaming AI chat via Cursor Agent CLI (SSE)",
)
def ai_chat_stream(
    body: AiChatRequest,
    session_id: str | None = None,
    new_session: bool = False,
    analyzer: TraceAnalyzer = Depends(get_analyzer),
):
    log.info("POST /ai/chat/stream trace=%s question=%.80s session=%s", body.trace_path, body.question, session_id)
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="question is required")

    abs_path = _require_or_reload(body.trace_path, analyzer)

    if new_session:
        session = _sessions.new_session(abs_path)
    else:
        session = _sessions.get_or_create(abs_path, session_id)

    _sessions.append_message(session, "user", body.question, "user")

    if not _runner.available:
        fb = FallbackAnalyzer(analyzer)
        ctx = fb.chat_analysis(body.question, abs_path, body.process)
        answer = ReportFormatter.evidence_report(body.question, ctx)
        _sessions.append_message(session, "assistant", answer, "fallback")

        def _fallback_sse():
            yield f"event: text\ndata: {json.dumps({'text': answer}, ensure_ascii=False)}\n\n"
            yield f"event: done\ndata: {json.dumps({'source': 'fallback', 'session_id': session.session_id})}\n\n"

        return StreamingResponse(_fallback_sse(), media_type="text/event-stream")

    prompt = PromptBuilder.chat(abs_path, body.question, body.process)

    def _stream_sse():
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        for ev in _runner.iter_events(
            prompt,
            resume_id=session.cursor_session_id or None,
            trace_path_hint=abs_path,
        ):
            if ev.kind == "init":
                sid = ev.data.get("session_id", "")
                if sid:
                    session.cursor_session_id = sid
                yield f"event: init\ndata: {json.dumps(ev.data, ensure_ascii=False)}\n\n"
            elif ev.kind == "text":
                text_parts.append(ev.data["text"])
                yield f"event: text\ndata: {json.dumps(ev.data, ensure_ascii=False)}\n\n"
            elif ev.kind == "tool_use":
                tool_calls.append(ev.data)
                yield f"event: tool_use\ndata: {json.dumps(ev.data, ensure_ascii=False)}\n\n"
            elif ev.kind == "tool_result":
                yield f"event: tool_result\ndata: {json.dumps(ev.data, ensure_ascii=False)}\n\n"
            elif ev.kind == "done":
                full_text = "".join(text_parts)
                _sessions.append_message(session, "assistant", full_text, "cursor-agent")
                yield f"event: done\ndata: {json.dumps({'source': 'cursor-agent', 'session_id': session.session_id, **ev.data}, ensure_ascii=False)}\n\n"
            elif ev.kind == "error":
                yield f"event: error\ndata: {json.dumps(ev.data, ensure_ascii=False)}\n\n"

    return StreamingResponse(_stream_sse(), media_type="text/event-stream")


@router.post(
    "/auto",
    response_model=AiChatResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="One-shot automatic comprehensive analysis via Cursor Agent",
)
def auto_analyze(
    body: AutoAnalyzeRequest,
    playbook: str | None = None,
    analyzer: TraceAnalyzer = Depends(get_analyzer),
) -> AiChatResponse:
    log.info("POST /ai/auto trace=%s process=%s playbook=%s", body.trace_path, body.process, playbook)
    abs_path = _require_or_reload(body.trace_path, analyzer)
    session = _sessions.new_session(abs_path)
    scene = playbook or "auto"
    _sessions.append_message(session, "system", f"开始AI性能分析 (scene={scene})…", "system")

    prompt = PromptBuilder.auto(
        abs_path, body.process, body.layer_name_hint,
        playbook_name=playbook,
    )
    _sessions.append_message(session, "user", f"AI性能分析 (playbook={scene})", "auto")

    if _runner.available:
        try:
            result = _runner.run(prompt, timeout=300, trace_path_hint=abs_path)
            if result.cursor_session_id:
                session.cursor_session_id = result.cursor_session_id
            _sessions.append_message(session, "assistant", result.text, "cursor-agent")
            log.info("POST /ai/auto → cursor-agent session=%s len=%d", session.session_id, len(result.text))
            return AiChatResponse(
                answer=result.text,
                source="cursor-agent",
                session_id=session.session_id,
            )
        except Exception as exc:
            log.warning("cursor agent auto-analyze failed: %s", exc)

    fb = FallbackAnalyzer(analyzer)
    ctx = fb.auto_analysis(abs_path, body.process, body.layer_name_hint)
    report = ReportFormatter.auto_report(ctx)
    _sessions.append_message(session, "assistant", report, "fallback")
    log.info("POST /ai/auto → fallback session=%s len=%d", session.session_id, len(report))
    return AiChatResponse(answer=report, source="fallback", session_id=session.session_id)


@router.post(
    "/auto/stream",
    summary="Streaming auto-analysis via Cursor Agent CLI (SSE)",
)
def auto_analyze_stream(
    body: AutoAnalyzeRequest,
    playbook: str | None = None,
    analyzer: TraceAnalyzer = Depends(get_analyzer),
):
    log.info("POST /ai/auto/stream trace=%s process=%s playbook=%s", body.trace_path, body.process, playbook)
    abs_path = _require_or_reload(body.trace_path, analyzer)
    session = _sessions.new_session(abs_path)
    scene = playbook or "auto"
    _sessions.append_message(session, "system", f"开始AI性能分析 (scene={scene})…", "system")
    _sessions.append_message(session, "user", f"AI性能分析 (playbook={scene})", "auto")

    prompt = PromptBuilder.auto(
        abs_path, body.process, body.layer_name_hint,
        playbook_name=playbook,
    )

    if not _runner.available:
        fb = FallbackAnalyzer(analyzer)
        ctx = fb.auto_analysis(abs_path, body.process, body.layer_name_hint)
        report = ReportFormatter.auto_report(ctx)
        _sessions.append_message(session, "assistant", report, "fallback")

        def _fb():
            yield f"event: text\ndata: {json.dumps({'text': report}, ensure_ascii=False)}\n\n"
            yield f"event: done\ndata: {json.dumps({'source': 'fallback', 'session_id': session.session_id})}\n\n"

        return StreamingResponse(_fb(), media_type="text/event-stream")

    def _stream():
        text_parts: list[str] = []
        for ev in _runner.iter_events(prompt, trace_path_hint=abs_path):
            if ev.kind == "init":
                sid = ev.data.get("session_id", "")
                if sid:
                    session.cursor_session_id = sid
                yield f"event: init\ndata: {json.dumps(ev.data, ensure_ascii=False)}\n\n"
            elif ev.kind == "text":
                text_parts.append(ev.data["text"])
                yield f"event: text\ndata: {json.dumps(ev.data, ensure_ascii=False)}\n\n"
            elif ev.kind == "tool_use":
                yield f"event: tool_use\ndata: {json.dumps(ev.data, ensure_ascii=False)}\n\n"
            elif ev.kind == "tool_result":
                yield f"event: tool_result\ndata: {json.dumps(ev.data, ensure_ascii=False)}\n\n"
            elif ev.kind == "done":
                _sessions.append_message(session, "assistant", "".join(text_parts), "cursor-agent")
                yield f"event: done\ndata: {json.dumps({'source': 'cursor-agent', 'session_id': session.session_id, **ev.data}, ensure_ascii=False)}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


# ── Playbook endpoints ────────────────────────────────────────────────────────


@router.get("/playbooks", summary="List available analysis playbooks (scenes)")
def list_playbooks() -> dict[str, Any]:
    log.info("GET /ai/playbooks")
    reg = _get_registry()
    if reg is None:
        log.warning("GET /ai/playbooks → orchestrator not available")
        return {"playbooks": [], "note": "atrace-orchestrator not available"}
    names = reg.list()
    result = []
    for name in names:
        try:
            pb = reg.load(name)
            result.append({
                "name": pb.name,
                "scenario": pb.scenario,
                "description": pb.description.strip().split("\n")[0],
                "capture": pb.capture.model_dump(),
                "builtin": reg.is_builtin(name),
                "custom": reg.is_custom(name),
            })
        except Exception:
            result.append({"name": name, "scenario": "", "description": "",
                           "capture": {}, "builtin": False, "custom": False})
    log.info("GET /ai/playbooks → %d playbook(s)", len(result))
    return {"playbooks": result}


@router.get("/playbooks/{name}", summary="Get full playbook detail")
def get_playbook(name: str) -> dict[str, Any]:
    log.info("GET /ai/playbooks/%s", name)
    reg = _get_registry()
    if reg is None:
        raise HTTPException(status_code=400, detail="atrace-orchestrator not available")
    try:
        pb = reg.load(name)
        return {
            **pb.model_dump(),
            "builtin": reg.is_builtin(name),
            "custom": reg.is_custom(name),
        }
    except FileNotFoundError:
        log.warning("GET /ai/playbooks/%s → not found", name)
        raise HTTPException(status_code=404, detail=f"Playbook not found: {name}")


@router.get("/playbooks/{name}/yaml", summary="Get raw YAML of a playbook (for editing)")
def get_playbook_yaml(name: str) -> dict[str, Any]:
    log.info("GET /ai/playbooks/%s/yaml", name)
    reg = _get_registry()
    if reg is None:
        raise HTTPException(status_code=400, detail="atrace-orchestrator not available")
    try:
        return {
            "name": name,
            "yaml": reg.raw_yaml(name),
            "builtin": reg.is_builtin(name),
            "custom": reg.is_custom(name),
        }
    except FileNotFoundError:
        log.warning("GET /ai/playbooks/%s/yaml → not found", name)
        raise HTTPException(status_code=404, detail=f"Playbook not found: {name}")


@router.put("/playbooks/{name}", summary="Create or update a custom playbook")
def save_playbook(name: str, body: dict[str, Any]) -> dict[str, Any]:
    log.info("PUT /ai/playbooks/%s", name)
    reg = _get_registry()
    if reg is None:
        raise HTTPException(status_code=400, detail="atrace-orchestrator not available")
    yaml_content = body.get("yaml", "")
    if not yaml_content.strip():
        raise HTTPException(status_code=400, detail="'yaml' field is required")
    try:
        path = reg.save(name, yaml_content)
        log.info("PUT /ai/playbooks/%s → saved to %s", name, path)
        return {"status": "saved", "name": name, "path": str(path)}
    except Exception as exc:
        log.error("PUT /ai/playbooks/%s failed: %s", name, exc)
        raise HTTPException(status_code=400, detail=f"Invalid playbook YAML: {exc}")


@router.delete("/playbooks/{name}", summary="Delete a custom playbook")
def delete_playbook(name: str) -> dict[str, Any]:
    log.info("DELETE /ai/playbooks/%s", name)
    reg = _get_registry()
    if reg is None:
        raise HTTPException(status_code=400, detail="atrace-orchestrator not available")
    if reg.is_builtin(name) and not reg.is_custom(name):
        log.warning("DELETE /ai/playbooks/%s → refused (built-in)", name)
        raise HTTPException(status_code=403, detail="Cannot delete built-in playbook")
    if reg.delete(name):
        log.info("DELETE /ai/playbooks/%s → deleted", name)
        return {"status": "deleted", "name": name}
    log.warning("DELETE /ai/playbooks/%s → not found", name)
    raise HTTPException(status_code=404, detail=f"Custom playbook not found: {name}")


@router.post(
    "/playbooks/{name}/analyze",
    response_model=AiChatResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Run AI analysis guided by a specific playbook (scene)",
)
def playbook_analyze(
    name: str,
    body: AutoAnalyzeRequest,
    analyzer: TraceAnalyzer = Depends(get_analyzer),
) -> AiChatResponse:
    """Load a playbook, generate a rich context prompt, and run Cursor Agent."""
    log.info("POST /ai/playbooks/%s/analyze trace=%s process=%s", name, body.trace_path, body.process)
    reg = _get_registry()
    if reg is None:
        raise HTTPException(status_code=400, detail="atrace-orchestrator not available")
    try:
        pb = reg.load(name)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Playbook not found: {name}. Available: {reg.list()}",
        )

    abs_path = _require_or_reload(body.trace_path, analyzer)
    session = _sessions.new_session(abs_path)
    _sessions.append_message(session, "system", f"Playbook: {name}", "system")

    prompt = PromptBuilder.from_playbook(pb, abs_path, body.process)
    _sessions.append_message(session, "user", f"Playbook 分析: {name}", "auto")

    if _runner.available:
        try:
            result = _runner.run(prompt, timeout=300, trace_path_hint=abs_path)
            if result.cursor_session_id:
                session.cursor_session_id = result.cursor_session_id
            _sessions.append_message(session, "assistant", result.text, "cursor-agent")
            log.info("POST /ai/playbooks/%s/analyze → cursor-agent len=%d", name, len(result.text))
            return AiChatResponse(
                answer=result.text,
                source="cursor-agent",
                session_id=session.session_id,
            )
        except Exception as exc:
            log.warning("cursor agent playbook-analyze failed: %s", exc)

    fb = FallbackAnalyzer(analyzer)
    ctx = fb.auto_analysis(abs_path, body.process, body.layer_name_hint)
    report = ReportFormatter.auto_report(ctx)
    _sessions.append_message(session, "assistant", report, "fallback")
    log.info("POST /ai/playbooks/%s/analyze → fallback len=%d", name, len(report))
    return AiChatResponse(answer=report, source="fallback", session_id=session.session_id)


@router.post(
    "/playbooks/{name}/analyze/stream",
    summary="Streaming playbook-driven analysis (SSE)",
)
def playbook_analyze_stream(
    name: str,
    body: AutoAnalyzeRequest,
    analyzer: TraceAnalyzer = Depends(get_analyzer),
):
    log.info("POST /ai/playbooks/%s/analyze/stream trace=%s process=%s", name, body.trace_path, body.process)
    reg = _get_registry()
    if reg is None:
        raise HTTPException(status_code=400, detail="atrace-orchestrator not available")
    try:
        pb = reg.load(name)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Playbook not found: {name}. Available: {reg.list()}",
        )

    abs_path = _require_or_reload(body.trace_path, analyzer)
    session = _sessions.new_session(abs_path)
    _sessions.append_message(session, "system", f"Playbook: {name}", "system")
    _sessions.append_message(session, "user", f"Playbook 分析: {name}", "auto")

    prompt = PromptBuilder.from_playbook(pb, abs_path, body.process)
    log.info("[playbook-stream] prompt length=%d chars, runner available=%s", len(prompt), _runner.available)
    log.info("[playbook-stream] mcp config: %s", _runner.check_mcp_config())

    if not _runner.available:
        log.warning("[playbook-stream] cursor CLI not available, using fallback")
        fb = FallbackAnalyzer(analyzer)
        ctx = fb.auto_analysis(abs_path, body.process, body.layer_name_hint)
        report = ReportFormatter.auto_report(ctx)
        _sessions.append_message(session, "assistant", report, "fallback")

        def _fb():
            yield f"event: text\ndata: {json.dumps({'text': report}, ensure_ascii=False)}\n\n"
            yield f"event: done\ndata: {json.dumps({'source': 'fallback', 'session_id': session.session_id})}\n\n"

        return StreamingResponse(_fb(), media_type="text/event-stream")

    log.info("[playbook-stream] starting cursor agent stream for playbook=%s trace=%s process=%s", name, abs_path, body.process)

    def _stream():
        text_parts: list[str] = []
        event_count = 0
        for ev in _runner.iter_events(prompt, trace_path_hint=abs_path):
            event_count += 1
            if ev.kind == "init":
                sid = ev.data.get("session_id", "")
                if sid:
                    session.cursor_session_id = sid
                log.info("[playbook-stream] init: session=%s", sid)
                yield f"event: init\ndata: {json.dumps(ev.data, ensure_ascii=False)}\n\n"
            elif ev.kind == "text":
                text_parts.append(ev.data["text"])
                yield f"event: text\ndata: {json.dumps(ev.data, ensure_ascii=False)}\n\n"
            elif ev.kind == "tool_use":
                log.info("[playbook-stream] tool_use: %s(%s)", ev.data.get("name"), ev.data.get("summary", ""))
                yield f"event: tool_use\ndata: {json.dumps(ev.data, ensure_ascii=False)}\n\n"
            elif ev.kind == "tool_result":
                log.info("[playbook-stream] tool_result: %s", ev.data.get("preview", "")[:80])
                yield f"event: tool_result\ndata: {json.dumps(ev.data, ensure_ascii=False)}\n\n"
            elif ev.kind == "error":
                log.error("[playbook-stream] error: %s", ev.data)
                yield f"event: error\ndata: {json.dumps(ev.data, ensure_ascii=False)}\n\n"
            elif ev.kind == "done":
                log.info("[playbook-stream] done: %d events, tokens=%s", event_count, ev.data)
                _sessions.append_message(session, "assistant", "".join(text_parts), "cursor-agent")
                yield f"event: done\ndata: {json.dumps({'source': 'cursor-agent', 'session_id': session.session_id, **ev.data}, ensure_ascii=False)}\n\n"
        if event_count == 0:
            log.warning("[playbook-stream] no events received from cursor agent!")

    return StreamingResponse(_stream(), media_type="text/event-stream")


# ── Session management endpoints ─────────────────────────────────────────────


@router.get("/sessions", summary="List all AI chat sessions")
def list_sessions() -> dict[str, list[dict[str, Any]]]:
    log.info("GET /ai/sessions")
    return {"sessions": _sessions.list_all()}


@router.get("/sessions/{trace_id:path}", summary="List sessions for a specific trace")
def sessions_for_trace(trace_id: str) -> dict[str, Any]:
    import urllib.parse
    trace_path = str(Path(urllib.parse.unquote(trace_id)).resolve())
    log.info("GET /ai/sessions/%s", trace_id)
    return {
        "trace_path": trace_path,
        "sessions": _sessions.sessions_for_trace(trace_path),
    }


@router.get("/history/{session_id}", summary="Get full chat history for a session")
def get_history(session_id: str) -> dict[str, Any]:
    log.info("GET /ai/history/%s", session_id)
    s = _sessions.get(session_id)
    if not s:
        log.warning("GET /ai/history/%s → not found", session_id)
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return {
        "session_id": s.session_id,
        "trace_path": s.trace_path,
        "messages": s.messages,
        "cursor_session_id": s.cursor_session_id,
    }


@router.get("/status", summary="AI engine status — cursor CLI + MCP availability")
def ai_status() -> dict[str, Any]:
    log.info("GET /ai/status")
    status = _runner.full_status()
    if not status["ready"]:
        status["how_to_enable_mcp"] = (
            "确保以下条件满足:\n"
            "1. 安装 Cursor CLI (cursor --version)\n"
            "2. 在 TraceMind/.cursor/mcp.json 配置 atrace MCP server\n"
            "3. 在 TraceMind/.cursor/cli.json 预批准 Mcp(atrace, *) 权限\n"
            "4. 从 TraceMind 仓库根目录启动 atrace-service"
        )
    return status
