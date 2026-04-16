# atrace-analyzer

**TraceMind** 的 Perfetto 分析引擎：**PerfettoSQL**、启动 / 卡顿 / 滑动等指标，以及与 **`atrace-mcp`** 共用的 **`TraceAnalyzer`**。

## 无 AI 快速分析：`atrace-analyze`

安装本包后可直接在终端输出 **JSON**（适合 CI、脚本、无 Cursor 环境）：

```bash
pip install -e .   # 或 monorepo 下 ./dev-setup.sh
atrace-analyze overview /path/to/trace.perfetto
atrace-analyze bundle /path/to/trace.perfetto --process com.example.app -o snapshot.json
```

开发时：

```bash
cd atrace-analyzer
uv run atrace-analyze --help
uv run python -m atrace_analyzer.cli overview /path/to/trace.perfetto
```

子命令：`overview`、`startup`、`jank`、`scroll`、`sql`、`top-slices`、`bundle`。详见 **`python -m atrace_analyzer.cli --help`**。

**MCP**：自然语言与多轮下钻见 **`../atrace-mcp`**；分析内核一致。

## 依赖

- Python ≥ 3.10  
- **`perfetto`** Python 包（Trace Processor）

## 许可证

Apache-2.0（与仓库根 TraceMind 一致）。
