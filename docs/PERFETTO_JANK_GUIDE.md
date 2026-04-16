# Perfetto 流畅度分析实战指南

> 面向 ATrace 项目团队的完整方法论文档。  
> 配合 [JANK_CHECKLIST.md](./JANK_CHECKLIST.md) 使用，可快速落地到日常排查流程。

---

## 目录

0. [实践说明：四模块关系与分析路径](#0-实践说明四模块关系与分析路径)
1. [核心结论与方法论](#1-核心结论与方法论)
2. [Perfetto 抓取配置详解](#2-perfetto-抓取配置详解)
3. [UI 高效操作与分析主线](#3-ui-高效操作与分析主线)
4. [自定义埋点实战（Trace.beginSection）](#4-自定义埋点实战-tracebeginsection)
5. [常见问题与解释](#5-常见问题与解释)
6. [ATrace 项目落地建议](#6-atrace-项目落地建议)
7. [PerfettoSQL 常用查询模板](#7-perfettosql-常用查询模板)

---

## 0. 实践说明：四模块关系与分析路径

做 **FrameTimeline / 主线程 slice** 类流畅度分析时，建议先弄清 **谁在采数据、谁在合文件、谁在跑 SQL**。下面四块是同一链路的不同层次，不是互相替代关系。

### 0.1 四模块各自做什么

| 模块 | 运行位置 | 与「卡顿 trace」的关系 |
|------|----------|------------------------|
| **`atrace-api`** | App 进程（Jar / AAR） | **对外契约**：`ATrace`、`TraceConfig`、`TracePlugin` 等；**无 Native**。应用只依赖 api 无法单独采样，需配合 **`atrace-core`**。 |
| **`atrace-core`** | App 进程 | **真正产生应用侧轨迹**：栈采样、插件 Hook、`Trace.beginSection` 同类事件写入缓冲区；**HTTP TraceServer**（默认可开）供 PC 启停、下文件；**动态插桩**（WatchList / Art hook）让方法级 slice 进同一套导出格式。流畅度分析里，它解决「应用内细粒度耗时从哪来」。 |
| **`atrace-tool`** | 开发机（JVM Fat JAR） | **采系统 Perfetto**（`record_android_trace` 等）+ **拉取 atrace-core 导出的二进制采样** → 解码合并为 **单个 `.perfetto`**。没有 core 时仍可抓纯系统 trace，但缺少应用方法轨道。 |
| **`atrace-mcp`** | 开发机（Python MCP） | **不跑在手机上**。对已有 `.perfetto`：`load_trace` + `execute_sql` / `analyze_scroll_performance` 等；对设备：通过 **`java -jar atrace-tool … --json`** 调 **`capture_trace`**，并可 **HTTP 控制**已集成 core 的 App。 |

依赖关系简述：**应用集成 `atrace-core`（传递依赖 `atrace-api`）**；**PC 上 `atrace-tool` 负责合并**；**Cursor/Agent 用 `atrace-mcp` 包装 CLI + SQL 分析**。更完整的工程视图见 [ATRACE_ENGINEERING_GUIDE.md](./ATRACE_ENGINEERING_GUIDE.md)。

### 0.2 推荐实践路径（从集成到结论）

1. **被测 App**：依赖 **`atrace-core`**，在 `Application` 中 **`TraceEngineCore.register()`** 后 **`ATrace.init`**；保持 **`enableHttpServer`**（或与 `atrace-tool`/MCP 一致的端口转发），以便 PC 侧拉取采样。滑动/冷启动场景可与本文 **第 2.3、2.5 节** 的配置思路对齐。
2. **采集**：任选其一  
   - **MCP**：对话里调用 `capture_trace(…, inject_scroll=True / cold_start=True)`（底层走 **`atrace-tool capture --json`**）；  
   - **CLI**：`java -jar atrace-tool-*.jar capture -a <包名> -t <秒> -o out.perfetto`。  
   得到 **含 FrameTimeline +（可选）应用 slice** 的合并文件。
3. **分析**：任选其一  
   - **Perfetto UI**（[ui.perfetto.dev](https://ui.perfetto.dev)）：按本文 **第 3 节** 的 SOP 看轨道、对齐主线程与 SF；  
   - **atrace-mcp**：`load_trace` 后 `analyze_scroll_performance`、`query_slices`、`execute_sql`（模板见 **第 7 节**）。  
   Trace Processor 在 MCP 进程内解析；与 **`atrace-tool`** 解耦（tool 只负责产出/合并文件）。
4. **加深业务归因**：在 App 内用 **`Trace.beginSection`**（第 4 节）或 **ATrace WatchList / 动态 hook**（第 6.3 节），让超长帧在时间轴上能对应到具体模块名。

### 0.3 和本文各章怎么对照

| 本文章节 | 模块侧重点 |
|----------|------------|
| **第 2 节** 抓取配置 | 描述的是 **系统侧 Perfetto 数据源**；`atrace-tool` 使用的 config 与这里同一套思想，MCP 可通过参数或自定义 config 传入。 |
| **第 2.5 / 3.4 节** | 直接对应 **`atrace-mcp`** 工具名；底层采集仍依赖设备 +（建议）**`atrace-core` HTTP** + **`atrace-tool` JAR**。 |
| **第 4 节** | 系统 `android.os.Trace`；与 **`atrace-core`** 导出的 slice 可在同一 trace 时间轴对齐。 |
| **第 6.3 节** | **`atrace-core`** 的 ART 插桩与运行时控制，与 FrameTimeline 联合作归因。 |

---

## 1. 核心结论与方法论

### 1.1 为什么首选 Perfetto

| 维度 | Perfetto | Systrace（旧） |
|------|----------|--------------|
| 时间精度 | 纳秒级 | 毫秒级 |
| 帧时间线 | FrameTimeline（actual/expected 双轨） | 无 |
| 查询能力 | PerfettoSQL（类 SQL） | 无内置查询 |
| 采集灵活性 | 文本 proto config，按需组合 | 命令行 flag |
| 生态 | Perfetto UI / Android Studio / atrace-mcp | 旧版 catapult |

**关键认知**：流畅度分析的价值不在"会抓 trace"，而在于建立稳定的**定位流程**：

```
帧异常（FrameTimeline 超预算）
  → 对齐 MainThread / RenderThread 执行段
  → 查线程状态（Running / Runnable / Sleeping / Uninterruptible）
  → 找业务 section（Trace.beginSection）
  → 对齐 CPU 频率 / 调度延迟
  → 得出根因 + 可执行优化点
```

### 1.2 三类卡顿的本质区分

```
┌─────────────────────────────────────────────────────┐
│  App Deadline Missed（应用侧超时）                   │
│  → MainThread/RenderThread 在 deadline 前未完成     │
│                                                     │
│  SF Deadline Missed（SurfaceFlinger 合成超时）       │
│  → SF 未能在合成截止前拿到 buffer                    │
│                                                     │
│  Prediction Error（预测错误，VSYNC 频率切换）        │
│  → expected deadline 本身预测有偏差，非真实卡顿      │
└─────────────────────────────────────────────────────┘
```

区分这三类是所有分析的第一步，直接决定后续往哪个方向深挖。

---

## 2. Perfetto 抓取配置详解

### 2.1 关键参数说明

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| `buffers[0].size_kb` | `65536`（64 MB） | 主 ftrace buffer，滑动 10s 约需 32–64 MB |
| `buffers[1].size_kb` | `4096` | process_stats 独立 buffer |
| `fill_policy` | `DISCARD` | 满了丢新数据，保留最早信息；如需末尾段改 `RING_BUFFER` |
| `duration_ms` | `10000–15000` | 覆盖完整操作场景，避免过长（文件大、加载慢） |

### 2.2 必选数据源（最小集）

```protobuf
# 1. 调度 + atrace + 用户自定义 section
data_sources { config { name: "linux.ftrace"
  ftrace_config {
    ftrace_events: "sched/sched_switch"
    ftrace_events: "sched/sched_wakeup"
    ftrace_events: "sched/sched_blocked_reason"
    ftrace_events: "power/cpu_frequency"
    ftrace_events: "ftrace/print"          # Trace.beginSection 输出到这里
    atrace_categories: "gfx"
    atrace_categories: "view"
    atrace_categories: "input"
    atrace_categories: "sched"
    atrace_apps: "com.your.app"            # 限定包名，减少噪声
  }
}}

# 2. 帧时间线（必选，用于 FrameTimeline 分析）
data_sources { config { name: "android.surfaceflinger.frametimeline" }}

# 3. 进程/线程名映射
data_sources { config { name: "linux.process_stats"
  target_buffer: 1
  process_stats_config { scan_all_processes_on_start: true }
}}

# 4. Logcat（与业务日志对齐）
data_sources { config { name: "android.log"
  android_log_config { log_ids: LID_DEFAULT  log_ids: LID_SYSTEM }
}}
```

### 2.3 按场景选择 atrace_categories

| 场景 | 必选 categories | 可选 |
|------|----------------|------|
| **列表滑动** | `gfx view input sched` | `binder_driver dalvik` |
| **冷启动** | `am wm gfx view res` | `binder_driver ss pm dalvik` |
| **动画** | `gfx view` | `sync` |
| **多线程竞争** | `sched binder_driver binder_lock` | `sync` |
| **内存 / GC** | `dalvik memory memreclaim` | `gfx` |

> **原则**：categories 不是越多越好，无关 category 会增加 buffer 压力和 UI 噪声。

### 2.4 全量配置文件（对应 `atrace-capture/.../config/perfetto/config.txtpb`）

项目中 **`atrace-capture`** 包内 **`config/perfetto/config.txtpb`** 是一个包含所有常用数据源的"全量模板"，包括：
- `linux.ftrace`（全量 categories + `atrace_apps: "*"`）
- `linux.process_stats` / `linux.sys_stats`
- `android.heapprofd`（内存采样，`sampling_interval_bytes: 4096`）
- `android.java_hprof`（Java 堆快照）
- `android.log`（全 log ID）
- `android.surfaceflinger.frametimeline`

**日常使用建议**：把 `config.txtpb` 裁剪成场景配置（见 2.3），不要直接用全量版（heapprofd 会带来明显额外开销）。

### 2.5 使用 atrace-mcp 一键抓取

```
# Cursor / Claude 对话中直接说：
抓取 com.your.app 的滑动 trace，时长 12 秒，注入滑动手势
→ capture_trace(package="com.your.app", duration_seconds=12, inject_scroll=True)

抓取冷启动 trace
→ capture_trace(package="com.your.app", duration_seconds=15, cold_start=True)
```

---

## 3. UI 高效操作与分析主线

### 3.1 必会快捷键

| 快捷键 | 作用 |
|--------|------|
| `W / S` | 放大 / 缩小时间轴 |
| `A / D` | 左移 / 右移时间轴 |
| `F` | 聚焦选中的 slice（自动缩放到合适比例） |
| `M` | 临时标记当前时间点 |
| `Shift+M` | 持续标记（可叠加多个） |
| `G` | 跳转到指定时间戳 |
| `Ctrl+F` | 全局搜索 slice 名称 |

### 3.2 固定"关键轨道模板"

每次分析前先 **Pin to Top**（右键轨道 → Pin），建立固定观察视图：

```
[置顶区]
  ├── FrameTimeline（actual frame）       ← 帧超预算一目了然
  ├── com.your.app / main                 ← 主线程
  ├── com.your.app / RenderThread         ← 渲染线程
  ├── com.your.app / GPU completion       ← GPU 提交
  ├── SurfaceFlinger / main               ← SF 合成
  └── CPU Frequency (big core)            ← 频率是否压制
```

### 3.3 分析主线（标准 SOP）

```
Step 1  找超预算帧
  ├── FrameTimeline 轨道，红色 slice = actual > expected
  └── 点击红帧 → 底部面板显示 jank_type、actual_end_ns

Step 2  对齐时间段
  ├── M 标记红帧起止时间
  └── 在主线程 / RenderThread 轨道找对应时间段的执行状态

Step 3  判断卡顿归属
  ├── 主线程 slice 超长 → App 侧 MainThread 问题
  ├── RenderThread 超长 → GPU 提交 / draw 耗时
  ├── 线程状态长期 Runnable 但未运行 → 调度延迟（CPU 竞争）
  └── SF buffer 空 → SF 合成侧问题（相对少见）

Step 4  定位业务代码
  ├── 找到最长 slice（Choreographer#doFrame / traversal）
  ├── 逐层展开子 slice（measure → layout → draw）
  └── 找到自定义 Trace.beginSection 命中点

Step 5  对照 CPU / 调度
  ├── 该时间段 CPU 频率是否突然降频？
  ├── 该线程是否频繁在 Uninterruptible Sleep（等 I/O / 锁）？
  └── 是否有其他高优先级线程抢占 CPU？

Step 6  对齐 Logcat
  └── 在 android.log 轨道找 GC / 异常 / 业务关键事件时间戳
```

### 3.4 使用 atrace-mcp 加速分析

```
# 快速判断是否有明显卡顿
analyze_scroll_performance(trace_path="xxx.pb")

# 查指定时间段的慢 slice
query_slices(trace_path="xxx.pb", min_duration_ms=8)

# 向下展开某个 slice 的子调用
slice_children(trace_path="xxx.pb", slice_name="Choreographer#doFrame")

# 向上追溯调用链
call_chain(trace_path="xxx.pb", slice_name="AndroidOwner:measureAndLayout")

# 直接跑自定义 SQL
execute_sql(trace_path="xxx.pb", sql="SELECT name, dur/1e6 AS ms FROM slice WHERE dur > 8000000 ORDER BY dur DESC LIMIT 20")
```

---

## 4. 自定义埋点实战（Trace.beginSection）

### 4.1 基础用法

```kotlin
// Kotlin / Java — 必须同线程、成对出现
fun loadData() {
    Trace.beginSection("MyApp/loadData")
    try {
        // 实际逻辑
    } finally {
        Trace.endSection()   // finally 保证不遗漏
    }
}
```

**注意事项**：

| 规则 | 说明 |
|------|------|
| 同线程配对 | `beginSection` 和 `endSection` 必须在同一线程 |
| 支持嵌套 | 可以在一个 section 内部再开子 section，形成层级 |
| 名称限制 | 最长 127 字节（超出会被截断） |
| 主线程优先 | 在主线程上加 section 效果最明显；协程需注意线程切换 |
| 避免高频循环 | `RecyclerView` 每个 item 的 `onBindViewHolder` 加 section 会产生大量噪声 |

### 4.2 推荐命名规范

```
<模块>/<子模块>/<函数>
```

示例：

```
UI/FeedList/bindItem
UI/FeedList/loadImage
Network/DataRepo/fetchFeed
DB/UserDao/queryUser
Render/CustomView/onDraw
```

统一命名后可直接在 PerfettoSQL 中按前缀聚合：

```sql
SELECT
  name,
  count(*) AS call_count,
  avg(dur) / 1e6 AS avg_ms,
  max(dur) / 1e6 AS max_ms
FROM slice
WHERE name LIKE 'UI/FeedList/%'
GROUP BY name
ORDER BY avg_ms DESC;
```

### 4.3 ATrace 项目的增强埋点

ATrace 的 ART hook 能力可以在**不改业务代码**的情况下自动插桩：

```kotlin
// 通过 ATrace API 动态添加 watch rule
// → 被 watch 的方法调用会自动出现在 Perfetto timeline 上
ATrace.addWatchRule("com.your.app.FeedAdapter", "onBindViewHolder")
```

结合手动 `Trace.beginSection` 的最佳策略：

- **粗粒度**：ATrace 自动 hook 整个类的关键方法（无需改代码）
- **细粒度**：在确认是热点后，手动加 `beginSection` 分解子步骤

### 4.4 逐层钻取示例

```
Choreographer#doFrame  [32ms]
  └── traversal  [28ms]
        ├── measure  [2ms]
        ├── layout  [1ms]
        └── draw  [25ms]          ← 异常
              └── UI/FeedList/bindItem  [22ms]  ← 自定义 section
                    └── UI/FeedList/loadImage  [20ms]  ← 根因
```

在这个链路下，只需关注 `loadImage` 为何在主线程执行 20ms（应该异步化）。

---

## 5. 常见问题与解释

### 5.1 MainThread 与 RenderThread 的关系

```
MainThread                 RenderThread
────────────────           ────────────────────────────
Choreographer#doFrame      ──────────────────────────── 
  measure / layout         DrawFrames（接收 DisplayList）
  draw（生成 DisplayList） → GPU 提交
  ← 结束 →                ← GPU completion → buffer 入队
```

- 两者**并行执行**，不是严格同步。
- `draw()` 阶段只是生成 `DisplayList`（轻量），实际 GPU 绘制在 RenderThread。
- 因此主线程 `draw` 很快但 RenderThread 很慢 → GPU 负载问题，不是 CPU 问题。

### 5.2 VSYNC 片段为什么很长

| 原因 | 在 Perfetto 的表现 | 处理方向 |
|------|-------------------|---------|
| 主线程业务逻辑耗时 | `Choreographer#doFrame` 内 measure/layout/自定义 section 超长 | 优化业务代码，迁移到后台线程 |
| GC 暂停（STW） | 主线程出现 `GC` slice，同时其他线程暂停 | 减少对象分配，避免在绘制路径中创建对象 |
| CPU 调度延迟 | 线程状态长期 `Runnable`（就绪但未被调度） | 检查 CPU 负载，考虑线程优先级 |
| I/O 阻塞 | 线程状态 `Uninterruptible Sleep`（D 状态） | 主线程禁止同步 I/O，改异步 |
| 大图解码 / Bitmap 操作 | `BitmapFactory.decode` 或 `Bitmap.copy` 在主线程 | 迁移到后台线程 + 图片库缓存 |
| 锁竞争 | 主线程 `monitor-wait` 或 `binder transaction` 长时间等待 | 减少同步块范围，考虑读写锁 |

### 5.3 SF Deadline Missed 的排查思路

SF 侧卡顿通常不是业务代码问题，排查路径：

```
1. SurfaceFlinger/main 耗时是否超过 VSYNC 周期？
   → 是：SurfaceFlinger 本身性能问题（合成层数过多？HWC 不支持？）

2. 检查合成层数（Layer count）
   → layers 过多 → 减少 View 层级 / 使用 Hardware Layer

3. 是否有 buffer 等待超时？
   → App 侧出帧本身就晚 → 实际是 App Deadline Missed 引发的连锁

4. 是否在测试机（低配 GPU / 软件合成）？
   → 换真机验证
```

### 5.4 Compose 特有问题

| 症状 | 排查 slice | 常见根因 |
|------|-----------|---------|
| 首帧慢 | `Compose:recomposition` 时长 | 过多同步初始化、字体加载 |
| 滑动掉帧 | `measure` / `layout` 反复执行 | `LazyColumn` item 中使用不稳定的 key，引发过度重组 |
| 动画卡顿 | RenderThread 中 `CanvasContext::draw` 长 | `Canvas.drawBitmap` 大图 / 复杂 path |
| 重组过频 | `Compose:recomposition` 高频出现 | State 对象粒度过粗，无关 State 触发重组 |

---

## 6. ATrace 项目落地建议

### 6.1 建立"场景配置模板"体系

项目在 **`platform/atrace-capture/atrace_capture/config/perfetto/`** 下维护了 5 份裁剪过的配置文件，**按场景直接使用，避免使用全量 `config.txtpb`**（全量版含 heapprofd/java_hprof，会带来不必要的开销和噪声）。

#### 配置文件总览

| 文件 | 适用场景 | buffer | 时长 | 核心 categories |
|------|---------|--------|------|----------------|
| `scroll.txtpb` | 列表滑动 / Fling | 64 MB | 12 s | `gfx view input sched binder_driver sync dalvik` |
| `startup.txtpb` | 冷/温启动 | 64 MB | 15 s | `am wm gfx view res dalvik binder_driver ss pm` |
| `animation.txtpb` | 属性动画 / Compose 动画 / 转场 | 32 MB | 8 s | `gfx view sync` |
| `memory.txtpb` | GC 频繁 / 内存泄漏 / OOM | 128 MB (RING_BUFFER) | 30 s | `dalvik memory memreclaim` + heapprofd |
| `binder.txtpb` | Binder 阻塞 / 跨进程瓶颈 | 64 MB | 12 s | `binder_driver binder_lock aidl ss sched` |

#### 各配置关键差异说明

**`scroll.txtpb`**
- `fill_policy: DISCARD`：保留采集最早时刻（滑动起始状态），适合"抓操作起手"
- `cpufreq_period_ms: 500`：缩短到 500ms，提高 CPU 频率变化的时间分辨率
- 包含 `sync`（GPU fence）和 `dalvik`（判断 GC 是否干扰滑动）
- `sched/sched_blocked_reason`：分析 Uninterruptible Sleep 的内核根因

**`startup.txtpb`**
- 包含 `res`（AssetManager 资源解码）和 `pm`（PackageManager 查包）：这两个在冷启动阶段耗时显著但常被忽略
- `STAT_FORK_COUNT`：记录冷启动时新进程 fork 事件
- `LID_EVENTS`：ActivityManager 的 event log（记录 Activity 生命周期耗时）

**`animation.txtpb`**
- 最精简的配置，只保留 `gfx view sync`
- `fill_policy: DISCARD` + 8s：动画问题通常能快速复现，短时间足够
- 去掉 `binder_driver / am / res`，减少无关噪声

**`memory.txtpb`**
- **`fill_policy: RING_BUFFER`**（唯一使用此策略的配置）：OOM / 大内存增长通常发生在采集末尾，需保留最新数据
- 128 MB buffer：heapprofd 高频采样数据量大
- `proc_stats_poll_ms: 1000`：每秒记录 RSS，画出内存增长曲线
- `meminfo_period_ms: 1000`：整机 MemFree/Cached 趋势
- heapprofd 默认开启（`sampling_interval_bytes: 4096`），怀疑 Java 泄漏时改用 `android.java_hprof`

**`binder.txtpb`**
- 额外开启内核级 Binder ftrace 事件：`binder_transaction / binder_transaction_received / binder_lock / binder_locked / binder_unlock`（这些事件在 `atrace_categories: "binder_driver"` 中不完全覆盖）
- 同时抓 `ss`（system_server）：定位 server 端处理延迟
- `sched_blocked_reason`：Binder 等待时线程为 D 状态，需要内核事件还原根因

#### 使用方式

```bash
# 方式 1：直接用 adb + perfetto 命令行
adb shell perfetto --config - --txt \
  -o /data/misc/perfetto-traces/out.pb \
  < platform/atrace-capture/atrace_capture/config/perfetto/scroll.txtpb

# 方式 2：通过 atrace-mcp（Cursor 对话中）
capture_trace(
  package="com.your.app",
  duration_seconds=12,
  inject_scroll=True,
  config="platform/atrace-capture/atrace_capture/config/perfetto/scroll.txtpb"
)

# 方式 3：使用 record_android_trace 脚本（随 atrace-provision 包安装；以下为仓库根目录相对路径）
python3 platform/atrace-provision/atrace_provision/bundled_record_android_trace/record_android_trace \
  -c platform/atrace-capture/atrace_capture/config/perfetto/scroll.txtpb \
  -o scroll_$(date +%H%M%S).pb
```

> **使用前必须修改**：将各配置中的 `atrace_apps: "com.your.app"` 替换为实际包名；  
> `memory.txtpb` 中的 `heapprofd_config.process_cmdline` 同样需要替换。

### 6.2 建立 section 命名规范并全员落地

在团队 wiki 中固定：

```
<Product>/<Module>/<Action>

示例：
  QY/Feed/bindItem
  QY/Feed/loadCover
  QY/Player/decode
  QY/Search/query
```

并提供 Kotlin 工具函数封装，降低使用门槛：

```kotlin
object PerfTrace {
    inline fun <T> section(name: String, block: () -> T): T {
        Trace.beginSection(name)
        return try { block() } finally { Trace.endSection() }
    }
}

// 使用：
PerfTrace.section("QY/Feed/loadCover") {
    imageLoader.load(url)
}
```

### 6.3 ART hook + Perfetto 联动

ATrace 当前的 ART method instrumentation 能力落地建议：

| 场景 | ATrace 能力 | 使用方式 |
|------|------------|---------|
| 定位未知耗时类 | 批量 watch 某个包下的所有方法 | `add_watch_rule(class="com.your.package.*")` |
| 精确计时特定方法 | watch 单个方法，输出到 Perfetto slice | `add_watch_rule(class="...", method="onBindViewHolder")` |
| 动态开关采样 | 运行时 pause / resume，避免持续开销 | `pause_tracing() / resume_tracing()` |
| 减少噪声 | 配合 sampling interval 控制精度 vs 开销 | `set_sampling_interval(interval_ms=5)` |

### 6.4 常用 PerfettoSQL 模板沉淀

将 [第 7 节](#7-perfettosql-常用查询模板) 的 SQL 固化到 atrace-mcp 的 `trace_analyzer.py` 中，形成可复用的分析函数。

---

## 7. PerfettoSQL 常用查询模板

### 7.1 超预算帧统计（FrameTimeline）

```sql
-- 60Hz 下超预算帧（> 16.6ms）
SELECT
  count(*) AS over_budget_count,
  round(avg((actual_end_ns - actual_start_ns) / 1e6), 2) AS avg_frame_ms,
  round(max((actual_end_ns - actual_start_ns) / 1e6), 2) AS max_frame_ms
FROM actual_frame_timeline_slice
WHERE
  layer_name LIKE '%com.your.app%'
  AND (actual_end_ns - actual_start_ns) > 16600000;  -- 16.6ms
```

```sql
-- 按 jank_type 分类统计
SELECT
  jank_type,
  count(*) AS cnt,
  round(avg((actual_end_ns - actual_start_ns) / 1e6), 2) AS avg_ms
FROM actual_frame_timeline_slice
WHERE layer_name LIKE '%com.your.app%'
  AND jank_type != 'None'
GROUP BY jank_type
ORDER BY cnt DESC;
```

### 7.2 主线程慢 slice（> 8ms）

```sql
SELECT
  s.name,
  s.dur / 1e6 AS dur_ms,
  t.name AS thread_name,
  s.ts / 1e9 AS start_sec
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE
  p.name = 'com.your.app'
  AND t.name = 'main'
  AND s.dur > 8000000
ORDER BY s.dur DESC
LIMIT 30;
```

### 7.3 自定义 section 聚合

```sql
SELECT
  name,
  count(*) AS call_count,
  round(avg(dur) / 1e6, 2) AS avg_ms,
  round(max(dur) / 1e6, 2) AS max_ms,
  round(sum(dur) / 1e6, 2) AS total_ms
FROM slice
WHERE name LIKE 'QY/%'      -- 替换为你的前缀
GROUP BY name
ORDER BY total_ms DESC
LIMIT 20;
```

### 7.4 线程状态分布（Running/Runnable/Sleep）

```sql
SELECT
  state,
  count(*) AS cnt,
  round(sum(dur) / 1e6, 2) AS total_ms,
  round(avg(dur) / 1e6, 2) AS avg_ms
FROM thread_state ts
JOIN thread t ON ts.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE
  p.name = 'com.your.app'
  AND t.name = 'main'
GROUP BY state
ORDER BY total_ms DESC;
```

> - `Running`：真正在 CPU 上执行  
> - `R`（Runnable）：就绪等待调度，时间长 → CPU 竞争 / 调度延迟  
> - `S`（Sleeping）：主动等待，正常  
> - `D`（Uninterruptible Sleep）：I/O 等待或内核锁，时间长 → I/O 问题

### 7.5 GC 暂停统计

```sql
SELECT
  name,
  dur / 1e6 AS dur_ms,
  ts / 1e9 AS start_sec
FROM slice
WHERE name LIKE '%GC%'
  OR name LIKE '%garbage%'
ORDER BY dur DESC
LIMIT 20;
```

### 7.6 Binder 调用耗时

```sql
SELECT
  s.name,
  s.dur / 1e6 AS dur_ms,
  t.name AS thread_name
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE
  p.name = 'com.your.app'
  AND (s.name LIKE 'binder%' OR s.name LIKE 'AIDL%')
  AND s.dur > 5000000
ORDER BY s.dur DESC
LIMIT 20;
```

### 7.7 CPU 频率平均值（采集期间）

```sql
SELECT
  cpu,
  round(avg(value) / 1e6, 2) AS avg_freq_ghz,
  round(min(value) / 1e6, 2) AS min_freq_ghz,
  round(max(value) / 1e6, 2) AS max_freq_ghz
FROM counter c
JOIN cpu_counter_track ct ON c.track_id = ct.id
WHERE ct.name = 'cpufreq'
GROUP BY cpu
ORDER BY cpu;
```

---

## 附：推荐阅读

- [Perfetto 官方文档](https://perfetto.dev/docs/)
- [Android FrameTimeline 源码说明](https://source.android.com/docs/core/graphics/frametimeline)
- [Perfetto UI 操作教程](https://perfetto.dev/docs/visualization/perfetto-ui)
- 本项目 [ATRACE_ENGINEERING_GUIDE.md](./ATRACE_ENGINEERING_GUIDE.md)：采集 / `atrace-tool` / MCP 工程级关系
- 本项目 [atrace-mcp/README.md](../platform/atrace-mcp/README.md)（含 **Perfetto 场景配置**、`atrace-capture` 包内模板选型、Prompt 与打包分发）
- 本项目 [atrace-tool/README.md](../sdk/atrace-tool/README.md)：PC 端子命令与合并流水线
- 本项目 [atrace-mcp/README.md](../platform/atrace-mcp/README.md)：MCP 工具与 Prompt 全集
- 本项目 `docs/JANK_CHECKLIST.md`：10 分钟快速排查 + 深度分析 Checklist
