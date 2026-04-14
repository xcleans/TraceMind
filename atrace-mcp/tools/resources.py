"""MCP Resources — docs/configs Perfetto .txtpb + SQL reference."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _mcp_bundled_resources_root() -> Path | None:
    beside = Path(__file__).resolve().parents[1] / "mcp_bundled_resources"
    if beside.is_dir():
        return beside
    pip_layout = Path(sys.prefix) / "atrace_mcp" / "mcp_bundled_resources"
    if pip_layout.is_dir():
        return pip_layout
    return None


def _docs_configs_dir() -> Path | None:
    override = os.environ.get("ATRACE_DOCS_CONFIGS", "").strip()
    if override:
        p = Path(override).expanduser().resolve()
        if p.is_dir():
            return p
    bundled = _mcp_bundled_resources_root()
    if bundled is not None:
        cfg = bundled / "configs"
        if cfg.is_dir():
            return cfg
    base = Path(__file__).resolve().parents[1].parent / "docs" / "configs"
    if base.is_dir():
        return base
    return None


def _read_docs_config_file(filename: str) -> str:
    root = _docs_configs_dir()
    if root is None:
        return f"# docs/configs directory not found\n\nMonorepo default: `{Path(__file__).resolve().parents[1].parent / 'docs' / 'configs'}`\n"
    path = root / filename
    if not path.is_file():
        return f"# File not found: `{filename}`\n\nSearched in `{root}`.\n"
    return path.read_text(encoding="utf-8", errors="replace")


def _perfetto_sql_reference_path() -> Path | None:
    override = os.environ.get("ATRACE_PERFETTO_SQL_REFERENCE", "").strip()
    if override:
        p = Path(override).expanduser().resolve()
        if p.is_file():
            return p
    bundled = _mcp_bundled_resources_root()
    if bundled is not None:
        p = bundled / "perfetto-trace-processor-reference.md"
        if p.is_file():
            return p
    default = Path(__file__).resolve().parents[1].parent / ".conversation" / "perfetto-trace-processor-reference.md"
    if default.is_file():
        return default
    return None


def _extract_perfetto_sql_reference_for_mcp(full_text: str) -> str:
    header = "# Perfetto SQL reference (MCP excerpt for execute_sql)\n\n"
    chunks: list[str] = []
    spans = (
        ("## 1. Available SQL Tables", "## 2. Python API Integration"),
        ("## 3. Common SQL Queries for Android Performance", "## 4. perfetto-mcp Architecture"),
        ("## Appendix: Quick Reference Cheat Sheet", None),
    )
    for start_marker, end_marker in spans:
        start = full_text.find(start_marker)
        if start < 0:
            continue
        if end_marker:
            end = full_text.find(end_marker, start + 1)
            block = full_text[start:end] if end >= 0 else full_text[start:]
        else:
            block = full_text[start:]
        block = block.strip()
        if block:
            chunks.append(block)
    if chunks:
        return header + "\n\n---\n\n".join(chunks)
    return header + full_text.strip()


def _read_perfetto_sql_reference_mcp() -> str:
    path = _perfetto_sql_reference_path()
    if path is None:
        return "# Perfetto SQL reference file not found\n\nSet ATRACE_PERFETTO_SQL_REFERENCE or use TraceMind repo layout.\n"
    full = path.read_text(encoding="utf-8", errors="replace")
    return _extract_perfetto_sql_reference_for_mcp(full)


def register_resources(mcp) -> None:

    @mcp.resource("atrace://configs/index", title="Perfetto configs index", mime_type="text/markdown")
    def perfetto_configs_index() -> str:
        root = _docs_configs_dir()
        root_line = f"Resolved directory: `{root}`\n\n" if root else "Directory not resolved.\n\n"
        return (
            root_line
            + "# Perfetto scenario configs (MCP resources)\n\n"
            + "| URI | File | Use |\n|-----|------|-----|\n"
            + "| `atrace://configs/startup` | startup.txtpb | Cold/warm launch |\n"
            + "| `atrace://configs/scroll` | scroll.txtpb | Scroll / jank |\n"
            + "| `atrace://configs/memory` | memory.txtpb | Memory / GC |\n"
            + "| `atrace://configs/binder` | binder.txtpb | Binder / IPC |\n"
            + "| `atrace://configs/animation` | animation.txtpb | Animations |\n"
            + "| `atrace://configs/full-template` | config.txtpb | Full template |\n"
        )

    @mcp.resource("atrace://configs/readme", title="docs/configs README", mime_type="text/markdown")
    def perfetto_configs_readme() -> str:
        return _read_docs_config_file("README.md")

    @mcp.resource("atrace://configs/startup", title="Perfetto config: startup.txtpb")
    def perfetto_config_startup() -> str:
        return _read_docs_config_file("startup.txtpb")

    @mcp.resource("atrace://configs/scroll", title="Perfetto config: scroll.txtpb")
    def perfetto_config_scroll() -> str:
        return _read_docs_config_file("scroll.txtpb")

    @mcp.resource("atrace://configs/memory", title="Perfetto config: memory.txtpb")
    def perfetto_config_memory() -> str:
        return _read_docs_config_file("memory.txtpb")

    @mcp.resource("atrace://configs/binder", title="Perfetto config: binder.txtpb")
    def perfetto_config_binder() -> str:
        return _read_docs_config_file("binder.txtpb")

    @mcp.resource("atrace://configs/animation", title="Perfetto config: animation.txtpb")
    def perfetto_config_animation() -> str:
        return _read_docs_config_file("animation.txtpb")

    @mcp.resource("atrace://configs/full-template", title="Perfetto config: config.txtpb (full template)")
    def perfetto_config_full_template() -> str:
        return _read_docs_config_file("config.txtpb")

    @mcp.resource("atrace://perfetto-sql-reference", title="Perfetto SQL reference", mime_type="text/markdown")
    def perfetto_sql_reference() -> str:
        return _read_perfetto_sql_reference_mcp()

    @mcp.resource("atrace://sql-patterns")
    def sql_patterns() -> str:
        """Common PerfettoSQL query patterns for Android performance analysis."""
        return """
