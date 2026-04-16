"""atrace-orchestrator — Playbook layer for TraceMind.

Provides AI-driven scene briefings (Playbooks) that describe:
  - scenario context, capture config, available tools
  - analysis strategy hints, SQL patterns, drill-down directions
  - expected report structure and threshold references

The AI receives a Playbook as prompt context and decides how to
explore, drill deeper, and generate the report on its own.
"""

from atrace_orchestrator.playbook import Playbook, PlaybookRegistry

__all__ = [
    "Playbook",
    "PlaybookRegistry",
]
