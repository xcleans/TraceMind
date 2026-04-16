"""Paths to vendored resources shipped inside ``atrace-provision``."""

from __future__ import annotations

import sys
from pathlib import Path


def bundled_simpleperf_root() -> Path | None:
    """Return the root of the vendored AOSP simpleperf script tree, or None if absent.

    Expected layout: ``bundled_simpleperf/scripts/app_profiler.py`` (next to this file's
    package directory).
    """
    root = Path(__file__).resolve().parent / "bundled_simpleperf"
    if (root / "scripts" / "app_profiler.py").is_file():
        return root
    return None


def bundled_atrace_tool_jar() -> Path | None:
    """Return path to the vendored ``atrace-tool`` fat JAR, or None if absent."""
    jar = Path(__file__).resolve().parent / "bundled_bin" / "atrace-tool.jar"
    return jar if jar.is_file() else None


def record_android_trace_script_path() -> Path | None:
    """Path to the vendored ``record_android_trace`` shell script for this host OS, or None."""
    name = "record_android_trace_win" if sys.platform == "win32" else "record_android_trace"
    script = Path(__file__).resolve().parent / "bundled_record_android_trace" / name
    return script if script.is_file() else None
