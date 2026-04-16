# ATrace MCP

在 **Cursor / Claude Desktop** 等支持 **Model Context Protocol (MCP)** 的宿主中，用自然语言驱动 **Android Perfetto（`.perfetto`）** 的 **采集、加载、PerfettoSQL 查询** 与 **结构化分析**（启动 / 卡顿 / 滑动帧质量等）。分析引擎为 `**atrace-analyzer`** 中的 `**TraceAnalyzer**`（`atrace-mcp` 经 `trace_analyzer.py` 引用）；**命令行分析不在本文档说明**。


| 项         | 说明                                                                   |
| --------- | -------------------------------------------------------------------- |
| **运行时**   | Python ≥ 3.10，`fastmcp` + `perfetto`（Trace Processor）                |
| **采集与设备** | `atrace-capture` → `DeviceController`（ADB、应用 HTTP、`atrace-tool` CLI） |
| **分析**    | `atrace-analyzer` 中的 `TraceAnalyzer`                                 |
| **布局**    | **扁平包**：根目录 `.py` 由 `pyproject.toml` 的 `py-modules` 打进 wheel         |


---

## 1. 功能


| 能力                | 说明                                                                        |
| ----------------- | ------------------------------------------------------------------------- |
| **加载与总览**         | `load_trace`、`trace_overview`；后续分析依赖已加载 trace 或显式 `trace_path`            |
| **即席查询**          | `query_slices`、`execute_sql`（PerfettoSQL）                                 |
| **结构化分析**         | `analyze_startup`、`analyze_jank`、`analyze_scroll_performance`             |
| **下钻**            | `slice_children`、`call_chain`；可选 `thread_states`                          |
| **本机看图**          | `open_trace_in_perfetto_browser`（localhost HTTP + CORS + ui.perfetto.dev） |
| **设备侧**           | `capture_trace`（合并系统 Perfetto + 应用 ATrace）、插件 / 采样 / Watch / hook / 预设等   |
| **Profiling**     | simpleperf CPU、heapprofd 堆、火焰图与 Firefox Profiler 转换等                      |
| **MCP Resources** | Perfetto 场景 `.txtpb` 与 SQL 参考（`atrace://…` URI）                           |
| **MCP Prompts**   | `prompts.py` 中 `@mcp.prompt`：中文标准编排、滑动工作流、英文分析模板等                         |


上表为导读；**注册名、参数、`payload_json` 键、Resource URI、Prompt 全量与编排以第 5 节为准**。**口语场景 · Prompt · Tools · Perfetto · CLI 对照仅维护一份**：见 **第 5.7 节**。

---

## 2. 工程结构

```
atrace-mcp/
├── server.py              # FastMCP 入口：stdio（默认）/ HTTP 调试 0.0.0.0:8090
├── run_mcp.py             # 控制台入口：chdir + 可选 _monorepo + 执行 server
├── trace_analyzer.py      # TraceAnalyzer 门面 → atrace_analyzer
├── device_controller.py   # from atrace_capture.device_controller import DeviceController
├── tool_provisioner.py    # JAR / simpleperf / perfetto 设备端准备
├── prompts.py             # MCP Prompt 模板（register_prompts）
├── mcp_pipeline.py        # 工具调用日志 → log/atrace-mcp-pipeline.log
├── tools/
│   ├── __init__.py        # register_all_tools
│   ├── query_tools.py     # load_trace、trace_overview、execute_sql、open_trace_in_perfetto_browser …
│   ├── analysis_tools.py  # analyze_startup / analyze_jank / analyze_scroll_performance
│   ├── control_tools.py   # capture_trace、插件、采样、watch、hook、replay、presets …
│   ├── profiling_tools.py # simpleperf / heapprofd、火焰图
│   └── resources.py       # MCP Resources
├── mcp_bundled_resources/ # wheel：Perfetto SQL 参考等
└── scripts/
    ├── build_release.sh   # 仓库根：JAR → capture wheel → mcp wheel → dist/ + zip
    └── README.md
```

**概念依赖**

```
MCP 宿主 → server.py (FastMCP)
            ├─ TraceAnalyzer      ← atrace-analyzer
            ├─ DeviceController   ← atrace-capture ← atrace-device, atrace-provision
            └─ tools/*             @mcp.tool / @mcp.resource / @mcp.prompt
```

---

## 3. 依赖与前置条件


