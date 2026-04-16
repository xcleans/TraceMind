# ATrace MCP 效果样例（基于 MCP 的轨迹分析自动化）

本文说明如何在 **Cursor** 中通过 **`atrace-mcp`** 完成 **轨迹采集与分析自动化**：以对话编排 **增强采集（ATrace SDK + MCP 侧合并实现）→ 加载 → 预置分析 / 自定义 SQL**，使 **系统 Perfetto** 与 **应用侧 ATrace 数据** 在同一时间轴对齐，并由模型 **辅助选用工具、迭代查询与归纳结论**。文内给出 **可复现参数、示例输出量级及解读要点**（包名与路径请按本地环境替换）。

**参考**：[atrace-mcp/README.md](../platform/atrace-mcp/README.md)（含 **第 6 节** 场景编排 · 话术 · 报告模板）、根目录 [README.md](../README.md)（「Cursor MCP：AI 辅助下的轨迹分析」一节）

---

## 0. 自动化分析能力概览

| 能力 | 说明 |
|------|------|
| **合并 trace** | 一次 `capture_trace` 得到 **系统侧 + 应用侧** 单一 `.perfetto`，便于 AI 用 `execute_sql` / `analyze_*` 跨层关联（binder、帧、主线程 slice、应用栈等）。 |
| **结构化结论** | `analyze_startup`、`analyze_jank` 等把常见 PerfettoSQL 固化成 JSON/表，适合直接贴进对话里做**回归对比**或**写进报告**。 |
| **按需下钻** | 在对话里追加「锁竞争 / 某 Activity / 某进程」等，`execute_sql` 迭代；大文件若 MCP 单次超时，可用文内 **本地 TraceAnalyzer** 命令等价执行。 |
| **人工校验** | 同一文件用 [Perfetto UI](https://ui.perfetto.dev) 打开，对照时间轴与 AI 结论。 |

**前置**：设备 ADB；应用已集成 **ATrace SDK**；按文档执行 **`./gradlew deployMcp`**（或等价方式）使 MCP 具备 **合并采集** 所需 JAR；被测进程可按场景冷启。

---

## 1. 冷启动抓取与分析

### 效果说明（本样例 trace 上可验证）

- 区分 **主进程** 与 **`:plugin1` 等多进程**：`bindApplication` / DEX 耗时一眼可见。  
- 主线程 **首屏**：`Choreographer#doFrame`、`RV OnLayout` 等与 **`WelcomeActivity` 生命周期** 可对齐。  
- 合并 trace 中 **slice 规模大**（数十万级）时，优先看 `blocking_calls` / 主线程 SQL Top，再下钻。

### `capture_trace`

| 参数 | 值 |
|------|-----|
| `package` | `com.qiyi.video` |
| `cold_start` | `true` |
| `duration_seconds` | `20` |
| `output_dir` | `/tmp/atrace_qiyi_coldstart` |

### 后续工具（建议同一会话内顺序调用，避免并行）

`load_trace` → `trace_path` = 返回的 `merged_trace`  
`trace_overview` → `trace_path`  
`analyze_startup` → `trace_path`, `process` = `com.qiyi.video`

### 抓取返回（示例）

- `status`: `success`
- `method`: `atrace-tool (Perfetto system trace + ATrace app sampling merged)`
- `merged_trace`: `/tmp/atrace_qiyi_coldstart/com.qiyi.video_1775031624.perfetto`
- `size_kb`: ~65631
- `overview.duration_ms`: ~10073
- `overview.total_slices`: ~405923
- `overview.total_threads`: ~3290

### `analyze_startup` / 等价 SQL 主线程 Top（示例数值）

| 进程 | 切片 | 耗时 (ms) |
|------|------|-----------|
| `com.qiyi.video:plugin1` | `bindApplication` | ~2480 |
| `com.qiyi.video` | `bindApplication` | ~1133 |
| `com.qiyi.video:plugin1` | `makeApplication` | ~1071 |
| `com.qiyi.video:plugin1` | `OpenDexFilesFromOat` / `Open dex file` | ~979 |
| `com.qiyi.video` | `OpenDexFilesFromOat` / `Open dex file` | ~565 |
| `com.qiyi.video` | `makeApplication` | ~280 |
| `com.qiyi.video` | `Choreographer#doFrame` + `traversal` + `layout` + `RV OnLayout` | ~550–1173 |
| `com.qiyi.video` | `performCreate:com.qiyi.video.WelcomeActivity` | ~93 |
| `com.qiyi.video` | `performResume` / `activityResume` | ~118–139 |

### 大文件分析（MCP 超时备用）

```bash
cd atrace-mcp && uv run python -c "
from trace_analyzer import TraceAnalyzer
import json
p = '/path/to/file.perfetto'
a = TraceAnalyzer()
a.load(p, 'com.qiyi.video')
print(json.dumps(a.analyze_startup(p, 'com.qiyi.video'), indent=2, default=str))
a.close(p)
"
```

---

## 2. 锁竞争（`execute_sql`）

### 效果说明（本样例 trace 上可验证）

- **主线程**：`monitor contention` 可定位 **`nativeLoad` 串行**、**WebView 初始化**、**预加载线程与 inflate 抢锁** 等百毫秒级问题。  
- **后台线程**：`pthread mutex`、Camera / OkHttp / MessageQueue 等争用，用于解释「启动期 CPU 忙但 UI 卡点不在主线程」类现象。  
- 与 **第 1 节 冷启动** 对照：DEX / Application 阶段与锁等待时间戳对齐，便于判断优化优先级。

### SQL：主线程 monitor / Lock（`dur >= 3ms`）

```sql
SELECT
  pr.name AS process,
  t.name AS thread,
  ROUND(s.dur/1e6, 3) AS dur_ms,
  s.name
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process pr ON t.upid = pr.upid
WHERE pr.name LIKE '%com.qiyi.video%'
  AND t.is_main_thread = 1
  AND s.dur >= 3000000
  AND (s.name LIKE 'monitor contention%' OR s.name LIKE 'Lock contention%')
ORDER BY s.dur DESC
LIMIT 30;
```

### SQL：全进程锁相关 Top（`dur >= 1ms`）

```sql
SELECT pr.name AS process, t.name AS thread, t.is_main_thread AS main,
       s.name, ROUND(s.dur/1e6, 3) AS dur_ms
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process pr ON t.upid = pr.upid
WHERE pr.name LIKE '%com.qiyi.video%'
  AND s.dur >= 1000000
  AND (
    s.name LIKE '%contention%'
    OR s.name LIKE '%pthread mutex%'
    OR s.name LIKE 'Contending for pthread mutex%'
  )
ORDER BY s.dur DESC
LIMIT 40;
```

### 样例输出（同 trace）

| 指标 | 值 |
|------|-----|
| `com.qiyi.video`：`Lock contention` 次数（≥0.5ms） | ~736，累计 ~6257 ms |
| `com.qiyi.video`：`pthread mutex` 次数（≥0.5ms） | ~895，累计 ~5957 ms，单次最大 ~430 ms |
| `com.qiyi.video`：`monitor contention` 次数（≥0.5ms） | ~247，累计 ~3522 ms |
| 主线程：`Runtime.nativeLoad` / owner `csj_l_4::init sync` | ~106 ms |
| 主线程：WebView `onServiceConnected` / `GoogleApiHandler` | ~76 ms |
| 主线程：`CardViewPreload` vs `LayoutInflater.inflate` | ~10–48 ms（多次） |

---

## 3. Perfetto UI（对照校验）

`https://ui.perfetto.dev` → Open trace file → 上述 `.perfetto`

用于核对 **帧时间线、CPU、主线程 slice** 与 MCP / SQL 结论是否一致。
