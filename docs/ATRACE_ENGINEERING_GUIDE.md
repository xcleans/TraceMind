# ATrace 工程级指南：采集、工具链与 MCP 分析

本文界定 **ATrace 仓库各模块职责**、**设备端到 `.perfetto` 文件的数据路径**、**`atrace-mcp` 与底层采集实现的衔接关系**，以及 **分析能力** 的分层归属；并说明 **命令行 / CI** 如何复用同一采集 JAR。适用于集成、扩展与故障排查。

---

## 1. 仓库模块地图

| 模块 | 角色 | 典型使用者 |
|------|------|------------|
| **`atrace-api`** | 对外 Kotlin API（`ATrace`、`TraceConfig` 等） | 应用工程 |
| **`atrace-core`** | 采样引擎、Native Hook、HTTP TraceServer、导出二进制采样 | 应用工程（依赖 api） |
| **`atrace-tool`** | **Fat JAR**（ADB、`record_android_trace`、拉取 ATrace 应用采样、解码合并为 `.perfetto`；含 `cpu` / `heap` / `devices` 等） | **MCP 合并采集时内部调用**；工程师 CLI、CI 亦可直接使用 |
| **`atrace-mcp`** | Python MCP Server：`capture_trace`、SQL 分析、simpleperf、heapprofd、运行时控制等；**在 Cursor 等客户端中支持自然语言驱动的轨迹分析自动化** | Cursor、Claude Desktop 等 |
| **`sample`** | 示例 App | 联调 |
| **`docs/`** | 专题文档（卡顿、动态插桩等） | 全员 |

插件若独立为 `atrace-plugins` 等，仍以根工程 `settings.gradle.kts` 为准。

---

## 2. 三条「平面」

### 2.1 数据平面（Trace 文件从哪来）

1. **系统侧**：`atrace-tool capture` 通过 **`record_android_trace`**（Perfetto 官方 Android 录制脚本，随 jar 资源或 PATH）在设备上采集 **ftrace / atrace / FrameTimeline** 等，得到系统 **Perfetto 原始包流**。
2. **应用侧**（可选）：集成 `atrace-core` 的应用在 **HTTP**（默认经 ADB forward）上响应 start/stop，并导出 **二进制采样文件**（magic `ATRC`，与 Native `ExportToFile` 对齐）及 **符号映射**。
3. **合并**：`atrace-tool` 内 **`SamplingDecoder` → `StackConvertor` → `TraceBuilder`** 将应用采样转为 Perfetto 的 **slice / track**（含 Section、Message、调用栈树），再与系统 trace **按 protobuf 包流拼接**，输出 **单个 `.perfetto`**。

若 HTTP 不可达，**降级为仅系统 trace**（无应用轨道），流程不中断。

### 2.2 控制平面（谁发 start/stop、改配置）

| 通道 | 能力 |
|------|------|
| **HTTP（atrace-core TraceServer）** | 启停 trace、插件开关、WatchList、动态 hook、即时抓栈等 |
| **`atrace-tool capture`** | 脚本化：时长、输出路径、`-c` Perfetto 配置、systrace 分类、ProGuard mapping |
| **`atrace-mcp`** | 封装上述能力为 **MCP tools**，并驱动 **atrace-tool** 做重采集 |

### 2.3 分析平面（谁做「分析」）

| 层级 | 能力 | 不负责 |
|------|------|--------|
| **`atrace-tool`** | 解码、合并、**simpleperf report** 文本、**heap** 产出 `.perfetto` | PerfettoSQL、卡顿结论、火焰图渲染 |
| **Perfetto UI** | 时间轴、手动 SQL、Heap 视图 | 自动化报告 |
| **`atrace-mcp`** | `load_trace` 后 **Trace Processor（Python `perfetto` 包）** 执行 SQL；**`analyze_*`** 封装常用查询（启动、卡顿、滑动、heap） | 不替代 UI 的全部交互 |

结论：**工程内「智能分析」主要在 `atrace-mcp`**；**`atrace-tool` 负责可复现的采集与格式转换**。

---

## 3. `atrace-tool` 与 `atrace-mcp` 的调用关系