# PerfettoSQL Quick Reference for Android Performance

## Find slow functions on main thread
SELECT s.name, s.dur/1e6 AS ms, s.id
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%com.example%' AND t.is_main_thread = 1
ORDER BY s.dur DESC LIMIT 20

## Thread state analysis
SELECT state, SUM(dur)/1e6 AS total_ms, COUNT(*) AS count
FROM thread_state ts
JOIN thread t ON ts.utid = t.utid
WHERE t.name = 'main' AND ts.dur > 0
GROUP BY state ORDER BY total_ms DESC

## Find GC pauses
SELECT s.name, s.dur/1e6 AS ms, s.ts
FROM slice s WHERE s.name LIKE '%GC%' OR s.name LIKE 'concurrent%'
ORDER BY s.dur DESC LIMIT 20

## Binder transactions
SELECT s.name, s.dur/1e6 AS ms, t.name AS thread
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
WHERE s.name LIKE 'binder%' ORDER BY s.dur DESC LIMIT 20

## Lock contention
SELECT s.name, s.dur/1e6 AS ms, t.name AS thread
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
WHERE s.name LIKE '%Lock%' OR s.name LIKE '%Monitor%' OR s.name LIKE '%contention%'
ORDER BY s.dur DESC LIMIT 20

## IO on main thread
SELECT s.name, s.dur/1e6 AS ms
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
WHERE t.is_main_thread = 1
  AND (s.name LIKE '%read%' OR s.name LIKE '%write%' OR s.name LIKE '%open%' OR s.name LIKE '%IO%')
ORDER BY s.dur DESC LIMIT 20

## heapprofd: top retained allocations
SELECT HEX(callsite_id) AS callsite_id, SUM(size)/1024.0 AS retained_kb, SUM(count) AS alloc_count
FROM heap_profile_allocation WHERE size > 0
GROUP BY callsite_id ORDER BY retained_kb DESC LIMIT 20
"""
