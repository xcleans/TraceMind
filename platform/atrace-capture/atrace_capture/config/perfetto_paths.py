"""Disk path to Perfetto text configs (``.txtpb``) shipped inside ``atrace-capture``."""

from __future__ import annotations

from pathlib import Path


def bundled_perfetto_configs_dir() -> Path:
    """Directory containing scenario ``*.txtpb`` and ``README.md`` (package data)."""
    return Path(__file__).resolve().parent / "perfetto"