`atrace-mcp` 的 **`device_controller.py`** 通过统一入口调用：

```text
java -jar <atrace-tool.jar> [--json] <subcommand> ...
```

| MCP 工具 / 流程 | 对应的 `atrace-tool` |
|-----------------|----------------------|
| **`capture_trace`**（合并系统 + 应用） | `capture --json`（参数由 MCP 组装：`-a`、`-t`、`-s` 等） |
| **`capture_cpu_profile`**（优先路径） | `cpu --json` |
| **`capture_heap_profile`**（优先路径） | `heap --json` |
| **`list_devices`**（可选对齐） | `devices --json` |
| **`check_device_tools`** | 可触发 **atrace-tool / NDK simpleperf** 等准备逻辑 |

若本机 **未构建 `atrace-tool` JAR**，MCP 会返回构建提示（见 `tool_provisioner` / `ensure_atrace_tool()`）。

**详细 CLI 与子命令**：见 [`atrace-tool/README.md`](../atrace-tool/README.md)。

---

## 4. `atrace-mcp` 分析能力一览

以下均在 **`load_trace(trace_path)`** 之后对**同一文件**生效（Trace Processor 会话）。

### 4.1 通用查询

| 工具 | 用途 |
|------|------|
| `trace_overview` | 时长、进程/线程、slice 规模 |
| `query_slices` | 按进程/线程/name/最小时长过滤 slice |
| `execute_sql` | 任意 **PerfettoSQL** |
| `call_chain` / `slice_children` | 从某 slice 上钻/下钻 |
| `thread_states` | Running / Blocked 等分布 |

资源 **`atrace://sql-patterns`**：常用 SQL 片段。

### 4.2 封装分析（高阶）

| 工具 | 场景 |
|------|------|
| `analyze_startup` | 冷启动阶段与慢点 |
| `analyze_jank` | 快速烟雾（长帧/Choreographer） |
| `analyze_scroll_performance` | **滑动与帧质量**（依赖 FrameTimeline，API 31+ 等条件） |
| `analyze_heap_profile` | native heap trace 的 Top 分配等 |

**滑动 / 帧分析**的解读与 SQL 补充：见 [`PERFETTO_JANK_GUIDE.md`](PERFETTO_JANK_GUIDE.md)、[`JANK_CHECKLIST.md`](JANK_CHECKLIST.md)。

### 4.3 CPU / Heap（与 tool 的衔接）

- **CPU**：MCP 优先走 **`atrace-tool cpu`**；另有 **`report_cpu_profile`**、**`generate_flamegraph`** 等处理已拉回的 `perf.data`。
- **Heap**：MCP 优先走 **`atrace-tool heap`**；**`analyze_heap_profile`** 对 **`.perfetto`** 做 SQL 汇总。