| 项                     | 要求                                                                                                         |
| --------------------- | ---------------------------------------------------------------------------------------------------------- |
| **Python**            | ≥ 3.10（见 `pyproject.toml`）                                                                                 |
| **包管理**               | 推荐 [uv](https://docs.astral.sh/uv/)；亦可用 `pip` + venv                                                       |
| **分析引擎**              | 须能 `import atrace_analyzer`（`**./dev-setup.sh`**、editable 安装或 `**_monorepo.bootstrap()**`）                 |
| **ADB**               | `adb devices` 可用（采集 / 设备类工具）                                                                               |
| `**atrace-tool` JAR** | 合并采集依赖；仓库根 `**./gradlew deployMcp`** → `**atrace-provision/atrace_provision/bundled_bin/atrace-tool.jar**` |
| **应用集成 ATrace**       | HTTP 控制与合并流水线需宿主 App 已接入 SDK                                                                               |


Python 依赖（节选）：`fastmcp`、`perfetto`、`httpx`、`pydantic`、`atrace-capture`（monorepo 下多为 path editable）。

---

## 4. 打包与分发与 MCP 安装

### 4.1 仅离线 zip 发版

在仓库根执行：

```bash
./platform/atrace-mcp/scripts/build_release.sh           # 版本读 platform/atrace-mcp/pyproject.toml
./platform/atrace-mcp/scripts/build_release.sh 0.2.0     # 指定 MCP 版本（zip 名）
```

概要：`**./gradlew deployMcp**` → 构建必要 Python 包 → 产出 `**dist/atrace-mcp-v<MCP>.zip**`。

**zip 解压根目录**须 **同级** 包含：`platform/atrace-mcp/`、`platform/atrace-capture/`、`platform/atrace-device/`、`platform/atrace-provision/`、`platform/atrace-analyzer/`、`**platform/_monorepo.py`**（及可选 `platform/_logging.py`）。**旧包**（仅 mcp+capture）会报 `**Distribution not found .../atrace-device`** 等 — 请重新 `**build_release.sh**` 后解压到独立目录。

### 4.2 离线 zip 运行 MCP 进程

```bash
cd /path/to/bundle/platform/atrace-mcp
uv run python server.py                      # stdio（Cursor 默认）
uv run python server.py --transport http     # HTTP 调试 0.0.0.0:8090
uv run python run_mcp.py                     # 先 chdir 再等价启动
```

### 4.3 离线 zip 接入 Cursor（`mcp.json`）

1. 编辑项目 `**.cursor/mcp.json**` 或全局 `**~/.cursor/mcp.json**`。
2. `**uv run --directory**` 指向 `**…/bundle/platform/atrace-mcp**`（且 bundle 根含上表各目录与 `**platform/_monorepo.py**`）。
3. **完全重启 Cursor**；在 **设置 → MCP** 中确认 `**load_trace`**、`**capture_trace**` 等工具已列出。

```json
{
  "mcpServers": {
    "atrace": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/ABS/PATH/bundle/platform/atrace-mcp",
        "python",
        "run_mcp.py"
      ]
    }
  }
}
```

---

## 5. MCP：Tools · Resources · Prompts

本节与 `**tools/*.py**`、`**prompts.py**`、`**tools/resources.py**` 注册内容一一对应。

### 5.1 Tools（`@mcp.tool`，全部）

**调用约定**


| 类别                                                           | 调用方式                                                                                      |
| ------------------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| **Trace / 查询 / 结构化分析**（`query_tools.py`、`analysis_tools.py`） | 单参数 `**payload_json`**：值为 **JSON 对象的字符串**（服务端 `json.loads`）。`sql`、路径中的 `"` 与换行须按 JSON 转义。 |
| **设备控制、Profiling**（`control_tools.py`、`profiling_tools.py`）  | **扁平具名参数**（以各工具在 MCP 中暴露的 schema 为准）。                                                     |


**Trace 与查询**（`tools/query_tools.py`）


| 工具                               | 作用                                    |
| -------------------------------- | ------------------------------------- |
| `load_trace`                     | 加载 `.perfetto` 到 Trace Processor      |
| `trace_overview`                 | 时长、进程、slice 规模等总览                     |
| `query_slices`                   | 按进程 / 线程 / 名称 / 耗时等过滤 slice           |
| `execute_sql`                    | 任意 PerfettoSQL                        |
| `call_chain`                     | 自给定 `slice_id` 向上溯源                   |
| `slice_children`                 | 子 slice 下钻                            |
| `thread_states`                  | 线程 Running / Sleeping / Blocked 等状态分布 |
| `open_trace_in_perfetto_browser` | 本机起 HTTP + 在 ui.perfetto.dev 打开 trace |


**结构化分析**（`tools/analysis_tools.py`）


| 工具                           | 作用                       |
| ---------------------------- | ------------------------ |
| `analyze_startup`            | 冷 / 温启动阶段与主线程阻塞          |
| `analyze_jank`               | Choreographer 等 jank 线索  |
| `analyze_scroll_performance` | 滑动帧质量（依赖 trace 中帧时间线等数据） |


**设备与应用控制**（`tools/control_tools.py`）


| 工具                                                                                    | 作用                                                         |
| ------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| `list_devices`                                                                        | 列出已连接 ADB 设备                                               |
| `query_app_status`                                                                    | 查询已集成 ATrace 的应用状态（HTTP）                                   |
| `capture_trace`                                                                       | 合并采集：系统 Perfetto + 应用 ATrace（见第 5.6 小节）                    |
| `pause_tracing` / `resume_tracing`                                                    | 暂停 / 恢复采样                                                  |
| `list_plugins` / `toggle_plugin`                                                      | 列出 / 开关插件                                                  |
| `get_sampling_config` / `set_sampling_interval`                                       | 读取 / 设置采样间隔（`0` 表示该项不修改）                                   |
| `list_watch_patterns` / `add_watch_rule` / `add_watch_entries` / `add_watch_patterns` | Watch 规则                                                   |
| `remove_watch_pattern` / `remove_watch_entry` / `clear_watch_patterns`                | 移除 / 清空 Watch                                              |
| `hook_method` / `unhook_method`                                                       | 方法级 hook                                                   |
| `query_threads` / `list_process_threads`                                              | 线程列表                                                       |
| `add_trace_mark`                                                                      | 插入自定义标记（参数名为 `**name`**）                                   |
| `capture_stack`                                                                       | 触发即时栈采样                                                    |
| `replay_scenario`                                                                     | 设备侧场景：`cold_start` / `hot_start` / `scroll` / `tap_center` |
| `list_capture_presets`                                                                | 列出采集预设与 Perfetto 模板名                                       |
| `capture_with_preset`                                                                 | 按预设名执行采集（`atrace-capture` 配置注册表）                           |


**Profiling**（`tools/profiling_tools.py`）


| 工具                           | 作用                              |
| ---------------------------- | ------------------------------- |
| `check_device_tools`         | 检查设备端 simpleperf / 相关工具是否就绪     |
| `convert_to_firefox_profile` | 将 perf 数据转为 Firefox Profiler 格式 |
| `capture_cpu_profile`        | simpleperf CPU 采样采集             |
| `report_cpu_profile`         | 文本报告（按 sort_keys、percent_limit） |
| `generate_flamegraph`        | 生成火焰图（可选 Firefox Profiler）      |
| `capture_heap_profile`       | heapprofd 堆采集                   |
| `analyze_heap_profile`       | 对已含 heap 数据的 trace 做 Top 分配分析   |
| `trace_viewer_hint`          | 返回在本机打开 trace 的简要提示             |


### 5.2 `payload_json` 字段速查


| 工具                                                                | 常用字段                                                                              | 说明                                                                                |
| ----------------------------------------------------------------- | --------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| `load_trace`                                                      | `trace_path`, `process_name`                                                      | `trace_path` 在无法从会话 / `**ATRACE_DEFAULT_TRACE_PATH`** 推断时**必填**；`process_name` 可选 |
| `trace_overview`                                                  | `trace_path`（可选）                                                                  | 建议与当前文件一致                                                                         |
| `analyze_startup` / `analyze_jank` / `analyze_scroll_performance` | `trace_path`（可选）, `**process`**                                                   | 进程过滤用 `**process**`（子串），**不要**写 `process_name`                                    |
| `analyze_scroll_performance`                                      | 另可选 `layer_name_hint`                                                             |                                                                                   |
| `query_slices`                                                    | `process`, `thread`, `name_pattern`, `min_dur_ms`, `limit`, `main_thread_only`, … |                                                                                   |
| `execute_sql`                                                     | `**sql`（必填）**, `trace_path`（可选）                                                   |                                                                                   |
| `call_chain` / `slice_children`                                   | `**slice_id`（必填）**, `trace_path`（可选）                                              | `slice_children` 可选 `**limit`**（默认 20）                                            |
| `thread_states`                                                   | `**thread_name`（必填）**, `trace_path`（可选）, `ts_start`, `ts_end`                     | 纳秒时间窗可选                                                                           |
| `open_trace_in_perfetto_browser`                                  | `trace_path`, `open_browser`, `port`, …                                           | 见工具 docstring                                                                     |


**示例**

`load_trace`（键名为 `**process_name`**）：

```json
{"trace_path":"/tmp/app.perfetto","process_name":"com.example.app"}
```

`analyze_jank` / `query_slices`（键名为 `**process**`）：

```json
{"trace_path":"/tmp/app.perfetto","process":"com.example.app"}
```

**串行**：同一会话内，`load_trace` 之后的 `trace_overview`、`analyze_*`、`execute_sql`、`slice_children`、`call_chain` 等会占用 Trace Processor — **须串行调用，勿并行**。

**设备侧常用扁平参数形态**（节选）


| 说明   | 示例形态                                                                                                                                   |
| ---- | -------------------------------------------------------------------------------------------------------------------------------------- |
| 合并采集 | `capture_trace(package=..., duration_seconds=..., cold_start=..., inject_scroll=..., perfetto_config=..., serial=..., port=9090, ...)` |
| 探活   | `query_app_status(package=..., serial=..., port=...)`                                                                                  |
| 插件   | `toggle_plugin(plugin_id, enable, package=..., serial=..., port=...)`                                                                  |
| 标记   | `**add_trace_mark(name=..., package=..., ...)`**（参数为 `**name**`）                                                                       |


### 5.3 MCP Resources（`@mcp.resource`，全部）

宿主通过 **Resource URI** 读取只读内容（实现见 `**tools/resources.py`**）。


| URI                               | MIME（注册时）       | 内容                                                          |
| --------------------------------- | --------------- | ----------------------------------------------------------- |
| `atrace://configs/index`          | `text/markdown` | 场景 `.txtpb` 索引表（含各子 URI 用途）                                 |
| `atrace://configs/readme`         | `text/markdown` | 包内 `**README.md**`（场景说明）                                    |
| `atrace://configs/startup`        | （默认文本）          | `startup.txtpb`                                             |
| `atrace://configs/scroll`         | （默认文本）          | `scroll.txtpb`                                              |
| `atrace://configs/memory`         | （默认文本）          | `memory.txtpb`                                              |
| `atrace://configs/binder`         | （默认文本）          | `binder.txtpb`                                              |
| `atrace://configs/animation`      | （默认文本）          | `animation.txtpb`                                           |
| `atrace://configs/full-template`  | （默认文本）          | `config.txtpb`（全量模板）                                        |
| `atrace://perfetto-sql-reference` | `text/markdown` | 从仓库 bundled 参考文档中截取的表结构 + 常用 Android 查询（供 `execute_sql` 对照） |
| `atrace://sql-patterns`           | （默认文本）          | 内嵌的短 PerfettoSQL 片段（主线程慢函数、Binder、GC、锁、IO、heap 等）           |


**解析目录与覆盖**

- 场景文件真源目录：`**atrace-capture/atrace_capture/config/perfetto/`**（随 `**atrace-capture**` 安装；`bundled_perfetto_configs_dir()`）。
- `**ATRACE_PERFETTO_CONFIGS**` 或兼容别名 `**ATRACE_DOCS_CONFIGS**`：若设为**目录**，则 MCP 与 `capture_trace` 的默认解析优先使用该目录下的同名 `.txtpb` / `README.md`。
- `**ATRACE_PERFETTO_SQL_REFERENCE`**：覆盖 `atrace://perfetto-sql-reference` 的源文件路径（否则用 `**mcp_bundled_resources/perfetto-trace-processor-reference.md**`）。

更细的字段级说明见同目录下的 **[../atrace-capture/atrace_capture/config/perfetto/README.md](../atrace-capture/atrace_capture/config/perfetto/README.md)**。

### 5.4 MCP Prompts（`@mcp.prompt`，全部）

在 Cursor **MCP → Prompts** 中选下列名称（与 `**prompts.py` 中函数名**一致），将生成文本贴回对话执行。


| Prompt                           | 参数                                         | 用途概要                                                             |
| -------------------------------- | ------------------------------------------ | ---------------------------------------------------------------- |
| `platform_hub_zh`                | 无                                          | 中文入口：标准 Prompt 选用表 + `payload_json` 字段约定 + 串行规则                  |
| `cn_standard_review`             | `trace_path`, `process_name`               | 已有 trace：总览 → 帧 → jank → 主线程 Top SQL → 下钻                        |
| `cn_standard_startup`            | `trace_path`, `process_name`               | 已有 trace：启动分析 + 阻塞下钻                                             |
| `cn_standard_jank`               | `trace_path`, `process_name`               | 已有 trace：滑动帧质量 + jank + 最重帧下钻                                    |
| `cn_standard_blocking`           | `trace_path`, `process_name`               | 已有 trace：Binder/Lock/GC/IO 等 + `thread_states`                   |
| `cn_standard_cold_start_capture` | `package`, 可选 `duration_seconds`, `serial` | 设备：`list_devices` → 状态 → `capture_trace(cold_start)` → 启动 + jank |
| `analyze_trace`                  | `trace_path`, 可选 `process_name`, `concern` | 英文通用分析工作流                                                        |
| `startup_analysis`               | `trace_path`, `process_name`               | 英文冷启动                                                            |
| `jank_analysis`                  | `trace_path`, `process_name`               | 英文卡顿 / 帧                                                         |
| `blocking_analysis`              | `trace_path`, `process_name`               | 英文主线程阻塞                                                          |
| `quick_health_check`             | `trace_path`                               | 英文快速健康检查（规模与进程）                                                  |
| `smart_capture`                  | `package`, 可选 `scenario`, `duration`       | 英文智能采集（预检 → 按场景调插件/采样 → `capture_trace`）                         |
| `iterative_diagnosis`            | `trace_path`, `process_name`, `symptom`    | 英文迭代诊断（观测 → 假设 → 改配置复采 → 验证）                                     |
| `plugin_tuning`                  | `package`                                  | 英文插件与采样调参实验                                                      |
| `scroll_performance_workflow`    | `package`, 多选滚动/时长/`trace_path`/`serial` 等 | **当前页**滑动：可选采集（`inject_scroll`）或仅分析已有 `trace_path`               |
| `explore_issue`                  | `trace_path`, `process_name`, `question`   | 英文开放式单点问题排查                                                      |


### 5.5 Prompt 编排说明

**分层结构**

1. **入口层**：`**platform_hub_zh`** 无参，向模型列出全部中文标准 Prompt 及选用条件；并重复 `**payload_json` / `process` vs `process_name**` 等与服务器一致的硬性约定。
2. **场景层（中文）**：`**cn_standard_*`** 与 `**cn_standard_cold_start_capture**` — 每个返回一段**固定步骤**的说明文，要求模型按顺序 **串行** 调用 MCP 工具；步骤内已写好示例 JSON 形态（注意对 `{` `}` 在 f-string 中的转义以源码为准）。
3. **场景层（英文）**：`**analyze_trace`**、`**startup_analysis**`、`**jank_analysis**`、`**blocking_analysis**` 等与中文编排**逻辑等价**，便于英文团队或英文报告输出。
4. **复合工作流**：`**scroll_performance_workflow`**（采集 + 分析或仅分析）、`**smart_capture**`、`**iterative_diagnosis**`、`**plugin_tuning**` — 在单 Prompt 内串联**设备扁平工具**与 **Trace `payload_json` 工具**。
5. **轻量 / 自由**：`**quick_health_check`**、`**explore_issue**`。

**编排共性（模型必须遵守）**

- **Trace 类工具串行、`payload_json` 键名（含 `process` / `process_name`）：** 与**第 5.2 小节**一致，此处不重复列举工具名。
- `**capture_trace` 会阻塞**整个 `duration_seconds`；录制窗口内自动滑动须 `**inject_scroll=True`**（见 `**scroll_performance_workflow**`、`**smart_capture**`），**不要**在 `capture_trace` 返回后再指望同一录制窗口内接 `**replay_scenario("scroll")`**。

**与仓库文档的关系**

- **话术、场景编排总表、可复制对话模板、分析报告全文**已收拢在本文**第 6 节**；**工具名与字段以本文第 5.1、5.2 小节与源码为准**。

### 5.6 `perfetto_config` 与场景 `.txtpb`

**真源路径**

- 仓库内：`**atrace-capture/atrace_capture/config/perfetto/*.txtpb`**（及 `**README.md**`）。
- 安装后：由 `**atrace_capture.config.perfetto_paths.bundled_perfetto_configs_dir()**` 指向包内同构目录。

`**capture_trace(..., perfetto_config=...)**`

- 类型：可选 `**str | None**`。传入 `**atrace-tool**` 的 `**-c**` 配置文件路径（`**.txtpb**`）。
- `**None` / 空字符串**：不覆盖，使用 `**atrace-tool`** 内置默认。
- **解析**（当进程能 `import _monorepo` 时）：调用 `**_monorepo.resolve_perfetto_config`**：
  - **绝对路径**：文件存在则原样返回。
  - **含 `/` 的相对路径**：相对 **仓库根 `REPO_ROOT`** 解析；可省略 `**.txtpb**` 后缀再试一次。
  - **短名**（无 `/`）：在固定相对目录 `**atrace-capture/atrace_capture/config/perfetto`** 下查找 `**{name}.txtpb**` 或 `**{name}**`。
- 若传入非空但解析失败：**记录告警并回退默认**（与 `atrace-service` 路由行为一致）。

**与 MCP Resource 的关系**：各 `**atrace://configs/*`** URI 与磁盘文件名、用途的对应表在**第 5.3 小节**（避免与本节双写）。读完 Resource 后，可将内容落盘，或在 monorepo 下用 `**capture_trace(perfetto_config="scroll")`** 这类**短名**（由 `**resolve_perfetto_config`** 解析到同目录下的 `.txtpb`）。

**与 `capture_with_preset` 的区别**

- `**capture_trace`**：直接调 `**DeviceController.run_atrace_tool**`，`**perfetto_config**` 为 `**.txtpb` 文件路径或短名**。
- `**capture_with_preset`**：走 `**atrace-capture**` 的 **YAML 预设注册表**（`list_capture_presets`），预设内部可再绑定 Perfetto 模板；与 MCP Resource 的 URI **无强制一一对应**，但语义上常与 `startup` / `scroll` 等场景同类。

**延伸阅读**

- 卡顿与帧预算语义：[../docs/PERFETTO_JANK_GUIDE.md](../docs/PERFETTO_JANK_GUIDE.md)

### 5.7 统一场景总表（口语场景 · Prompt · Tools · Perfetto · CLI）

**一张表收齐**：口语化场景名、**MCP Prompt**（与 `prompts.py` 函数名一致）、**主要 Tools 顺序**（与内置 Prompt 编排一致；采集类含设备扁平工具）、**Perfetto / Resource**（自定义系统 trace 时可读 URI 或 `perfetto_config` 短名；**仅分析已有文件时不必改配置**）、**无 MCP 时 CLI 快照**（详见 [`ATRACE_PLATFORM_CLI.md`](../docs/ATRACE_PLATFORM_CLI.md)）。

| 口语场景 / 入口 | 目标 | MCP Prompt（中 / 英） | 主要 MCP Tools（顺序意涵） | 相关 Perfetto Resource（可选） | CLI（无 MCP） |
| --- | --- | --- | --- | --- | --- |
| **场景入口（中文）** | 不知道选哪个 | `platform_hub_zh` | （元）列出下游 Prompt | `atrace://configs/index` | — |
| **通用体检** | 总览 + 帧 + jank + Top + 下钻 | `cn_standard_review` / `analyze_trace` | `load_trace` → `trace_overview` → `analyze_scroll_performance` → `analyze_jank` → `execute_sql` → `slice_children` / `call_chain` | `scroll` + `animation`（读内容辅助定配置） | `atrace-analyze bundle -p <pkg>` |
| **冷启动（已有文件）** | 启动阶段与阻塞 | `cn_standard_startup` / `startup_analysis` | `load_trace` → `trace_overview` → `analyze_startup` → `slice_children` / `call_chain` | `startup` | `atrace-analyze startup -p <pkg>` |
| **卡顿 / 长帧（已有文件）** | 帧质量 + jank + 最重帧 | `cn_standard_jank` / `jank_analysis` | `load_trace` → `analyze_scroll_performance` → `analyze_jank` → 下钻 | `scroll`、`animation` | `atrace-analyze jank` + `scroll` |
| **主线程阻塞** | Binder/Lock/GC/IO | `cn_standard_blocking` / `blocking_analysis` | `load_trace` → `execute_sql` → `thread_states` → `slice_children` / `call_chain` | `binder`、`memory`（GC） | `atrace-analyze top-slices` + `sql` |
| **冷启动采集 + 分析** | 设备上采冷启 trace 再分析 | `cn_standard_cold_start_capture` | `list_devices` → `query_app_status` → `capture_trace(cold_start=True)` → `load_trace` → `trace_overview` → `analyze_startup` → `analyze_jank` | `startup`（`perfetto_config="startup"`） | `atrace-tool` + `atrace-analyze` |
| **滑动采集 + 分析** | 当前页自动滑并看帧 | `scroll_performance_workflow` | 可选 `list_devices`、`query_app_status` → `capture_trace(inject_scroll=True)` 或跳过 → `load_trace` → `trace_overview` → `analyze_jank` → `query_slices` / `execute_sql` / 下钻；可选 `trace_viewer_hint` | `scroll`（`perfetto_config="scroll"`） | 采集：`atrace-tool`/MCP；分析：`atrace-analyze` |
| **快速扫一眼** | 多进程 / 规模 | `quick_health_check` | `load_trace` → `trace_overview` | — | `atrace-analyze overview` |
| **智能采集** | 按意图选插件 / 采样再采 | `smart_capture` | `list_devices` → `query_app_status` → `list_plugins` → 调插件/采样 → `capture_trace`（按 scenario 选 `cold_start` / `inject_scroll`） | 按场景选 `startup` / `scroll` 等 | — |
| **迭代诊断** | 假设—改配置—复采验证 | `iterative_diagnosis` | 首轮：`load_trace` + `analyze_*` / SQL；后续：`toggle_plugin`、`set_sampling_interval`、`add_trace_mark`、`capture_trace` 再加载新文件验证 | 随症状切换 `binder` / `memory` 等 | — |
| **插件与采样实验** | 调插件与采样对比 | `plugin_tuning` | `query_app_status` → `list_plugins` → `get_sampling_config` → 多轮 `toggle_plugin` + 短 `capture_trace` 对比 | 按需读 `atrace://configs/readme` | — |
| **自由提问** | 自定义问题深挖 | `explore_issue` | `load_trace` 后按 `question` 在 `execute_sql` / `query_slices` / `analyze_*` / 下钻间迭代 | `atrace://perfetto-sql-reference`、`atrace://sql-patterns` | `atrace-analyze sql -e "..."` |

**说明**：同一 Prompt 在 **第 5.4 节** 有参数说明；**第 6.1 节** 为「说法 → Prompt」速查；话术与报告模板见 **第 6.3、6.4 节**。

---

## 6. 平台能力：场景编排 · 话术 · 报告 · 与第 5 节的分工

- **第 5 节**：工具 / Resource / Prompt **注册清单**、`payload_json` 约定、**Prompt 编排**、`**perfetto_config`**、**统一场景总表（第 5.7 节）** — 以代码为准的「手册」。
- **本节**：**下钻速查**、**可复制到 Cursor 的对话模板**、**分析报告全文模板**；场景与 Prompt、Tools、Perfetto、CLI 的**完整对照仅维护一份**，见 **第 5.7 节**。与 `**prompts.py**`、**`docs/ATRACE_MCP_DEMO_SCENARIOS.md`** 互补。

**相关**：无 MCP 时用 **[../docs/ATRACE_PLATFORM_CLI.md](../docs/ATRACE_PLATFORM_CLI.md)** 的 **`atrace-analyze`**；工程分层见 **[../docs/ATRACE_ENGINEERING_GUIDE.md](../docs/ATRACE_ENGINEERING_GUIDE.md)**。

**注意**：同一 MCP 会话内 **尽量串行** 调用分析类工具，避免 Trace Processor 并发错误（见工程指南 第 4.5 节）。

### 6.0 平台提供的三件事

| 能力 | 说明 |
|------|------|
| **场景编排** | 每个场景约定 **工具调用顺序**（采集 → 加载 → 预置分析 → 可选 SQL/下钻），减少「下一步该调什么」的决策成本。 |
| **工具调用与下钻** | 预置分析出结论后，用 **`slice_children` / `call_chain` / `execute_sql` / `query_slices`** 按证据链继续下钻。 |
| **AI 话术 + 报告** | **话术**：对话里粘贴即可触发模型按步骤走 MCP；**报告**：用 第 6.4 节 模板归档，便于 PR/工单/版本对比。 |

**下钻工具速查**

| 情况 | 工具 |
|------|------|
| 看某 slice 内部耗时分布 | `slice_children(slice_id, limit)` |
| 看调用栈祖先链 | `call_chain(slice_id)` |
| 自定义过滤 | `execute_sql` / `query_slices` |
| 主线程 CPU/调度语义 | `thread_states`（或 SQL `thread_state`） |

### 6.1 场景 → Prompt（完整对照见 第 5.7 节）


| 用户场景（说法）         | 在 Cursor MCP Prompts 中选                              |
| ---------------- | ---------------------------------------------------- |
| 不知道选哪个（中文入口）     | `**platform_hub_zh`**                                |
| 已有文件，全面体检        | `**cn_standard_review**` 或英文 `**analyze_trace**`     |
| 已有文件，冷启动         | `**cn_standard_startup**` / `**startup_analysis**`   |
| 已有文件，滑动 / 帧 / 卡顿 | `**cn_standard_jank**` / `**jank_analysis**`         |
| 已有文件，主线程阻塞归因     | `**cn_standard_blocking**` / `**blocking_analysis**` |
| 设备上冷启采集再分析       | `**cn_standard_cold_start_capture**`                 |
| 当前页滑动采集再分析       | `**scroll_performance_workflow**`                    |
| 快速看规模与进程         | `**quick_health_check**`                             |
| 按意图调插件再采         | `**smart_capture**`                                  |
| 假设—改配置—复采        | `**iterative_diagnosis**`                            |
| 调插件与采样实验         | `**plugin_tuning**`                                  |
| 带着具体问题深挖         | `**explore_issue**`                                  |


**推荐工具链**：上表选定 Prompt 后，模型应遵循的具体 `**load_trace` → …** 顺序、Perfetto 资源与 **CLI** 对照见 **第 5.7 节 统一场景总表**。

### 6.2 下钻与帧预算（第 5.2 小节的补充）

`**slice_id` / `thread_name` / `sql` / `process` 等键与示例**：**第 5.2 小节**。

**分析习惯（不重复字段表）**：先 `**load_trace`**，再总览与 `**analyze_***`；下钻优先用工具返回里的 `**slice_id**`，否则用 SQL 查 `slice.id`。高刷设备上**勿把帧预算默认成 16.6ms**，见 **[../docs/PERFETTO_JANK_GUIDE.md](../docs/PERFETTO_JANK_GUIDE.md)**。

### 6.3 AI 话术（粘贴到 Cursor 对话框）

将 `<TRACE>`、`<PACKAGE>` 换成实际路径与包名。若已配置 **atrace MCP**，模型应 **按顺序调用工具**，不要并行分析工具。

**推荐**：优先在 Cursor **MCP → Prompts** 中选内置 Prompt（名称与 **`prompts.py`** 函数名一致，全量见 **第 5.4 节**），将生成文本整段贴回对话；与下表等价。

在 Cursor **MCP Prompts** 中常用：

- **`platform_hub_zh`**：无参，先发场景总表。  
- **`cn_standard_review`** / **`cn_standard_startup`** / **`cn_standard_jank`** / **`cn_standard_blocking`**：已有 trace 的 **中文标准编排**。  
- **`cn_standard_cold_start_capture`**：设备上 **冷启动采集 + 分析**。  
- **`scroll_performance_workflow`**：当前页 **滑动** 端到端（含 `inject_scroll`）。  
- **`startup_analysis`** / **`jank_analysis`** / **`blocking_analysis`**：英文步骤 + 更详 SQL。  

#### 6.3.1 通用分析（无 Prompt 面板时）

```
请使用 atrace MCP 分析性能轨迹：
- trace 路径：<TRACE>
- 包名：<PACKAGE>

步骤：1) load_trace  2) trace_overview  3) analyze_scroll_performance（若 trace 含滑动/帧）
4) analyze_jank  5) 对最严重的 doFrame 或长 slice 用 slice_children 下钻
最后按「分析报告模板」（本文 第 6.4 节）输出结构化结论（证据含 slice 名与耗时）。
```

#### 6.3.2 冷启动

```
请使用 atrace MCP 做冷启动分析：trace=<TRACE>，进程=<PACKAGE>。
顺序：load_trace → analyze_startup → 对 blocking_calls 与 bindApplication 相关 slice 做 slice_children / call_chain。
输出：分阶段耗时表 + Top 阻塞 + 优化优先级。
```

#### 6.3.3 滑动 / 卡顿（仅分析已有文件）

```
请使用 atrace MCP：load_trace(<TRACE>, <PACKAGE>) → analyze_scroll_performance → analyze_jank。
结合 verdict（no_jank_pct、buffer_stuffing、self_jank）说明帧质量；对 worst_frames 对应时间段用 slice_children 下钻到 animation/RV/onBind 等。
```

#### 6.3.4 一条通用话术（占位符最少）

```
请使用 ATrace MCP，按工具注册名串行调用（Trace 类工具勿并行）。
trace：<TRACE>，目标包名子串：<PACKAGE>。
1) load_trace：payload_json 含 "trace_path"、"process_name"（可与包名一致）
2) trace_overview → 按需 analyze_scroll_performance / analyze_jank / analyze_startup（payload_json 里进程过滤键为 "process"）
3) 对可疑长 slice：slice_children / call_chain（"slice_id" 必填）
参数与键名以第 5.2 小节为准；输出含证据（slice 名、ms、slice_id）。
```

### 6.4 分析报告模板（归档 / PR / 工单）

复制下面 Markdown，填完后随 trace 路径或附件一并提交。

```markdown
# 性能分析报告

## 1. 元信息
| 字段 | 内容 |
|------|------|
| 分析日期 | YYYY-MM-DD |
| 业务 / 版本 | |
| 包名 | |
| 场景 | 冷启动 / 滑动 / 某页面 / 其他：___ |
| Trace 文件 | `路径或对象存储链接` |
| 采集方式 | capture_trace 参数摘要 / 手工 adb / 其他 |
| 分析入口 | Cursor+MCP / atrace-analyze CLI / 混合 |

## 2. 摘要（给管理者 / 排期）
- **结论一句话**：
- **是否阻塞发版 / 合入**：是 / 否 / 待复现
- **优先级最高的 1～3 项**：

## 3. 数据证据
### 3.1 结构化指标（从 analyze_scroll_performance / analyze_startup / analyze_jank 摘录）
- 帧质量 / verdict（如有）：
- 主线程 Top slice（如有）：
- 阻塞类调用（如有）：

### 3.2 关键 slice / 帧（含 slice_id 或 ts 便于 UI 对齐）
| 名称 | 耗时(ms) | slice_id / 说明 |
|------|----------|------------------|
| | | |

## 4. 根因分析
（按证据链写：现象 → 对应代码或模块推测 → 置信度）

## 5. 建议与后续
| 建议 | 预期收益 | 负责人 / 排期 |
|------|----------|----------------|
| | | |

## 6. 复现与对比
- 复现步骤：
- 基线对比（若有）：旧版本指标 vs 当前：

## 7. 附录
- 使用的 MCP 工具列表 / 或 `atrace-analyze` 子命令
- Perfetto UI 打开方式（ui.perfetto.dev）
```

---

## 许可证

Apache-2.0（与仓库根 **TraceMind** 保持一致）。