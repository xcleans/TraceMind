"""Monorepo path helpers for ``atrace-capture`` (Phase 6 — L1 placement)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache
def monorepo_root() -> Path:
    """Return TraceMind repository root by walking up to monorepo marker."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "platform" / "_monorepo.py").is_file():
            return parent
        if (parent / "_monorepo.py").is_file():
            return parent.parent if parent.name == "platform" else parent
    # Fallback for editable installs without repo root marker.
    return here.parents[3]
