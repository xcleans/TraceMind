"""Monorepo path helpers for ``atrace-capture`` (Phase 6 — L1 placement)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache
def monorepo_root() -> Path:
    """Return TraceMind repository root (parent of ``atrace-capture``)."""
    # atrace-capture/atrace_capture/repo_paths.py → parents[2] == repo root
    return Path(__file__).resolve().parents[2]
