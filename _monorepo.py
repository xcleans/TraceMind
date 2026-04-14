"""Monorepo path bootstrap — single source of truth for inter-package imports.

Call ``bootstrap()`` once at process startup to ensure all TraceMind
sibling packages are importable.  Replaces the scattered ``sys.path.insert``
calls that previously appeared in every consumer module.

Usage (top of any entry-point or facade):
    import _monorepo; _monorepo.bootstrap()

This is a **development convenience**.  In production installs (``pip install -e``
or ``uv pip install -e``), packages declare proper inter-package dependencies
in their ``pyproject.toml`` and this module is never loaded.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

_PACKAGES = [
    "atrace-analyzer",
    "atrace-device",
    "atrace-capture",
    "atrace-provision",
    "atrace-ai",
    "atrace-orchestrator",
    "atrace-mcp",
    "atrace-service",
]

_bootstrapped = False


def bootstrap() -> None:
    """Add all monorepo package directories to ``sys.path`` (idempotent)."""
    global _bootstrapped
    if _bootstrapped:
        return
    for pkg_name in _PACKAGES:
        pkg_dir = REPO_ROOT / pkg_name
        if pkg_dir.is_dir() and str(pkg_dir) not in sys.path:
            sys.path.insert(0, str(pkg_dir))
    _bootstrapped = True


# ── Perfetto config resolution ───────────────────────────────────────────────

_CONFIG_SEARCH_DIRS = [
    "docs/configs",
    "atrace-capture/atrace_capture/config/perfetto",
    "atrace-mcp/mcp_bundled_resources/configs",
]


def resolve_perfetto_config(raw: str | None) -> str | None:
    """Resolve a Perfetto config reference to an absolute path.

    Accepts any of:
      - ``None`` / empty  → ``None`` (use atrace-tool's built-in default)
      - absolute path      → returned as-is after existence check
      - relative path      → resolved against ``REPO_ROOT``
      - short name         → searched in known config directories
        (e.g. ``"scroll"`` or ``"scroll.txtpb"``)

    Returns the absolute path string, or ``None`` if not found.
    """
    if not raw or not raw.strip():
        return None

    value = raw.strip()

    p = Path(value)
    if p.is_absolute():
        return str(p) if p.is_file() else None

    # relative path (contains /) → resolve against repo root
    if "/" in value:
        candidate = REPO_ROOT / value
        if candidate.is_file():
            return str(candidate.resolve())
        # also try with .txtpb suffix
        if not value.endswith(".txtpb"):
            candidate = REPO_ROOT / f"{value}.txtpb"
            if candidate.is_file():
                return str(candidate.resolve())
        return None

    # short name → search in known directories
    names = [value] if value.endswith(".txtpb") else [f"{value}.txtpb", value]
    for rel_dir in _CONFIG_SEARCH_DIRS:
        config_dir = REPO_ROOT / rel_dir
        if not config_dir.is_dir():
            continue
        for name in names:
            candidate = config_dir / name
            if candidate.is_file():
                return str(candidate.resolve())
    return None
