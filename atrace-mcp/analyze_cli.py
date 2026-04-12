#!/usr/bin/env python3
"""Headless Perfetto trace analysis — same engine as MCP, no Cursor/MCP required.

Usage (after `pip install` / `uv sync` in atrace-mcp):
  atrace-analyze overview /path/to/file.perfetto
  atrace-analyze scroll /path/to/file.perfetto --process com.example.app
  atrace-analyze sql /path/to/file.perfetto --sql "SELECT 1"

Or from repo:
  cd atrace-mcp && uv run python analyze_cli.py overview /path/to/trace.perfetto
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from trace_analyzer import TraceAnalyzer


def _emit(data: Any, *, pretty: bool, output: Path | None) -> None:
    text = json.dumps(data, indent=2 if pretty else None, default=str)
    if output:
        output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def _require_process(name: str | None, cmd: str) -> str:
    if not name or not name.strip():
        print(
            f"error: --process <package> is required for `{cmd}` "
            "(or use a trace where a single app is obvious and pass explicitly).",
            file=sys.stderr,
        )
        sys.exit(2)
    return name.strip()


def cmd_overview(analyzer: TraceAnalyzer, trace: str, pretty: bool, output: Path | None) -> None:
    analyzer.load(trace)
    data = analyzer.overview(trace)
    _emit(data, pretty=pretty, output=output)


def cmd_startup(
    analyzer: TraceAnalyzer, trace: str, process: str, pretty: bool, output: Path | None
) -> None:
    analyzer.load(trace, process_name=process)
    data = analyzer.analyze_startup(trace, process)
    _emit(data, pretty=pretty, output=output)


def cmd_jank(
    analyzer: TraceAnalyzer, trace: str, process: str, pretty: bool, output: Path | None
) -> None:
    analyzer.load(trace, process_name=process)
    data = analyzer.analyze_jank(trace, process)
    _emit(data, pretty=pretty, output=output)


def cmd_scroll(
    analyzer: TraceAnalyzer,
    trace: str,
    process: str,
    layer_hint: str | None,
    pretty: bool,
    output: Path | None,
) -> None:
    analyzer.load(trace, process_name=process)
    data = analyzer.scroll_performance_metrics(trace, process, layer_hint)
    _emit(data, pretty=pretty, output=output)


def cmd_sql(
    analyzer: TraceAnalyzer,
    trace: str,
    sql: str,
    pretty: bool,
    output: Path | None,
) -> None:
    analyzer.load(trace)
    rows = analyzer.query(trace, sql)
    _emit(rows, pretty=pretty, output=output)


def cmd_top_slices(
    analyzer: TraceAnalyzer,
    trace: str,
    process: str | None,
    thread: str | None,
    name_pattern: str | None,
    min_dur_ms: float,
    limit: int,
    main_thread_only: bool,
    pretty: bool,
    output: Path | None,
) -> None:
    analyzer.load(trace, process_name=process)
    rows = analyzer.top_slices(
        trace,
        process=process,
        thread=thread,
        name_pattern=name_pattern,
        min_dur_ms=min_dur_ms,
        limit=limit,
        main_thread_only=main_thread_only,
    )
    _emit(rows, pretty=pretty, output=output)


def cmd_bundle(
    analyzer: TraceAnalyzer,
    trace: str,
    process: str,
    pretty: bool,
    output: Path | None,
) -> None:
    """Run overview + jank + scroll in one JSON object (CI / snapshots)."""
    analyzer.load(trace, process_name=process)
    bundle = {
        "trace_path": str(Path(trace).resolve()),
        "process": process,
        "overview": analyzer.overview(trace),
        "jank": analyzer.analyze_jank(trace, process),
        "scroll": analyzer.scroll_performance_metrics(trace, process, None),
    }
    _emit(bundle, pretty=pretty, output=output)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "trace",
        help="Path to .perfetto / .pb trace file",
    )
    common.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Write JSON to this file instead of stdout",
    )
    common.add_argument(
        "--compact",
        action="store_true",
        help="Single-line JSON (default is indented)",
    )

    parser = argparse.ArgumentParser(
        description="Analyze Perfetto traces using the same TraceAnalyzer as atrace-mcp (no MCP).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("overview", parents=[common], help="Duration, process list, slice scale")
    p.set_defaults(_handler="overview")

    p = sub.add_parser("startup", parents=[common], help="Cold start style: main-thread tops + blocking")
    p.add_argument("--process", "-p", required=True, help="App package name, e.g. com.example.app")
    p.set_defaults(_handler="startup")

    p = sub.add_parser("jank", parents=[common], help="Quick jank: long Choreographer / main-thread slices")
    p.add_argument("--process", "-p", required=True, help="App package name")
    p.set_defaults(_handler="jank")

    p = sub.add_parser("scroll", parents=[common], help="Scroll/frame quality (FrameTimeline + verdict)")
    p.add_argument("--process", "-p", required=True, help="App package name")
    p.add_argument(
        "--layer-hint",
        default=None,
        help="Substring for actual_frame_timeline_slice.layer_name (auto-detected if omitted)",
    )
    p.set_defaults(_handler="scroll")

    p = sub.add_parser("sql", parents=[common], help="Run arbitrary PerfettoSQL")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--sql", "-e", help="SQL string")
    g.add_argument("--sql-file", type=Path, help="Read SQL from file")
    p.set_defaults(_handler="sql")

    p = sub.add_parser("top-slices", parents=[common], help="Largest slices (filters optional)")
    p.add_argument("--process", "-p", default=None, help="Filter process name substring")
    p.add_argument("--thread", "-t", default=None, help="Filter thread name substring")
    p.add_argument("--name-pattern", "-n", default=None, help="Filter slice name substring")
    p.add_argument("--min-dur-ms", type=float, default=0.0)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--main-thread-only", action="store_true")
    p.set_defaults(_handler="top_slices")

    p = sub.add_parser(
        "bundle",
        parents=[common],
        help="Single JSON: overview + jank + scroll (for CI / archives)",
    )
    p.add_argument("--process", "-p", required=True, help="App package name")
    p.set_defaults(_handler="bundle")

    return parser


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)

    trace = args.trace
    if not Path(trace).is_file():
        print(f"error: trace file not found: {trace}", file=sys.stderr)
        sys.exit(1)

    pretty = not args.compact
    output = args.output
    analyzer = TraceAnalyzer()

    try:
        handler = args._handler
        if handler == "overview":
            cmd_overview(analyzer, trace, pretty, output)
        elif handler == "startup":
            cmd_startup(analyzer, trace, args.process, pretty, output)
        elif handler == "jank":
            cmd_jank(analyzer, trace, args.process, pretty, output)
        elif handler == "scroll":
            cmd_scroll(analyzer, trace, args.process, args.layer_hint, pretty, output)
        elif handler == "sql":
            sql = args.sql
            if args.sql_file is not None:
                sql = args.sql_file.read_text(encoding="utf-8")
            cmd_sql(analyzer, trace, sql, pretty, output)
        elif handler == "top_slices":
            cmd_top_slices(
                analyzer,
                trace,
                args.process,
                args.thread,
                args.name_pattern,
                args.min_dur_ms,
                args.limit,
                args.main_thread_only,
                pretty,
                output,
            )
        elif handler == "bundle":
            cmd_bundle(analyzer, trace, args.process, pretty, output)
        else:
            raise RuntimeError(f"unknown handler {handler}")
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        analyzer.close_all()


if __name__ == "__main__":
    main()
