# Jank 排查 Checklist

> **两个版本**：  
> - [10 分钟快速定位版](#快速定位版-10-分钟) — 第一次看 trace，快速判断问题大类  
> - [深度分析版](#深度分析版) — 确认问题大类后，逐步钻取根因  
>
> 配合 [PERFETTO_JANK_GUIDE.md](./PERFETTO_JANK_GUIDE.md) 使用。

---

## 快速定位版（10 分钟）

> 目标：用 10 分钟判断"卡在哪一层"，决定下一步往哪个方向深挖。

### 准备（2 分钟）

- [ ] 已抓到 trace 文件（`.pb` / `.perfetto-trace`）
- [ ] 确认 trace 中包含复现时间段（操作时间 vs trace 时长对齐）
- [ ] 用 atrace-mcp 加载：`load_trace(trace_path="xxx.pb")`

### Step 1 — 快速看帧质量（2 分钟）

```
analyze_scroll_performance(trace_path="xxx.pb")
```

- [ ] `verdict` 是否为 `BAD` / `POOR`？
- [ ] `over_budget_frame_count` 超过总帧数的 5%？
- [ ] `p99_frame_ms` 超过 33ms？（接近 2 倍 VSYNC 周期）
- [ ] `jank_type` 分布：主要是 `App Deadline Missed` 还是 `SF Deadline Missed`？

**结论**：

| 结果 | 下一步 |
|------|--------|
| `App Deadline Missed` 为主 | → 进入「主线程/渲染线程分析」分支 |
| `SF Deadline Missed` 为主 | → 检查合成层数 / SurfaceFlinger 耗时 |
| `Prediction Error` 为主 | → 通常是 VSYNC 频率切换，可能是伪卡顿，继续验证 |

### Step 2 — 找最慢的 slice（2 分钟）

```sql
-- atrace-mcp execute_sql
SELECT name, dur/1e6 AS ms, ts/1e9 AS start_s
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name = 'com.your.app' AND t.name = 'main' AND dur > 8000000
ORDER BY dur DESC LIMIT 10;
```

- [ ] 最慢的 slice 是什么？（`Choreographer#doFrame` / `measure` / `draw` / 自定义 section）
- [ ] 最慢 slice 的耗时是多少 ms？
- [ ] 是否规律性出现（每 N 帧出现一次 → 可能是周期性任务）？

### Step 3 — 线程状态快照（2 分钟）

```sql
SELECT state, round(sum(dur)/1e6,1) AS total_ms
FROM thread_state ts
JOIN thread t ON ts.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name = 'com.your.app' AND t.name = 'main'
GROUP BY state ORDER BY total_ms DESC;
```

- [ ] `Running` 时间占比是否 < 50%？（说明 CPU 时间不够）
- [ ] `R`（Runnable）时间是否超过 5ms 的连续段？（调度延迟）
- [ ] `D`（Uninterruptible Sleep）是否出现？（I/O 阻塞）

### Step 4 — GC 是否干扰（1 分钟）

```
query_slices(trace_path="xxx.pb", name_filter="GC")
```

- [ ] 是否有 GC slice 与慢帧时间段重叠？
- [ ] GC 耗时是否超过 10ms？

### Step 5 — 快速结论（1 分钟）

填写排查卡：

| 字段 | 值 |
|------|---|
| 问题现象 | 滑动卡顿 / 启动慢 / 动画丢帧 |
| 超预算帧数 | |
| 主要 jank_type | |
| 最慢 slice 及耗时 | |
| 线程状态异常 | Running 不足 / Runnable 积压 / D 状态 |
| 是否有 GC 干扰 | 是 / 否 |
| 初步归因 | 业务代码 / GC / 调度 / I/O / SF |
| 下一步 | 进入深度分析 / 复现更多样本 |

---

## 深度分析版

> 目标：在快速版确认问题大类后，精确定位到函数级根因。

### 分支 A：主线程耗时过长

#### A1 — 定位最慢的 Choreographer 帧

```sql
SELECT s.id, s.dur/1e6 AS ms, s.ts/1e9 AS start_s
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name = 'com.your.app'
  AND t.name = 'main'
  AND s.name = 'Choreographer#doFrame'
ORDER BY s.dur DESC LIMIT 5;
```

- [ ] 记录最慢帧的 `ts`（用于后续 UI 对齐）
- [ ] 最慢帧耗时是否超过 2 × VSYNC 周期（33ms/22ms/16ms）？

#### A2 — 展开子 slice 层级

```
slice_children(trace_path="xxx.pb", slice_name="Choreographer#doFrame")
```

- [ ] 哪个子阶段最耗时？（`input` / `animation` / `traversal` / `draw`）
- [ ] `traversal` 内部：`measure` vs `layout` vs `draw` 哪个重？

#### A3 — 定位具体函数

```
call_chain(trace_path="xxx.pb", slice_name="<最慢的子 slice>")
```

- [ ] 调用链末端是哪个函数？
- [ ] 是否有自定义 section（`QY/` 前缀）出现在链路中？

#### A4 — 聚合自定义 section

```sql
SELECT name, count(*) AS cnt, round(avg(dur)/1e6,2) AS avg_ms, round(max(dur)/1e6,2) AS max_ms
FROM slice
WHERE name LIKE 'QY/%'    -- 替换为项目前缀
GROUP BY name ORDER BY avg_ms DESC LIMIT 20;
```

- [ ] 哪个 section 平均耗时最高？
- [ ] 是否有"偶发极值"（`max_ms` 远高于 `avg_ms`）？

#### A5 — 结论与优化

- [ ] 是否在主线程做了同步 I/O / 网络 / 大对象创建？
- [ ] 是否有死循环或 O(n²) 逻辑（随数据量增大耗时剧增）？
- [ ] 是否可以迁移到后台线程 / 协程？

---

### 分支 B：GC 暂停导致卡顿

#### B1 — 统计 GC 事件

```sql
SELECT name, dur/1e6 AS ms, ts/1e9 AS start_s
FROM slice
WHERE name LIKE '%GC%' OR name LIKE '%garbage%'
ORDER BY dur DESC LIMIT 20;
```

- [ ] GC 类型是什么？（`GC explicit` / `GC alloc` / `GC concurrent`）
- [ ] STW（Stop-The-World）阶段是否超过 5ms？

#### B2 — 找 GC 触发的根因

- [ ] GC 是否在每次滑动/动画时触发（→ 绘制路径中有大量临时对象）？
- [ ] 使用 `capture_heap_profile` 抓 allocation trace 确认分配热点：

```
capture_heap_profile(package="com.your.app", mode="native", duration_seconds=10)
analyze_heap_profile(trace_path="heap.pb")
```

#### B3 — 优化方向

- [ ] 在 `onDraw` / `onBindViewHolder` 中禁止 `new` 对象（使用对象池）
- [ ] 大型数据结构改用 `SparseArray` / `ArrayMap` 替代 `HashMap`
- [ ] 字符串拼接改 `StringBuilder`
- [ ] 图片 Bitmap 使用 `inBitmap` 复用

---

### 分支 C：调度延迟（CPU 竞争）

#### C1 — 确认 Runnable 积压

```sql
-- 主线程连续 Runnable 超过 5ms 的时间段
SELECT ts/1e9 AS start_s, dur/1e6 AS wait_ms
FROM thread_state ts_row
JOIN thread t ON ts_row.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name = 'com.your.app'
  AND t.name = 'main'
  AND ts_row.state = 'R'
  AND ts_row.dur > 5000000
ORDER BY ts_row.dur DESC LIMIT 10;
```

- [ ] Runnable 等待是否超过 5ms？
- [ ] 等待期间 CPU 是否被其他进程占用（在 Perfetto UI 查看 CPU 轨道）？

#### C2 — 检查 CPU 频率

```sql
SELECT cpu, round(avg(value)/1e6,2) AS avg_ghz
FROM counter c JOIN cpu_counter_track ct ON c.track_id = ct.id
WHERE ct.name = 'cpufreq'
GROUP BY cpu ORDER BY cpu;
```

- [ ] 大核是否在卡顿时间段降频（thermal throttling）？
- [ ] 应用是否被迁移到小核运行（调度策略问题）？

#### C3 — 优化方向

- [ ] 设置线程优先级：`Process.setThreadPriority(Process.THREAD_PRIORITY_DISPLAY)`
- [ ] 检查是否有其他高优先级任务（音视频 / 传感器）抢占
- [ ] 减少后台工作线程数量（线程过多导致 CPU 竞争）

---

### 分支 D：I/O 阻塞（主线程同步读写）

#### D1 — 确认 D 状态

```sql
SELECT ts/1e9 AS start_s, dur/1e6 AS block_ms
FROM thread_state ts_row
JOIN thread t ON ts_row.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name = 'com.your.app'
  AND t.name = 'main'
  AND ts_row.state = 'D'
ORDER BY ts_row.dur DESC LIMIT 10;
```

- [ ] D 状态是否超过 3ms？
- [ ] D 状态时间段与慢帧时间段是否重叠？

#### D2 — 找 I/O 调用栈

在 D 状态对应的时间戳，查看 `linux.ftrace` 中的 `block/block_rq_issue` 事件，或使用 `capture_cpu_profile` 抓调用栈：

```
capture_cpu_profile(package="com.your.app", duration_seconds=10)
report_cpu_profile(perf_data_path="perf.data")
```

- [ ] 调用栈中是否出现 `FileInputStream.read` / `SharedPreferences` / `SQLite` 在主线程？

#### D3 — 优化方向

- [ ] `SharedPreferences` 改 `DataStore`（异步）
- [ ] 数据库操作迁移到 Dispatcher.IO 协程
- [ ] 文件读写使用 `BufferedInputStream` + 后台线程

---

### 分支 E：Compose 重组过频

#### E1 — 统计重组次数

```sql
SELECT name, count(*) AS cnt, round(avg(dur)/1e6,2) AS avg_ms
FROM slice
WHERE name LIKE 'Compose%recomposition%' OR name LIKE 'AndroidOwner%'
GROUP BY name ORDER BY cnt DESC LIMIT 10;
```

- [ ] 单次滑动触发重组次数是否超过预期？
- [ ] 是否有不相关的 Composable 被触发重组（State 粒度过粗）？

#### E2 — 检查 measure/layout 重复执行

```sql
SELECT count(*) AS remeasure_count
FROM slice
WHERE name = 'measure' OR name = 'layout'
  AND dur > 2000000;   -- > 2ms 的 measure/layout
```

- [ ] `measure` 次数是否远多于帧数（一帧多次 measure → 不稳定 modifier）？

#### E3 — 优化方向

- [ ] 使用 `remember` / `derivedStateOf` 减少不必要的 State 传播
- [ ] 列表 item 的 `key` 必须稳定（避免 `index` 作为 key）
- [ ] 避免在 Composable 函数体直接创建 Lambda（使用 `remember` 缓存）
- [ ] `LazyColumn` item 中 side-effect 改为 `LaunchedEffect`

---

## 常用 atrace-mcp 命令速查

```bash
# 一键分析滑动帧质量
analyze_scroll_performance(trace_path="xxx.pb")

# 快速看卡顿 slice（> 8ms）
query_slices(trace_path="xxx.pb", min_duration_ms=8)

# 展开某个 slice 的子层级
slice_children(trace_path="xxx.pb", slice_name="Choreographer#doFrame")

# 追溯调用链
call_chain(trace_path="xxx.pb", slice_name="AndroidOwner:measureAndLayout")

# 执行自定义 SQL
execute_sql(trace_path="xxx.pb", sql="<查询语句>")

# 抓新 trace（滑动场景）
capture_trace(package="com.your.app", duration_seconds=12, inject_scroll=True)

# 抓 CPU 采样
capture_cpu_profile(package="com.your.app", duration_seconds=10)

# 抓内存分配
capture_heap_profile(package="com.your.app", mode="native", duration_seconds=10)
```

---

## 排查记录模板

复制此表到工单 / 周报中，方便团队沉淀经验：

```markdown
## Jank 排查记录

**日期**：
**负责人**：
**复现场景**：

### 数据

| 指标 | 值 |
|------|---|
| trace 文件 | xxx.pb |
| 总帧数 | |
| 超预算帧数 | |
| p99 帧耗时 | ms |
| 主要 jank_type | |

### 根因

| 层次 | 描述 |
|------|------|
| 现象 | （用户可感知的卡顿） |
| 直接原因 | （哪个 slice 超时） |
| 深层原因 | （为什么这个 slice 超时） |
| 代码位置 | （类名 / 函数名） |

### 修复方案

- [ ] 方案描述
- [ ] 预期收益（帧耗时降低 Xms / GC 次数减少 X%）

### 验证结果

对比修复前后 `analyze_scroll_performance` 输出：

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| over_budget_frame_count | | |
| p99_frame_ms | | |
```
