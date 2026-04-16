"""
ATrace MCP Server — AI Prompt templates.

Provides structured prompts that guide LLM to perform
systematic Android performance analysis.
"""

from fastmcp import FastMCP


def register_prompts(mcp: FastMCP):

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 0. Cursor 标准编排（中文）— 与 platform/atrace-mcp/README.md 第 6 节对齐
    #    供 Cursor MCP Prompts 面板直接选用；工具须串行调用（勿并行 analyze_*）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @mcp.prompt
    def platform_hub_zh() -> str:
        """Cursor 内场景入口：标准编排 Prompt 一览（中文说明）。

        无参数。在 Cursor → MCP → Prompts 中选本项，将本段发给模型即可。
        """
        return """# TraceMind / ATrace — Cursor 标准编排入口（中文）

你是 **ATrace MCP** 助手。以下为仓库内 **已注册的标准编排 Prompt**（名称 = 函数名，在 Cursor **MCP Prompts** 中选用并填参）。

## 选用表

| 场景 | Prompt 名 | 必填参数 | 说明 |
|------|-----------|----------|------|
| **已有 trace，标准体检** | `cn_standard_review` | trace_path, process_name | 总览 → 帧质量 → 卡顿 → 主线程 Top → 下钻 |
| **已有 trace，冷启动** | `cn_standard_startup` | trace_path, process_name | analyze_startup + 阻塞下钻 |
| **已有 trace，滑动/卡顿/帧** | `cn_standard_jank` | trace_path, process_name | analyze_scroll_performance + analyze_jank + 最重帧下钻 |
| **已有 trace，主线程阻塞** | `cn_standard_blocking` | trace_path, process_name | Binder/Lock/GC/IO 归因 + thread_states |
| **冷启动：采集 + 分析** | `cn_standard_cold_start_capture` | package | list_devices → capture_trace(cold_start) → startup + jank |
| **滑动：当前页采集 + 分析** | `scroll_performance_workflow` | package | 见英文 Prompt（inject_scroll）；已有文件可传 trace_path |
| **自由提问** | `explore_issue` | trace_path, process_name, question | 单点深挖 |
| **迭代诊断** | `iterative_diagnosis` | trace_path, process_name, symptom | 观测→假设→复采 |

**英文等价**：`analyze_trace`、`startup_analysis`、`jank_analysis`、`blocking_analysis` 与上表逻辑相近，可按团队语言习惯选用。

## 硬性规则

1. **`load_trace` 之后** 的 `trace_overview`、`analyze_*`、`execute_sql` 等 **必须串行**（同一会话内不要并行调用多个会走 Trace Processor 的工具）。
2. 工具名以 MCP 注册为准：`load_trace`、`trace_overview`、`analyze_scroll_performance`、`analyze_jank`、`analyze_startup`、`slice_children`、`call_chain`、`execute_sql`、`query_slices`、`open_trace_in_perfetto_browser`、`thread_states`、`capture_trace` 等。
3. 文档：**`platform/atrace-mcp/README.md` 第 6 节**（话术与报告模板）、**`docs/ATRACE_PLATFORM_CLI.md`**（无 MCP 时用 `atrace-analyze`）。

## MCP 工具入参（与当前服务器一致）

- **Trace / 查询类**（`load_trace`、`trace_overview`、`analyze_*`、`query_slices`、`execute_sql`、`slice_children`、`call_chain`、`thread_states`、`open_trace_in_perfetto_browser`）使用 **单一参数 `payload_json`**：其值为 **JSON 对象的字符串**（服务端 `json.loads`）。路径或 SQL 中的双引号需按 JSON 转义。
- **字段约定**：
  - `load_trace`：`trace_path`（在无法从会话 / env 推断时必填）、`process_name`（可选）
  - `analyze_startup` / `analyze_jank` / `analyze_scroll_performance`：`process`（进程名子串；**不要**写 `process_name`）；`analyze_scroll_performance` 还可选 `layer_name_hint`
  - `execute_sql`：**`sql` 必填**；`trace_path` 建议与分析目标一致
  - `slice_children`：**`slice_id` 必填**；可选 `limit`（默认 20）
  - `call_chain`：**`slice_id` 必填**
  - `thread_states`：**`thread_name` 必填**（`thread.name` 子串）；可选 `ts_start` / `ts_end`（纳秒）
- **设备控制类**（`capture_trace`、`query_app_status`、`toggle_plugin` 等）仍为 **扁平具名参数**，以各工具 schema 为准。

若用户尚未说明场景，先问：**已有 trace 路径 + 包名**，还是 **需要现场采集**，再选用上表 Prompt。"""

    @mcp.prompt
    def cn_standard_review(trace_path: str, process_name: str) -> str:
        """标准体检编排（中文）：已有 .perfetto，总览 + 帧 + 卡顿 + 主线程 Top + 下钻。

        Cursor：选本 Prompt，填写 trace_path 与 process_name（包名）。
        """
        return f"""# 标准编排：性能体检（已有 trace）

**轨迹文件**：`{trace_path}`  
**目标进程**：`{process_name}`

请严格按顺序 **串行** 调用 MCP 工具（不要并行）：

## 步骤 1 — 加载与总览
1. `load_trace`：`payload_json` 为 JSON 字符串，例如：
   `{{"trace_path":"{trace_path}","process_name":"{process_name}"}}`
2. `trace_overview`：`payload_json` 例如 `{{"trace_path":"{trace_path}"}}` — 记录时长、slice 规模、进程列表。

## 步骤 2 — 帧与卡顿（有则看，报错则记录原因）
3. `analyze_scroll_performance`：`payload_json` 例如 `{{"trace_path":"{trace_path}","process":"{process_name}"}}`  
   - 若失败或缺少 FrameTimeline，在报告中注明「本 trace 无帧时间线或 API 不满足」，跳过本步结论。
4. `analyze_jank`：`payload_json` 例如 `{{"trace_path":"{trace_path}","process":"{process_name}"}}`

## 步骤 3 — 主线程慢 slice Top
5. `execute_sql`：`payload_json` 必须包含 **`sql`**（PerfettoSQL），并建议包含 **`trace_path`** 与当前文件一致。下方 SQL 作为 `sql` 字段的值（对换行与引号按 JSON 规则转义后再填入）：
```sql
SELECT s.name, s.dur/1e6 AS dur_ms, s.id AS slice_id, s.ts
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%{process_name}%'
  AND t.is_main_thread = 1 AND s.dur > 0
ORDER BY s.dur DESC
LIMIT 20
```

## 步骤 4 — 下钻（选 2～5 个最可疑 slice）
6. 对 **Choreographer#doFrame**、**animation**、**RV Prefetch**、**inflate**、**Binder/Lock** 等，依次 `slice_children`：`payload_json` 例如 `{{"trace_path":"{trace_path}","slice_id":<id>,"limit":200}}`；必要时 `call_chain`：`{{"trace_path":"{trace_path}","slice_id":<id>}}`。

## 步骤 5 — 输出报告（中文）
按项目模板输出：**摘要**、**关键数据**（verdict / jank 条数 / Top slice）、**根因假设**、**优化建议**、**复现信息**（本 trace 路径）。"""

    @mcp.prompt
    def cn_standard_startup(trace_path: str, process_name: str) -> str:
        """冷启动分析编排（中文）：analyze_startup + 下钻阻塞与启动阶段。"""
        return f"""# 标准编排：冷启动分析（已有 trace）

**轨迹**：`{trace_path}`  
**包名**：`{process_name}`

## 串行步骤
1. `load_trace`：`payload_json` 例如 `{{"trace_path":"{trace_path}","process_name":"{process_name}"}}`
2. `trace_overview`：`payload_json` 例如 `{{"trace_path":"{trace_path}"}}`
3. `analyze_startup`：`payload_json` 例如 `{{"trace_path":"{trace_path}","process":"{process_name}"}}` — 保存 `blocking_calls`、`top_main_thread_slices`。
4. 对 **bindApplication**、**OpenDex**、**inflate**、**blocking_calls 前 5 条** 中的 slice，用 `slice_children` / `call_chain` 下钻（有 `slice_id` 时优先用返回中的 id；`payload_json` 含 `trace_path` + `slice_id`，`slice_children` 可加 `limit`）。
5. 若存在多进程（如 `:plugin`），在 SQL 或 `query_slices` 中对比各进程主线程 Top。

## 输出（中文）
- 启动阶段时间线摘要  
- Top 问题与证据（slice 名、ms、slice_id）  
- 阻塞类项与优化优先级  

参考（可选）：同仓库 `startup_analysis` Prompt 内嵌 SQL 可补充执行。"""

    @mcp.prompt
    def cn_standard_jank(trace_path: str, process_name: str) -> str:
        """滑动/卡顿/帧质量编排（中文）：已有 trace，优先 FrameTimeline + jank + 下钻。"""
        return f"""# 标准编排：滑动与帧质量（已有 trace）

**轨迹**：`{trace_path}`  
**包名**：`{process_name}`

## 串行步骤
1. `load_trace`：`payload_json` 例如 `{{"trace_path":"{trace_path}","process_name":"{process_name}"}}`
2. `analyze_scroll_performance`：`payload_json` 例如 `{{"trace_path":"{trace_path}","process":"{process_name}"}}` — 重点 **verdict**、**worst_frames**、**frame_quality**、**blocking_calls**。
3. `analyze_jank`：`payload_json` 例如 `{{"trace_path":"{trace_path}","process":"{process_name}"}}`
4. 取 **worst_frames** 或 **jank_frames** 中 1～3 个最重时刻，对同一时间段内主线程相关 slice 做 `slice_children`（`payload_json`：`trace_path` + `slice_id`；若只有 ts，可用 `execute_sql` 按 ts 窗口查 slice）。
5. 可选：`query_slices`：`payload_json` 例如 `{{"trace_path":"{trace_path}","process":"{process_name}","main_thread_only":true,"min_dur_ms":8,"limit":30}}`

## 输出（中文）
- 帧质量结论（No Jank / Buffer Stuffing / Self Jank 等占比）  
- 最差帧与下钻到的子 slice（animation / traversal / RV 等）  
- 可落地的优化方向（列表/布局/预取/binder 等）  

参考：`jank_analysis` Prompt 内 RenderThread SQL 可作为补充。"""

    @mcp.prompt
    def cn_standard_blocking(trace_path: str, process_name: str) -> str:
        """主线程阻塞归因编排（中文）：Binder/Lock/GC/IO + 调度。"""
        return f"""# 标准编排：主线程阻塞分析（已有 trace）

**轨迹**：`{trace_path}`  
**包名**：`{process_name}`

## 串行步骤
1. `load_trace`：`payload_json` 例如 `{{"trace_path":"{trace_path}","process_name":"{process_name}"}}`
2. `execute_sql`：`payload_json` 含 **`trace_path`** 与 **`sql`**（值为下方 SQL，按 JSON 转义后嵌入）— 主线程上 Binder/Lock/GC/IO/monitor/contention 等长 slice（示例）：
```sql
SELECT s.name, s.dur/1e6 AS dur_ms, s.id AS slice_id, s.ts
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%{process_name}%'
  AND t.is_main_thread = 1 AND s.dur > 2000000
  AND (s.name LIKE '%Binder%' OR s.name LIKE '%Lock%' OR s.name LIKE '%GC%'
       OR s.name LIKE '%IO%' OR s.name LIKE '%Monitor%' OR s.name LIKE '%contention%')
ORDER BY s.dur DESC
LIMIT 25
```
3. `thread_states`：`payload_json` 含 **`thread_name`**（`thread.name` 子串；主线程常见与包名相同或含 `main`，请用 `trace_overview` / SQL 先确认），例如 `{{"trace_path":"{trace_path}","thread_name":"{process_name}"}}`；可选 `ts_start` / `ts_end`（纳秒）。
4. 对最长几条阻塞 slice：`slice_children` / `call_chain` 的 `payload_json` 含 `trace_path` + `slice_id`。

## 输出（中文）
- 阻塞类型分布与最严重实例  
- 是否与锁/跨进程相关  
- 建议（减少主线程同步等待、拆 IO、调整锁粒度等）  

也可直接复用英文 Prompt `blocking_analysis` 中的 SQL 作为补充。"""

    @mcp.prompt
    def cn_standard_cold_start_capture(
        package: str,
        duration_seconds: int = 20,
        serial: str = "",
    ) -> str:
        """冷启动标准编排（中文）：设备采集合并 trace + 启动/卡顿分析。

        需设备已连 ADB、应用已集成 ATrace。填写 package；可选 duration_seconds、serial。
        """
        serial_hint = (
            f"\n多设备时在相关工具上传入 `serial=\"{serial}\"`。\n"
            if serial.strip()
            else ""
        )
        return f"""# 标准编排：冷启动采集 + 分析

**包名**：`{package}`  
**建议采集时长**：{duration_seconds}s{serial_hint}

## Phase A — 采集（串行）
1. `list_devices` — 确认设备在线。
2. `query_app_status` — 确认 ATrace HTTP 可达（必要时端口转发）。
3. `capture_trace(package="{package}", duration_seconds={duration_seconds}, cold_start=True, inject_scroll=False)` — **阻塞直至结束**；从返回 JSON 取 **`merged_trace`** 路径。

## Phase B — 分析（串行，路径用上面的 merged_trace）
4. `load_trace`：`payload_json` 例如 `{{"trace_path":"<粘贴 merged_trace 完整路径>","process_name":"{package}"}}`
5. `trace_overview`：`payload_json` 例如 `{{"trace_path":"<同上 merged_trace>"}}`
6. `analyze_startup`：`payload_json` 例如 `{{"trace_path":"<同上 merged_trace>","process":"{package}"}}`
7. `analyze_jank`：`payload_json` 例如 `{{"trace_path":"<同上 merged_trace>","process":"{package}"}}`
8. 对 **analyze_startup** 中阻塞与慢启动 slice：`slice_children` 的 `payload_json` 含 `trace_path` + `slice_id`。

## 输出（中文）
- 采集参数与 **merged_trace** 路径（便于归档）  
- 启动与首帧问题摘要  
- 下一步优化建议  

**注意**：不要用 `cold_start=True` 做「当前页滑动」场景；滑动请用 `scroll_performance_workflow`。"""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 1. 通用分析入口
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @mcp.prompt
    def analyze_trace(trace_path: str, process_name: str = "", concern: str = "") -> str:
        """Systematic Android trace analysis workflow.

        Args:
            trace_path: Path to the Perfetto trace file
            process_name: Target app process name (e.g. com.example.app)
            concern: What the user is concerned about (e.g. "startup slow", "jank", "ANR")
        """
        return f"""Analyze the Android performance trace at: {trace_path}
Target process: {process_name or "(auto-detect from trace)"}
User concern: {concern or "(general performance review)"}

Follow this systematic workflow:

## MCP tool calling (matches this server)
- `load_trace`, `trace_overview`, `analyze_*`, `query_slices`, `execute_sql`, `slice_children`, `call_chain`, `thread_states`, `open_trace_in_perfetto_browser` each take **one** string argument **`payload_json`**: a JSON **object** as a string (`json.loads` on the server). Escape quotes/newlines inside `sql` per JSON rules.
- **`load_trace`** uses key **`process_name`** (optional default process). **`analyze_startup` / `analyze_jank` / `analyze_scroll_performance` / `query_slices`** use **`process`** (substring), not `process_name`.
- **`execute_sql`** requires **`sql`**. **`slice_children` / `call_chain`** require **`slice_id`**. **`thread_states`** requires **`thread_name`**.
- After `load_trace`, other tools may omit `trace_path` if the session resolves it — still recommend passing `trace_path` for clarity.
- **Serialize** trace tools: do not run multiple trace-processor tools concurrently in one session.

## Step 1: Load and Overview
- `load_trace` with `payload_json` like: `{{"trace_path":"{trace_path}","process_name":"{process_name}"}}` (omit or empty `process_name` only when intentionally auto-detecting).
- `trace_overview` with `payload_json` like: `{{"trace_path":"{trace_path}"}}`
- Identify the target app process if not specified

## Step 2: Main Thread Health Check
Run `execute_sql` with `payload_json` containing `trace_path` and `sql` set to:
```sql
SELECT s.name, s.dur/1e6 AS ms, s.id, s.depth
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%{process_name}%'
  AND t.is_main_thread = 1 AND s.dur > 0
ORDER BY s.dur DESC LIMIT 15
```

## Step 3: Identify Problem Category
Based on the results, determine which category to investigate:
- **Startup**: If slow functions are in onCreate/bindApplication/inflate
- **Jank**: If `Choreographer#doFrame` slices exceed the **device refresh-rate budget** (do not assume 16.6ms on high-refresh devices)
- **Blocking**: If Lock/Binder/GC/IO slices appear on main thread
- **Memory**: If GC pauses are frequent

## Step 4: Deep Dive
For each suspicious slice:
1. `slice_children` with `payload_json` like `{{"trace_path":"{trace_path}","slice_id":<id>,"limit":200}}`
2. `call_chain` with `payload_json` like `{{"trace_path":"{trace_path}","slice_id":<id>}}`
3. `execute_sql` joining `thread_state` / other tables as needed (still via `payload_json`)

## Step 5: Report
Summarize findings with:
- Top 3-5 performance issues ranked by impact
- Root cause for each issue
- Specific optimization suggestions"""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 2. 冷启动分析
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @mcp.prompt
    def startup_analysis(trace_path: str, process_name: str) -> str:
        """Cold startup performance analysis.

        Args:
            trace_path: Path to the Perfetto trace file
            process_name: App process name
        """
        return f"""Analyze the cold startup of {process_name} in trace: {trace_path}

## Step 1: Load trace
- `load_trace` — `payload_json`: `{{"trace_path":"{trace_path}","process_name":"{process_name}"}}`
- `trace_overview` — `payload_json`: `{{"trace_path":"{trace_path}"}}`

## Step 2: Find startup phases
`execute_sql` — `payload_json` with `trace_path` and `sql` =
```sql
SELECT s.name, s.dur/1e6 AS ms, s.id, s.depth, s.ts
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%{process_name}%'
  AND t.is_main_thread = 1
  AND (s.name LIKE '%bindApplication%'
       OR s.name LIKE '%Application%onCreate%'
       OR s.name LIKE '%Activity%onCreate%'
       OR s.name LIKE '%Activity%onResume%'
       OR s.name LIKE '%inflate%'
       OR s.name LIKE '%doFrame%'
       OR s.name LIKE '%ContentProvider%'
       OR s.name LIKE '%activityStart%'
       OR s.name LIKE '%reportFullyDrawn%')
ORDER BY s.ts ASC
```

## Step 3: Identify blocking calls during startup
`execute_sql` — same pattern, `sql` =
```sql
SELECT s.name, s.dur/1e6 AS ms, s.id
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%{process_name}%'
  AND t.is_main_thread = 1
  AND s.dur > 5000000
  AND (s.name LIKE '%Binder%' OR s.name LIKE '%Lock%'
       OR s.name LIKE '%GC%' OR s.name LIKE '%IO%'
       OR s.name LIKE '%dex%' OR s.name LIKE '%class%init%'
       OR s.name LIKE '%SharedPreferences%'
       OR s.name LIKE '%SQLite%' OR s.name LIKE '%openDatabase%'
       OR s.name LIKE '%loadLibrary%' OR s.name LIKE '%dlopen%')
ORDER BY s.dur DESC LIMIT 20
```

## Step 4: Drill down into the slowest phase
For the slowest phase found, `slice_children` — `payload_json`: `{{"trace_path":"{trace_path}","slice_id":<id>,"limit":200}}` (and `call_chain` with the same `slice_id` if needed).

## Step 5: Check thread scheduling during startup
`execute_sql` — `sql` =
```sql
SELECT ts.state,
       SUM(ts.dur)/1e6 AS total_ms,
       COUNT(*) AS count
FROM thread_state ts
JOIN thread t ON ts.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%{process_name}%'
  AND t.is_main_thread = 1 AND ts.dur > 0
GROUP BY ts.state ORDER BY total_ms DESC
```

## Step 6: Report
Output a startup timeline:
```
Process start → bindApplication (Xms)
  → Application.onCreate (Xms)
    → ContentProvider.onCreate (Xms) [if any]
  → Activity.onCreate (Xms)
    → inflate (Xms)
  → Activity.onResume (Xms)
  → First frame (Xms)
Total: Xms
```

Key findings:
- Which phase is the bottleneck?
- Any blocking calls (Binder/IO/Lock) on main thread?
- Is the main thread CPU-bound or IO-blocked?
- Optimization suggestions"""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 3. 卡顿分析
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @mcp.prompt
    def jank_analysis(trace_path: str, process_name: str) -> str:
        """Jank frame detection and root cause analysis.

        Args:
            trace_path: Path to the Perfetto trace file
            process_name: App process name
        """
        return f"""Detect and analyze jank frames for {process_name} in trace: {trace_path}

## Step 1: Load trace
- `load_trace` — `payload_json`: `{{"trace_path":"{trace_path}","process_name":"{process_name}"}}`
- (Recommended) `analyze_scroll_performance` / `analyze_jank` — `payload_json`: `{{"trace_path":"{trace_path}","process":"{process_name}"}}` (uses **`process`**, not `process_name`)

## Step 2: Find heavy `Choreographer#doFrame` slices (SQL threshold example)
Prefer **refresh-rate-aware** budgets in your write-up (60/90/120/144 Hz). The `16600000` ns line below is only a **60 Hz–order example**; adjust `s.dur` cutoff to match the device.
`execute_sql` — `payload_json` with `trace_path` and `sql` =
```sql
SELECT s.name, s.dur/1e6 AS ms, s.id AS slice_id, s.ts
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%{process_name}%'
  AND t.is_main_thread = 1
  AND s.name LIKE 'Choreographer#doFrame%'
  AND s.dur > 16600000
ORDER BY s.dur DESC LIMIT 20
```

## Step 3: For each jank frame, find the root cause
`slice_children` — `payload_json`: `{{"trace_path":"{trace_path}","slice_id":<worst_frame_slice_id>,"limit":200}}` (and `call_chain` with the same `slice_id`). Look for:
- Is it measure/layout/draw that's slow? (traversal)
- Is it animation callback? (animation)
- Is it input handling? (input)

## Step 4: Find main thread blocking during frames
`execute_sql` — `sql` =
```sql
SELECT s.name, s.dur/1e6 AS ms, s.id
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%{process_name}%'
  AND t.is_main_thread = 1
  AND s.dur > 3000000
  AND (s.name LIKE '%Binder%' OR s.name LIKE '%Lock%'
       OR s.name LIKE '%GC%' OR s.name LIKE '%contention%'
       OR s.name LIKE '%inflate%' OR s.name LIKE '%measure%')
ORDER BY s.dur DESC LIMIT 15
```

## Step 5: Check RenderThread
`execute_sql` — `sql` =
```sql
SELECT s.name, s.dur/1e6 AS ms, s.id
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%{process_name}%'
  AND t.name LIKE '%RenderThread%'
  AND s.dur > 8000000
ORDER BY s.dur DESC LIMIT 10
```

## Step 6: Report
For each jank frame:
```
Frame #N: XX.Xms (compare to the correct vsync budget for this device, e.g. 8.33ms @120Hz)
  Root cause: [GC pause / Binder call / complex layout / ...]
  Recommendation: [specific fix]
```

Summary:
- Total jank frames detected
- Most common jank cause
- Optimization priority list"""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 4. 线程阻塞分析
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @mcp.prompt
    def blocking_analysis(trace_path: str, process_name: str) -> str:
        """Main thread blocking / contention analysis.

        Args:
            trace_path: Path to the Perfetto trace file
            process_name: App process name
        """
        return f"""Analyze main thread blocking for {process_name} in trace: {trace_path}

## Step 1: Load trace
- `load_trace` — `payload_json`: `{{"trace_path":"{trace_path}","process_name":"{process_name}"}}`
- `trace_overview` — `payload_json`: `{{"trace_path":"{trace_path}"}}`

## Step 2: Find all blocking calls on main thread
`execute_sql` — `payload_json` with `trace_path` and `sql` =
```sql
SELECT s.name, s.dur/1e6 AS ms, s.id,
       CASE
         WHEN s.name LIKE '%Binder%' THEN 'Binder IPC'
         WHEN s.name LIKE '%Lock%' OR s.name LIKE '%contention%' OR s.name LIKE '%Monitor%' THEN 'Lock'
         WHEN s.name LIKE '%GC%' OR s.name LIKE '%concurrent%' THEN 'GC'
         WHEN s.name LIKE '%IO%' OR s.name LIKE '%read%' OR s.name LIKE '%write%' THEN 'IO'
         WHEN s.name LIKE '%dex%' OR s.name LIKE '%class%' THEN 'ClassLoading'
         WHEN s.name LIKE '%SharedPreferences%' THEN 'SharedPrefs'
         WHEN s.name LIKE '%SQLite%' OR s.name LIKE '%Database%' THEN 'Database'
         WHEN s.name LIKE '%sleep%' OR s.name LIKE '%wait%' OR s.name LIKE '%park%' THEN 'Wait'
         ELSE 'Other'
       END AS category
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%{process_name}%'
  AND t.is_main_thread = 1
  AND s.dur > 1000000
  AND (s.name LIKE '%Binder%' OR s.name LIKE '%Lock%'
       OR s.name LIKE '%GC%' OR s.name LIKE '%IO%'
       OR s.name LIKE '%contention%' OR s.name LIKE '%Monitor%'
       OR s.name LIKE '%dex%' OR s.name LIKE '%class%init%'
       OR s.name LIKE '%SharedPreferences%'
       OR s.name LIKE '%SQLite%' OR s.name LIKE '%Database%'
       OR s.name LIKE '%sleep%' OR s.name LIKE '%wait%'
       OR s.name LIKE '%park%' OR s.name LIKE '%dlopen%')
ORDER BY s.dur DESC LIMIT 30
```

## Step 3: Aggregate by category
`execute_sql` — `sql` =
```sql
SELECT
  CASE
    WHEN s.name LIKE '%Binder%' THEN 'Binder IPC'
    WHEN s.name LIKE '%Lock%' OR s.name LIKE '%contention%' THEN 'Lock Contention'
    WHEN s.name LIKE '%GC%' THEN 'GC'
    WHEN s.name LIKE '%IO%' OR s.name LIKE '%read%' OR s.name LIKE '%write%' THEN 'IO'
    ELSE 'Other'
  END AS category,
  COUNT(*) AS count,
  SUM(s.dur)/1e6 AS total_ms,
  MAX(s.dur)/1e6 AS max_ms,
  AVG(s.dur)/1e6 AS avg_ms
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%{process_name}%'
  AND t.is_main_thread = 1 AND s.dur > 1000000
  AND (s.name LIKE '%Binder%' OR s.name LIKE '%Lock%'
       OR s.name LIKE '%GC%' OR s.name LIKE '%IO%'
       OR s.name LIKE '%contention%')
GROUP BY category ORDER BY total_ms DESC
```

## Step 4: For the worst blockers, trace the call chain
`call_chain` — `payload_json`: `{{"trace_path":"{trace_path}","slice_id":<id>}}` for each top blocker `id`.

## Step 5: Check main thread state distribution
`thread_states` — `payload_json`: `{{"trace_path":"{trace_path}","thread_name":"<main_thread_name_substring>"}}` (discover `thread.name` via SQL/`trace_overview`; it is often the package name or contains `main`).

## Step 6: Report
```
Main Thread Blocking Summary:
  Total blocking time: XXms out of XXms trace duration (XX%)

  By category:
    Binder IPC:       XXms (N calls, max XXms)
    Lock Contention:  XXms (N calls, max XXms)
    GC:               XXms (N calls, max XXms)
    IO:               XXms (N calls, max XXms)

  Top 5 individual blockers:
    1. [name] - XXms - [recommendation]
    2. ...
```"""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 5. 快速健康检查
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @mcp.prompt
    def quick_health_check(trace_path: str) -> str:
        """Quick overall health check of a trace.

        Args:
            trace_path: Path to the Perfetto trace file
        """
        return f"""Perform a quick health check on trace: {trace_path}

## Step 1: Load and overview
- `load_trace` — `payload_json`: `{{"trace_path":"{trace_path}"}}` (add `"process_name":"..."` when known)
- `trace_overview` — `payload_json`: `{{"trace_path":"{trace_path}"}}`
Note the duration, process count, slice count.

## Step 2: Find the user-facing app
`execute_sql` — `payload_json` with `trace_path` and `sql` =
```sql
SELECT p.name, p.pid,
       COUNT(s.id) AS slice_count,
       SUM(CASE WHEN t.is_main_thread = 1 THEN 1 ELSE 0 END) AS main_slices
FROM process p
JOIN thread t ON t.upid = p.upid
JOIN thread_track tt ON tt.utid = t.utid
JOIN slice s ON s.track_id = tt.id
WHERE p.name LIKE 'com.%'
  AND p.name NOT LIKE 'com.android.%'
  AND p.name NOT LIKE 'com.google.%'
  AND p.name NOT LIKE 'com.qualcomm.%'
  AND p.name NOT LIKE 'com.qti.%'
  AND p.name NOT LIKE 'com.miui.%'
  AND p.name NOT LIKE 'com.xiaomi.%'
GROUP BY p.name ORDER BY slice_count DESC LIMIT 5
```

## Step 3: Run checks (serialize trace tools)
For each app found, **one tool at a time** (same session: no parallel `analyze_*` / `execute_sql`):

a) **Jank check**: `analyze_jank` — `payload_json`: `{{"trace_path":"{trace_path}","process":"<app_process_substring>"}}` (or SQL on `Choreographer#doFrame` with a refresh-rate-aware threshold)
b) **Blocking check**: `execute_sql` for Binder/Lock/GC > 5ms on main thread
c) **Main thread health**: `thread_states` — `payload_json`: `{{"trace_path":"{trace_path}","thread_name":"<main_thread_name>"}}`

## Step 4: One-page summary
```
Health Report for [trace_path]
Duration: X.Xs | Processes: N | Slices: N

App: [name]
  ✅/⚠️/❌ Frame performance: N jank frames (worst: Xms)
  ✅/⚠️/❌ Main thread blocking: Xms total (Binder/Lock/GC/IO)
  ✅/⚠️/❌ Thread scheduling: X% Running, X% Sleeping, X% Blocked

Recommendations (if any):
  1. ...
  2. ...
```

Use ✅ for good, ⚠️ for warning, ❌ for critical."""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 6. 运行时控制 — 智能抓取
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @mcp.prompt
    def smart_capture(package: str, scenario: str = "general", duration: int = 10) -> str:
        """AI-driven smart trace capture with runtime tuning.

        Args:
            package: App package name (e.g. com.example.app)
            scenario: Scenario type: "startup", "scroll", "general", or custom description
            duration: Trace duration in seconds
        """
        return f"""Perform an intelligent trace capture for {package}.
Scenario: {scenario}
Duration: {duration}s

## Step 1: Pre-flight check
1. Call `list_devices` to verify device connectivity
2. Call `query_app_status` to check if ATrace SDK is active
3. Call `list_plugins` to see which hooks are available

## Step 2: Configure for scenario
Based on scenario type "{scenario}", configure plugins and sampling:

**For startup:**
- Enable all plugins: binder, gc, lock, loadlib, io, msgqueue
- Set high-detail sampling: `set_sampling_interval(main_interval_ns=500000, other_interval_ns=2000000, package="{package}")`
- Will use cold_start

**For scroll/jank:**
- Enable: binder, gc, lock, msgqueue
- Disable heavy plugins: alloc, jni (reduce overhead)
- Default sampling: `set_sampling_interval(main_interval_ns=1000000, other_interval_ns=5000000, package="{package}")`
- Will use scroll scenario

**For general:**
- Enable: binder, gc, lock, io, msgqueue
- Default sampling intervals

## Step 3: Capture (tool names and parameters must match the ATrace MCP server)
**Important:** `capture_trace` **blocks** for the whole `duration_seconds`. For scroll/jank on a **page already open**, use **`inject_scroll=True`** so swipes run **inside** the capture window. Do **not** chain `replay_scenario(scroll)` after `capture_trace` in the same session expecting overlap — that fails because the first call does not return until capture ends.

1. Optional mark: `add_trace_mark(name="capture_start_{scenario}", package="{package}")`
2. By scenario:
   - **startup**: `capture_trace(package="{package}", duration_seconds={duration}, cold_start=True, inject_scroll=False)` (add `activity` if needed)
   - **scroll** (list/feed, app already on target screen): `capture_trace(package="{package}", duration_seconds={duration}, cold_start=False, inject_scroll=True, scroll_repeat=8, scroll_dy=600, scroll_start_x=540, scroll_start_y=1200)` — tune coordinates to the device resolution
   - **general**: `capture_trace(package="{package}", duration_seconds={duration}, cold_start=False, inject_scroll=False)` (user may scroll manually while waiting)

## Step 4: Analyze
1. `trace_overview` — `payload_json`: pass the merged trace path when needed (see tool schema)
2. Run quick health check (still **serialize** trace-processor tools)
3. Based on findings, decide if recapture with different settings is needed

## Step 5: Report
Provide capture results and initial findings."""

    @mcp.prompt
    def iterative_diagnosis(
        trace_path: str, process_name: str, symptom: str
    ) -> str:
        """Iterative diagnosis workflow: observe → hypothesize → control → verify.

        Args:
            trace_path: Initial trace file path
            process_name: App process name
            symptom: Observed symptom (e.g. "scroll jank", "slow startup", "ANR")
        """
        return f"""Iterative diagnosis for symptom: "{symptom}"
Process: {process_name}
Initial trace: {trace_path}

## Methodology: Observe → Hypothesize → Control → Verify

### Round 1: Observe
1. `load_trace` — `payload_json`: `{{"trace_path":"{trace_path}","process_name":"{process_name}"}}`
2. Run appropriate analysis (each via `payload_json` on trace tools):
   - For jank: `analyze_jank` — `{{"trace_path":"{trace_path}","process":"{process_name}"}}`
   - For startup: `analyze_startup` — `{{"trace_path":"{trace_path}","process":"{process_name}"}}`
   - General: `query_slices` / `execute_sql` on main-thread top slices
3. Check thread states for scheduling issues (`thread_states` with `thread_name`)
4. Check for blocking calls (Binder/Lock/GC/IO) via `execute_sql`

### Round 2: Hypothesize
Based on observations, form a hypothesis. Examples:
- "Jank is caused by Binder calls on main thread"
- "Startup is slow due to class loading"
- "Lock contention between main and worker threads"

### Round 3: Control (re-capture with targeted config)
Adjust runtime controls to gather more evidence:

**If Binder is suspected:**
```
toggle_plugin("binder", True, package="{process_name}")
set_sampling_interval(main_interval_ns=500000, other_interval_ns=0, package="{process_name}")  # 0 = leave other unchanged
```

**If Lock contention suspected:**
```
toggle_plugin("lock", True, package="{process_name}")
```

**If IO is suspected:**
```
toggle_plugin("io", True, package="{process_name}")
```

Then recapture with marks:
```
add_trace_mark(name="diag_round2_start", package="{process_name}")
capture_trace(package="{process_name}", duration_seconds=10, cold_start=False)
```

### Round 4: Verify
1. Load new trace
2. Check if hypothesis is confirmed
3. If confirmed → report root cause + fix
4. If not → form new hypothesis, go to Round 2

### Output
```
Diagnosis Report for: {symptom}

Round 1 findings: [initial observations]
Hypothesis: [what you think is wrong]
Round 2 config changes: [what plugins/sampling you adjusted]
Round 2 findings: [new evidence]
Root cause: [confirmed cause with trace evidence]
Recommendation: [specific, actionable fix]
```"""

    @mcp.prompt
    def plugin_tuning(package: str) -> str:
        """Guide AI to find optimal plugin configuration for an app.

        Args:
            package: App package name
        """
        return f"""Find the optimal ATrace plugin configuration for {package}.

## Goal
Determine which plugins provide valuable data vs. which add too much overhead,
and find the best sampling interval for this app.

## Step 1: Baseline
1. Check current status: `query_app_status`
2. List current plugins: `list_plugins`
3. Get current sampling config: `get_sampling_config`
4. Capture baseline trace with all default settings: `capture_trace(package="{package}", duration_seconds=5, cold_start=False)`
5. Note: frame times, thread states, buffer usage

## Step 2: Test each plugin individually
For each plugin (binder, gc, lock, jni, loadlib, alloc, msgqueue, io):
1. Disable all other plugins
2. Enable only the test plugin: `toggle_plugin("<plugin_id>", True, package="{package}")`
3. Capture short trace (3s)
4. Measure: does this plugin produce useful data for this app?
5. Note overhead indicators (buffer fill rate, frame drops)

## Step 3: Optimize sampling interval
Test different intervals via `set_sampling_interval` (nanoseconds; `0` means no change for that axis), e.g.:
- High detail: `set_sampling_interval(main_interval_ns=500000, other_interval_ns=2000000, package="{package}")`
- Default-ish: `set_sampling_interval(main_interval_ns=1000000, other_interval_ns=5000000, package="{package}")`
- Low overhead: `set_sampling_interval(main_interval_ns=5000000, other_interval_ns=10000000, package="{package}")`
For each, capture and compare buffer usage and frame impact.

## Step 4: Recommend
```
Optimal Configuration for {package}:
  Plugins: [list of recommended plugins]
  Sampling: main=Xns, other=Xns
  Rationale: [why this config is optimal]
  
  Plugins to avoid: [list with reasons]
  Estimated overhead: ~X%
```"""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 7. 当前页滑动性能 — 采集 + 分析（Cursor / MCP 引导）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @mcp.prompt
    def scroll_performance_workflow(
        package: str,
        duration_seconds: int = 15,
        trace_path: str = "",
        scroll_repeat: int = 8,
        scroll_dy: int = 600,
        scroll_start_x: int = 540,
        scroll_start_y: int = 1200,
        scroll_start_delay_seconds: float = 1.5,
        serial: str = "",
    ) -> str:
        """End-to-end: capture scroll/jank trace (current page open) then analyze with MCP tools.

        Use in Cursor via MCP Prompts, or paste the returned text into the chat so the model
        follows the tool sequence. See atrace-mcp/README.md section on scroll performance.

        Args:
            package: App package name (e.g. com.example.app)
            duration_seconds: Trace length; should cover delay + all swipes + margin (e.g. 12–20)
            trace_path: If non-empty, skip capture and only analyze this merged .perfetto file
            scroll_repeat / scroll_dy / scroll_start_x / scroll_start_y / scroll_start_delay_seconds:
                Passed to `capture_trace` when inject_scroll=True
            serial: ADB serial if multiple devices (empty = default device)
        """
        serial_line = f'Serial: use `serial="{serial}"` on device tools if multiple devices.\n' if serial else ""
        capture_block = f"""## Phase A — Capture (skip if trace already exists)

**Precondition:** User has navigated to the **target scrollable screen** on the device; app is in foreground. **Do not** use `cold_start=True` (that kills the app).

1. `list_devices` — confirm ADB device.
2. `query_app_status` — confirm ATrace HTTP is reachable (port 9090).
3. Optional: `list_plugins` / `toggle_plugin` / `set_sampling_interval` — for scroll, prefer binder+gc+lock+msgqueue; avoid heavy alloc/jni if overhead is high (see project README).
4. Optional: `add_trace_mark(name="scroll_perf_start", package="{package}")` to align time range in the trace.
5. **Main capture** — call **`capture_trace`** exactly once with:
   - `package="{package}"`
   - `duration_seconds={duration_seconds}`
   - `cold_start=False`
   - `inject_scroll=True`
   - `scroll_start_delay_seconds={scroll_start_delay_seconds}`
   - `scroll_repeat={scroll_repeat}`
   - `scroll_dy={scroll_dy}`
   - `scroll_start_x={scroll_start_x}`
   - `scroll_start_y={scroll_start_y}`
   {serial_line.strip()}

   Read the JSON response: **`merged_trace`** is the merged Perfetto path. Confirm **`inject_scroll_meta`** is present when inject_scroll was used.

**Do not** call `replay_scenario(scenario="scroll")` after `capture_trace` expecting the same recording window — `capture_trace` blocks until done. Use **`inject_scroll=True`** for automated swipes inside the window, or `inject_scroll=False` and ask the user to scroll manually during the wait."""

        if trace_path.strip():
            capture_block = f"""## Phase A — Capture

**Skipped:** User supplied existing trace. Path: `{trace_path.strip()}`"""

        load_path_hint = (
            trace_path.strip()
            if trace_path.strip()
            else "the `merged_trace` string from the `capture_trace` JSON response"
        )

        return f"""You are using the **ATrace MCP** server. Follow this workflow exactly; call tools by their registered names.

**Target app package:** `{package}`
{serial_line}
{capture_block}

## Phase B — Load and analyze

Trace/query tools use **`payload_json`**: a JSON **object** serialized to one string (see `platform_hub_zh` / server tool docstrings). **`load_trace`** uses `process_name`; **`analyze_jank` / `analyze_scroll_performance` / `query_slices`** use **`process`** (substring).

1. If not already loaded from capture response, `load_trace` — build `payload_json` as a JSON string: `{{"trace_path":"<PUT_TRACE_FILE_PATH_HERE>","process_name":"{package}"}}`. **Path source:** {load_path_hint}

2. `trace_overview` — `payload_json`: same `trace_path` string as step 1.

3. `analyze_jank` — `payload_json`: `{{"trace_path":"<SAME_PATH_AS_STEP_1>","process":"{package}"}}`

4. Deep dive (pick as needed; **serialize** tool calls):
   - `query_slices` — e.g. `{{"trace_path":"<SAME_PATH>","process":"{package}","main_thread_only":true,"min_dur_ms":5,"limit":50}}`
   - `execute_sql` — `{{"trace_path":"<SAME_PATH>","sql":"<PerfettoSQL escaped per JSON>"}}`
   - `slice_children` / `call_chain` — `{{"trace_path":"<SAME_PATH>","slice_id":<id>}}` (optional `limit` on `slice_children`)

5. Optional: `open_trace_in_perfetto_browser` — `payload_json` with `trace_path` (localhost + ui.perfetto.dev flow), or `trace_viewer_hint` with flat arg `trace_path` for a plain file-open hint.

## Phase C — Report

Output:
- Capture settings used (`inject_scroll`, duration, scroll params or "manual scroll")
- Top jank / frame issues with evidence (slice names, durations)
- Likely root causes (layout, binder, GC, etc.)
- Concrete next steps (code areas to optimize, or recapture with different `scroll_start_x/y`)

**Reference:** Project README — section «场景：当前页滑动性能采集»."""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 8. 自由探索 Prompt
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @mcp.prompt
    def explore_issue(trace_path: str, process_name: str, question: str) -> str:
        """Open-ended performance investigation guided by a specific question.

        Args:
            trace_path: Path to the Perfetto trace file
            process_name: App process name
            question: The specific performance question to investigate
        """
        return f"""Investigate: "{question}"
Trace: {trace_path}
Process: {process_name}

## Approach
You are a performance detective. Use the following tools iteratively:

1. **Start broad**: Use `query_slices` / `execute_sql` / `analyze_*` — all trace tools take **`payload_json`** (JSON object string; see `platform_hub_zh` cheat sheet). **`load_trace`** uses `process_name`; analyzers use **`process`**.
2. **Form hypothesis**: Based on initial data, hypothesize the root cause
3. **Verify**: Use `slice_children`, `call_chain`, or more targeted SQL to confirm
4. **If stuck**: Try different angles:
   - Check thread_states for scheduling issues
   - Look at other threads that might be interacting
   - Search for specific patterns (Binder, Lock, GC, IO)
5. **Iterate**: If first hypothesis is wrong, form a new one

## Available SQL Tables
- `slice`: Function calls (name, dur, ts, track_id, depth, parent_id)
- `thread`: Thread info (utid, tid, name, upid, is_main_thread)
- `process`: Process info (upid, pid, name)
- `thread_track`: Maps tracks to threads
- `thread_state`: Thread scheduling (state: Running/S/D/R, dur, ts)
- `counter`: Time-series metrics (CPU freq, memory)
- `sched`: Kernel scheduling events

## Common Joins
```sql
-- Slice with full context
slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid

-- Thread state with context
thread_state ts
JOIN thread t ON ts.utid = t.utid
```

## Output
Present your findings as:
1. **Investigation steps** (what you looked at and why)
2. **Root cause** (with evidence from the trace data)
3. **Recommendation** (specific, actionable fix)"""
