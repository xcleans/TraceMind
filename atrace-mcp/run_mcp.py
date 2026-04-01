#!/usr/bin/env python3
"""Cross-platform launcher for atrace-mcp (Mac & Windows).

Finds the atrace-mcp directory from __file__, chdirs there, then runs server.py.
Use in MCP config so only one path is needed; works with: uv run <path>/run_mcp.py
"""
from __future__ import annotations

import os
import runpy
import sys

def main() -> None:
    base = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base)
    if base not in sys.path:
        sys.path.insert(0, base)
    runpy.run_path(os.path.join(base, "server.py"), run_name="__main__")

if __name__ == "__main__":
    main()
