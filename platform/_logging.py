"""TraceMind unified logging — all components log to ``<repo>/log/``.

Usage:
    from _logging import get_logger
    log = get_logger("atrace.service")
    log.info("server started on port %d", port)

Log files:
    log/atrace-service.log        — HTTP service
    log/atrace-mcp.log            — MCP server (general)
    log/atrace-mcp-pipeline.log   — MCP tool enter/exit + launch (full handler chain)
    log/atrace-ai.log             — AI / Cursor agent runner
    log/atrace-all.log            — combined (all components)

Configuration via environment:
    ATRACE_LOG_LEVEL   — root level for atrace.* loggers (default: DEBUG)
    ATRACE_LOG_DIR     — override log directory (default: <repo>/log/)
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

_MAX_BYTES = 10 * 1024 * 1024  # 10 MB per file
_BACKUP_COUNT = 3

_initialized = False


def _log_dir() -> Path:
    override = os.environ.get("ATRACE_LOG_DIR", "").strip()
    if override:
        d = Path(override)
    else:
        d = _REPO_ROOT / "log"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _init_root() -> None:
    """One-time setup: configure the ``atrace`` root logger with file + stderr."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    level_name = os.environ.get("ATRACE_LOG_LEVEL", "DEBUG").strip().upper()
    level = getattr(logging, level_name, logging.DEBUG)

    root = logging.getLogger("atrace")
    root.setLevel(level)
    root.propagate = False

    if root.handlers:
        return

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.INFO)
    stderr_handler.setFormatter(fmt)
    root.addHandler(stderr_handler)

    log_d = _log_dir()
    all_handler = RotatingFileHandler(
        str(log_d / "atrace-all.log"),
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    all_handler.setLevel(logging.DEBUG)
    all_handler.setFormatter(fmt)
    root.addHandler(all_handler)


def get_logger(name: str, log_file: str | None = None) -> logging.Logger:
    """Return a logger under the ``atrace.*`` hierarchy.

    Args:
        name:     Logger name (e.g. ``atrace.mcp``, ``atrace.service``).
        log_file: Optional dedicated log file name (e.g. ``atrace-mcp.log``).
                  Written to ``<repo>/log/<log_file>`` with rotation.
    """
    _init_root()

    logger = logging.getLogger(name)

    if log_file and not any(
        isinstance(h, RotatingFileHandler)
        and Path(h.baseFilename).name == log_file
        for h in logger.handlers
    ):
        fmt = logging.Formatter(
            "%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        fh = RotatingFileHandler(
            str(_log_dir() / log_file),
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger
