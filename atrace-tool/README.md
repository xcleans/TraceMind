# ATrace Tool

PC 端命令行工具：通过 **ADB** 连接设备，完成 **系统 Perfetto 采集**、**应用采样数据拉取与合并**、以及 **CPU（simpleperf）/ 堆内存（heapprofd）** 等辅助采集。

**说明**：工具侧 **不包含** PerfettoSQL 查询或火焰图分析引擎；「分析」一般指在 **[Perfetto UI](https://ui.perfetto.dev)** 打开生成的 trace，或使用 **MCP / 其他脚本** 对同一 `.perfetto` 文件做二次处理。

---

## 子命令一览

| 子命令 | 作用 |
|--------|------|
| `capture`（默认） | 系统 trace（ftrace / atrace 等）+ 应用 HTTP 采样数据 → 合并为单个 `.perfetto` |
| `cpu` | 设备上 `simpleperf record`，拉回 `perf.data` 并生成文本 `report` |
| `heap` | 通过 Perfetto 配置录制 **native heap（heapprofd）** 或 **Java heap dump（java_hprof）** |
| `devices` | 列出已连接 Android 设备 |

兼容：命令行里 **不写** `capture` 时，除 `cpu` / `heap` / `devices` 关键字外，其余参数全部按 **`capture`** 解析（与旧版 CLI 一致）。

别名：`simpleperf` → `cpu`，`heapprofd` → `heap`。

---

## 全局参数

| 参数 | 说明 |
|------|------|
| `--json` | 仅向 stdout 输出一条 JSON（适合 MCP / CI）；抑制彩色日志 |
| `-v` / `--version` | 版本与简要帮助 |
| `-h` / `--help` | 顶层帮助；各子命令支持 `atrace-tool <cmd> -h` |

---

## `capture`：合并 trace 与「分析」相关能力

### 行为摘要

1. **ADB** 初始化，按 API 选择 **`PerfettoCapture`（≥28）** 或 **`LiteCapture`（更旧）**。
2. 启动系统侧采集：内置 **`record_android_trace`**（或 PATH 中的同名脚本），使用生成的 Perfetto 配置或 `-c` 自定义配置。
3. **可选** 通过 **端口转发 + HTTP** 连接集成 **atrace-core** 的应用：下发 `start/stop`、下载 `sampling` 与 `sampling-mapping`。
4. **若 HTTP 不可用**：降级为 **仅系统 trace**（`systemOnly`），不中断流程。
5. **`process()`**：对应用二进制采样做 **解码 → 转 Perfetto 包 → 与系统 trace 按包流拼接**，得到最终输出文件。

### 工具内「数据处理」（面向 Perfetto 的可视化）

| 模块 | 作用 |
|------|------|
| **`SamplingDecoder`** | 读取应用导出的采样文件（magic `ATRC`、与 native `ExportToFile` 对齐）；解析 **符号映射**；可选 **ProGuard mapping** 反混淆 |
| **`StackList` / `StackConvertor`** | 将采样记录转为 Perfetto 中的 **slice / track**：如 **SectionBegin/End**、**Message** 区间、以及 **调用栈树**（采样栈折叠为树再编码） |
| **`TraceBuilder` / `PerfettoProto`** | 手写 protobuf 片段，写出与 **ui.perfetto.dev** 兼容的 trace 流（含与系统 trace 合并策略） |

因此：**「分析」的第一落点**是合并后的 **`.perfetto`**；在 UI 里可看 **线程 slice**、与 **ftrace/sched** 等 **同一时间轴对齐**。

### 常用参数（`capture`）

除 `-h` 外，与 **`Arguments`** 一致，主要包括：

| 参数 | 说明 |
|------|------|
| `-a <package>` | 目标包名（必填） |
| `-t <seconds>` | 时长；省略则交互式按 Enter 结束 |
| `-o <path>` | 输出 `.perfetto` 路径 |
| `-m <path>` | ProGuard mapping（与解码反混淆配合） |
| `-mode perfetto` / `-mode simple` | 强制 Perfetto 或 Lite（仅应用 trace） |
| `-c <config>` | 自定义 Perfetto 配置（`.txtpb` / `.pbtxt`） |
| `-b <size>` | ring buffer，如 `64mb` |
| `-s <serial>` | 设备序列号 |
| `-port <port>` | 本地转发端口（默认 9090） |
| `-r` / `-w` | 重启应用 / 等待启动后再连 HTTP |
| `-maxAppTraceBufferSize` | 应用侧缓冲上限提示相关 |
| 尾部 **systrace 分类** | 如 `sched gfx view`；未指定时默认带 `sched` |

完整说明可运行：

```bash
java -jar build/libs/atrace-tool-1.0.0.jar capture -h
```
（若 jar 名随构建变化，以 `build/libs/` 下实际文件为准。）

### 离线分析建议

- 用 **Perfetto UI** 打开合并文件，查看 **Slices**、**CPU**、**Frame Timeline**（若配置已开启）等。
- 需要 SQL 时，在 UI 中使用 **PerfettoSQL**（或 trace_processor）对 `slice`、`thread_track` 等表查询。
- 更深入的启动/卡顿分析可参考仓库内 **`docs/PERFETTO_JANK_GUIDE.md`** 等文档。

---

## `cpu`：simpleperf 与输出物

- 在设备上对目标 **pid** 执行 **`simpleperf record`**（事件链：`cpu-cycles` → `task-clock` → … 自动回退）。
- **`--call-graph`**：`dwarf`（默认）或 `fp`，决定内核/ simpleperf 如何采 **调用栈**。
- 拉取 **`perf.data`**，并在设备上执行 **`simpleperf report`**，生成本地 **`perf_*_report.txt`**。

**分析方式**：阅读 report 文本（热点符号）；或用 Android NDK / simpleperf 自带工具对 `perf.data` 做火焰图等（本仓库 CLI 仅封装 record/pull/report）。

```bash
java -jar build/libs/atrace-tool-1.0.0.jar cpu -a com.example.app -t 10 --call-graph dwarf
java -jar build/libs/atrace-tool-1.0.0.jar cpu -a com.example.app -t 10 --json
```

---

## `heap`：内存 trace

- **API 29+**，应用需 **profileable 或 debuggable**。
- **`--mode native`**（默认）：**heapprofd**，采样 native **malloc/free** 调用栈（开始采集后才分配的可被观测）。
- **`--mode java-dump`**：trace 结束时 **Java heap hprof** 类数据，便于 retention 分析。

输出为 **`.perfetto`**，在 **Perfetto UI** 中打开，使用文档推荐的 **heap** 相关 SQL（参见命令内 `ui_hint` 与 [Perfetto Memory Profiling](https://perfetto.dev/docs/getting-started/memory-profiling)）。

```bash
java -jar build/libs/atrace-tool-1.0.0.jar heap -a com.example.app -t 30
java -jar build/libs/atrace-tool-1.0.0.jar heap -a com.example.app -t 10 --mode java-dump
```

---

## `devices`

列出 `adb devices` 可见设备；`--json` 时输出结构化列表，便于自动化选机。

---

## 构建

```bash
cd atrace-tool
./gradlew jar
```

Fat JAR 通常在 `build/libs/atrace-tool-1.0.0.jar`（版本与 `build.gradle.kts` 中 `version` 一致）。

也可使用安装目录入口脚本：

```bash
./gradlew installDist
./build/install/atrace-tool/bin/atrace-tool --help
```

---

## 依赖与环境

- Kotlin / Java（与根工程一致，建议 **Java 17+**）
- 本机 **`adb`** 在 PATH 中
- **`capture`** 的完整系统采集依赖 jar 内或 PATH 中的 **`record_android_trace`**（与 Perfetto Android 录制脚本一致）
- 应用侧 **`capture`** 合并采样需集成 **atrace-core** 并暴露 HTTP 控制与采样导出（见 `HttpClient` 注释中的 ContentProvider / 端口发现说明）

---

## 架构（源码目录）

```
atrace-tool/src/main/kotlin/com/aspect/atrace/tool/
├── Main.kt              # 入口与子命令路由
├── command/             # CaptureCommand, CpuCommand, HeapCommand, DevicesCommand
├── adb/                 # ADB 封装
├── capture/             # PerfettoCapture, LiteCapture, SystemCapture
├── core/                # Arguments, Workspace, GlobalArgs, parseCommand, Log, JsonOutput
├── http/                # 与 App TraceServer 通信
├── perfetto/            # TraceBuilder, PerfettoProto（手写 packet）
└── trace/               # SamplingDecoder, StackConvertor, StackList, MappingDecoder, Proguard…
```

---

## 数据流（`capture` + 应用在线）

```
ADB 连接
  → 启动系统 Perfetto（record_android_trace + 配置）
  →（可选）转发端口 + HTTP start/stop + 下载 sampling / mapping
  → 停止系统采集
  → SamplingDecoder 解码 + StackConvertor 转 Perfetto 包
  → 与系统 trace 拼接 → 输出单个 .perfetto
```

**纯系统降级**：HTTP 失败时仅输出系统 trace，无应用采样轨道。

---

## 与「分析功能」的边界

| 能力 | 是否在 atrace-tool 内实现 |
|------|---------------------------|
| 将应用采样转为 Perfetto slice / 栈树 | ✅（`trace/` + `perfetto/`） |
| 合并系统 + 应用 trace | ✅（`PerfettoCapture.process`） |
| simpleperf 文本 report | ✅（`cpu`） |
| PerfettoSQL / 自动瓶颈报告 | ❌（使用 UI 或 MCP `atrace` 等） |

若需命令行 SQL 分析同一 trace，可使用官方 **trace_processor_shell** 或仓库中的 **atrace-mcp** 等组件，与本工具输出的文件格式兼容。