官方背景：[Perfetto Memory Profiling](https://perfetto.dev/docs/getting-started/memory-profiling)。

### 4.4 Prompts

`atrace-mcp/prompts.py` 注册 **`scroll_performance_workflow`**、**`iterative_diagnosis`** 等，将 **采集 + 多工具分析** 编排为对话流程。列表见 [`atrace-mcp/README.md`](../atrace-mcp/README.md)。

### 4.5 `load_trace` / 分析报错 `Request-sent` 或 `ResponseNotReady`

**原因（已修复）**：Python `perfetto.trace_processor.TraceProcessor` 通过单连接与子进程通信，**不支持并发 `query()`**。宿主（如 Cursor）若对同一 MCP 会话**并行**调用 `analyze_startup`、`trace_overview`、`execute_sql` 等，会触发 `CannotSendRequest('Request-sent')` / `ResponseNotReady`，在客户端常表现为工具失败或超时类错误。

**实现**：`atrace-mcp/trace_analyzer.py` 内 **`TraceAnalyzer` 使用 `threading.RLock` 串行化**所有 `TraceProcessor` 的创建、`query()` 迭代与 `close`，并行调用会排队执行而非损坏连接。

**仍可能超时的情况**：单份 trace 极大或磁盘慢时，**首次** `TraceProcessor(trace=path)` 可能耗时数十秒；若 IDE 对 MCP 工具有固定超时，可尝试缩短采集窗口、或查阅当前 Cursor 版本是否支持调大 MCP 工具超时（以官方设置为准）。

---

## 5. 推荐工作流（工程实践）

### 5.1 仅命令行、可脚本化

1. 设备连接 ADB，应用已集成 **atrace-core** 并运行。  
2. `java -jar atrace-tool-*.jar capture -a <pkg> -t 10 -o out.perfetto`  
3. 用 **Perfetto UI** 打开 `out.perfetto`，或自行跑 **trace_processor_shell**。

### 5.2 Cursor：基于 MCP 的轨迹分析自动化

在 **Cursor** 中以对话串联 MCP 工具，可将 **采集 → 加载 → 查询 / 预置分析** 交由模型辅助编排，减少逐步手写 SQL 与 Shell 的工作量。相对纯手工，常见收益为：**端到端工具切换更少**、**Perfetto 表结构 / SQL 模板依赖更低**、**同一会话内多轮下钻**、**结构化输出便于对比与归档**（对比表见根目录 [README.md](../README.md)「Cursor MCP：AI 辅助下的轨迹分析」一节）。

1. 配置 MCP（见根目录 [`.cursor/README.md`](../.cursor/README.md)）。  
2. 使用 **`capture_trace`** 或 **`scroll_performance_workflow`** 得到 trace 路径。  
3. **`load_trace`** → **`analyze_scroll_performance`** / **`analyze_startup`** / **`execute_sql`** 迭代（工具调用宜**串行**，避免 Trace Processor 并发错误，见 §4.5）。  
4. Trace Processor 启动失败时：按 MCP 提示用 **Perfetto UI** 打开同一文件（文件通常仍有效）。  

**可复现实验与结论校验**（合并轨迹、冷启动、锁竞争 SQL）：见 [`ATRACE_MCP_DEMO_SCENARIOS.md`](ATRACE_MCP_DEMO_SCENARIOS.md)。

### 5.3 CI / 门禁

- 采集：`atrace-tool capture --json` 解析 stdout 中的 `merged_trace` 路径。  
- 分析：对固定 trace 跑 **Python trace_processor** 或自建脚本；或与 **MCP 解耦**，直接复用 `atrace-mcp` 内 SQL 逻辑（需抽库）。

---

## 6. 相关文档索引

| 文档 | 内容 |
|------|------|
| [`atrace-tool/README.md`](../atrace-tool/README.md) | CLI 子命令、数据流、与 MCP 边界 |
| [`atrace-mcp/README.md`](../atrace-mcp/README.md) | MCP 工具全集、`docs/configs` 场景配置、Prompt、打包分发、故障排查 |
| [`ATRACE_MCP_DEMO_SCENARIOS.md`](ATRACE_MCP_DEMO_SCENARIOS.md) | **MCP 轨迹分析自动化**：样例参数、输出量级、冷启动 / 锁竞争说明与 SQL |
| [`PERFETTO_JANK_GUIDE.md`](PERFETTO_JANK_GUIDE.md) | 卡顿与 FrameTimeline 分析 |
| [`configs/README.md`](configs/README.md) | Perfetto 场景 `.txtpb` 索引 |
| [`ARTMETHOD_WATCHLIST.md`](ARTMETHOD_WATCHLIST.md) | 动态插桩 / WatchList（`addWatchedRule` 等） |
| [Perfetto ATrace 与 ftrace](https://perfetto.dev/docs/getting-started/atrace) | 应用 slice 与系统 trace 同 buffer 的关系 |

---

## 7. 版本与兼容（摘要）

- **应用采样合并**：依赖 **atrace-core** 与 **atrace-tool** 二进制格式一致（`ATRC` 头、extra JSON 字段）。  
- **FrameTimeline 深度分析**：需 trace 中含对应数据源，且系统版本满足 MCP 工具注释中的 API 要求。  
- **Heap**：API 29+，应用 **profileable 或 debuggable**。

---

*本文随仓库演进更新；若与源码行为不一致，以 `atrace-tool` 与 `atrace-mcp` 的实现为准。*
