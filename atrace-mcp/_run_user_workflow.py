#!/usr/bin/env python3
"""One-shot workflow for user-requested capture + analysis."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_base = Path(__file__).resolve().parent
if str(_base) not in sys.path:
    sys.path.insert(0, str(_base))
_repo_root = _base.parent
_monorepo_path = _repo_root / "_monorepo.py"
if _monorepo_path.is_file():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    import _monorepo; _monorepo.bootstrap()  # noqa: E702

from server import (  # noqa: E402
    analyze_jank,
    analyze_scroll_performance,
    capture_trace,
    list_devices,
    load_trace,
    query_app_status,
)

PKG = "com.qiyi.video"
DURATION = 8


def main() -> None:
    print("=== 1. list_devices ===")
    print(list_devices())
    print()

    print("=== 2. query_app_status ===")
    print(query_app_status(package=PKG))
    print()

    print("=== 3. capture_trace (duration=8, inject_scroll=true) ===")
    cap = capture_trace(
        package=PKG,
        duration_seconds=DURATION,
        inject_scroll=True,
        output_dir="/tmp/atrace",
    )
    print(cap)
    print()

    merged: str | None = None
    try:
        data = json.loads(cap)
        merged = data.get("merged_trace")
    except (json.JSONDecodeError, TypeError):
        pass
    if not merged:
        print("No merged_trace in capture response; stopping before load/analyze.")
        sys.exit(1)

    print("=== 4. load_trace ===")
    print(load_trace(merged, process_name=PKG))
    print()

    print("=== 5. analyze_scroll_performance ===")
    print(analyze_scroll_performance(merged, PKG))
    print()

    print("=== 6. analyze_jank ===")
    print(analyze_jank(merged, PKG))
    print()


if __name__ == "__main__":
    main()
