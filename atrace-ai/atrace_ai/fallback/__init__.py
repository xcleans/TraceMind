"""Fallback analysis — local TraceAnalyzer-based engine.

When cursor CLI is unavailable, this module provides equivalent depth:
  - Deep drill (slice_children + call_chain)
  - Keyword-based scope selection
  - Structured Markdown report generation
"""

from atrace_ai.fallback.analyzer import FallbackAnalyzer
from atrace_ai.fallback.formatter import ReportFormatter

__all__ = ["FallbackAnalyzer", "ReportFormatter"]
