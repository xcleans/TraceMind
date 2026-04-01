# atrace-mcp/bin/

This directory contains pre-built JVM tools bundled with the MCP server.

## atrace-tool.jar

**Purpose**: Captures and merges Perfetto system trace + ATrace app sampling into a
single unified `.perfetto` file that Cursor can query via PerfettoSQL.

**Build / update**:
```bash
# From project root
./gradlew deployMcp
```

This runs `./gradlew :atrace-tool:jar` (fat JAR with all deps) and copies the
result here as `atrace-tool.jar`.

**Requirements at runtime**: Java 11+ on the host machine (`java` on PATH).

## Distribution

When distributing the MCP server independently, include this entire `atrace-mcp/`
directory. The `bin/atrace-tool.jar` makes the server self-contained — no Gradle
or separate atrace-tool installation needed.

```
atrace-mcp/
├── server.py
├── device_controller.py
├── tool_provisioner.py
├── trace_analyzer.py
├── prompts.py
├── run_mcp.py
├── pyproject.toml
├── requirements.txt
├── scripts/
│   ├── record_android_trace
│   └── record_android_trace_win
├── simpleperf_toolkit/
└── bin/
    └── atrace-tool.jar   ← this file
```
