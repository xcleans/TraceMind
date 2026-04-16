"""atrace-ai — AI analysis engine for TraceMind.

Provides CursorAgentRunner (subprocess lifecycle), prompt builders,
session management, and deep fallback analysis using local TraceAnalyzer.
"""

from atrace_ai.cursor_runner import CursorAgentRunner, AgentEvent, AgentResult
from atrace_ai.session_manager import SessionManager, ChatSession
from atrace_ai.prompt_builder import PromptBuilder

__all__ = [
    "CursorAgentRunner",
    "AgentEvent",
    "AgentResult",
    "SessionManager",
    "ChatSession",
    "PromptBuilder",
]
