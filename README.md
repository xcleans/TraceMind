# TraceMind / ATrace

## 产品说明

### 项目定位与目标

**TraceMind（ATrace 工具链 + MCP）** 把 Android 端性能问题从「只有少数人会看 trace 的专家活」变成 **可重复、可协作、可被 AI 辅助的标准流程**，端到端覆盖三件事：

| 环节 | 要解决的问题 | 本仓库中的落点 |
|------|----------------|----------------|
| **采集** | 系统侧与应用侧数据割裂、对不齐 | **系统 Perfetto + 应用 ATrace** 经 **`atrace-tool`** 合并为 **单个 `.perfetto`**，同一时间轴对齐调度、帧、logcat 与方法栈 / 插件切片 |
| **分析** | Perfetto UI 与 SQL 门槛高、结论难复用 | **`atrace-mcp` / `trace_analyzer`** 提供 **结构化分析**（启动、滑动与帧质量、卡顿粗查等）与 **PerfettoSQL 下钻**；在 **Cursor** 里通过 **MCP** 由模型 **串联采集、加载、工具与查询**，多轮归因 |
| **与研发工作流衔接** | 结论口头化、难留档、难对比 | **可归档的 trace + 结构化结果**；**[atrace-mcp README · 第 6 节 平台能力（编排 · 话术 · 报告）](platform/atrace-mcp/README.md)**、**[场景复现与样例](docs/ATRACE_MCP_DEMO_SCENARIOS.md)**、**[工程指南](docs/ATRACE_ENGINEERING_GUIDE.md)** 降低「一人一策」；便于随 **工单 / PR / 版本** 传递证据链 |

**能力边界（诚实表述）**：深度结论仍须结合业务代码解读；**AI/MCP** 负责降低操作成本与加速下钻，**增强轨迹** 负责补齐跨层证据。  
**可持续完善的方向**（与「平台化」一致）：**离线标准输出** 已提供命令行 **`atrace-analyze`**（JSON / `bundle`，与 MCP 同源 `TraceAnalyzer`，见 [`docs/ATRACE_PLATFORM_CLI.md`](docs/ATRACE_PLATFORM_CLI.md)）；后续可补场景编排配置、**版本间指标对比与门禁**、与 **Cursor CLI** / CI 的固定流水线，使「标准流程」不绑定单一 IDE 交互方式。

---

- **AI 自动化 Trace 分析（Cursor + MCP）**  
在 **Cursor** 中接入 **`atrace-mcp`** 后，以 **自然语言驱动 MCP 工具**，将 **Trace 分析全流程自动化**：**设备侧采集 → 轨迹合并 → 加载 → Perfetto SQL / 内置分析** 由模型 **按意图串联**，减少手工脚本、命令行与 Perfetto UI 之间的反复切换；由模型 **自动选用工具、编写与修正查询**，在 **同一会话内多轮下钻**，并输出 **便于归档与版本对比的结构化结果**。**常用场景的工具编排、可复制话术与报告模板** 见 [atrace-mcp/README.md — 第 6 节](platform/atrace-mcp/README.md)；复现实验与参数见 [docs/ATRACE_MCP_DEMO_SCENARIOS.md](docs/ATRACE_MCP_DEMO_SCENARIOS.md)。

- **增强Trace（系统 Perfetto + 应用 ATrace 合一）**  
上述自动化建立在 **「增强轨迹」** 之上：**（1）应用内 ATrace SDK** 提供 **应用侧增强采集**（方法栈、内置插件切片、**`TraceServer`** 远程启停 / 采样与插件调参 / 打标与抓栈等）；**（2）MCP 服务端调用的本仓库合并采集实现** 将 **系统 Perfetto**（调度、帧、Binder、logcat 等）与 **ATrace 应用轨道** 合并为 **单个 `.perfetto` 文件**，使 **系统事件与应用调用栈、阻塞与自定义切片** 在 **同一时间轴** 对齐。相对仅使用 adb 侧系统采集，**应用层可见性与可分析维度显著增强**，也更利于 AI 做 **跨层关联与结论归纳**。

## 特性

- **AI 自动化 Trace 分析 + 增强轨迹**（可选，**Cursor** + **`atrace-mcp`**）：对话驱动 **全流程自动化分析**；依赖 **系统 + 应用合一 `.perfetto`** 的 **增强轨迹**（见上文产品说明）。**前置条件**：应用已集成 **ATrace SDK**，并完成 MCP **采集侧依赖**（**`./gradlew deployMcp`**，详见 [`atrace-mcp/README.md`](platform/atrace-mcp/README.md)）。**平台级场景编排、话术、报告** 见 [`atrace-mcp/README.md` 第 6 节](platform/atrace-mcp/README.md)；步骤与话术亦见 **快速开始** 与 [效果样例](docs/ATRACE_MCP_DEMO_SCENARIOS.md)
- **高性能**：无锁环形缓冲区，极低采样开销
- **可扩展**：插件化 Hook 架构，易于添加新采样点
- **兼容性强**：`minSdk 21`，`compileSdk`/`targetSdk` 与当前工程一致（见 `gradle/libs.versions.toml`）；已针对多版本系统与 **ARM（arm64-v8a / armeabi-v7a）** 构建
- **安全可靠**：符号动态解析，自适应版本变化
- **多格式输出**：支持 Perfetto / Chrome Trace 格式
- **易于集成**：一行代码接入，无侵入式设计

## 仓库结构

| 路径 | 说明 | 文档 |
|------|------|------|
| `sdk/atrace-api` | 对外稳定 API（无 Native / SandHook） | [工程指南 · 第 1 节 仓库模块地图](docs/ATRACE_ENGINEERING_GUIDE.md#1-仓库模块地图) |
| `sdk/atrace-core` | 运行时：JNI、引擎、HTTP 服务、内置插件、Native CMake | [工程指南 · 第 1 节 仓库模块地图](docs/ATRACE_ENGINEERING_GUIDE.md#1-仓库模块地图) |
| `sdk/atrace-tool` | 采集链路组件：供 MCP（及 CLI）合并系统 Perfetto 与应用侧 ATrace 数据 | [`sdk/atrace-tool/README.md`](sdk/atrace-tool/README.md) |
| `platform/atrace-mcp` | **Cursor / MCP 服务**：对话式采集编排、Perfetto SQL、设备与运行时控制（Python） | [`platform/atrace-mcp/README.md`](platform/atrace-mcp/README.md) |
| `sdk/sample` | 集成示例应用 | [`sdk/sample/README.md`](sdk/sample/README.md) |
| `sdk/third_party/SandHook` | 源码集成的 SandHook 子工程（`settings.gradle.kts` 中 `sandhook-*`） | [WatchList / 方法级插桩说明](docs/ARTMETHOD_WATCHLIST.md)（本仓库集成用法） |

## 环境要求

- **JDK**：11+（与 `libs.versions.toml` 中 `javaVersion` 一致）
- **Android 构建**：Android Studio 或命令行 Gradle；**AGP / Kotlin** 版本见根目录 `gradle/libs.versions.toml`
- **NDK**：构建 `atrace-core` 原生代码时需要（版本见 `ndkVersion`）
- **MCP / `atrace-mcp`**（可选）：**Python ≥ 3.10**、[uv](https://docs.astral.sh/uv/)；安装方式见 **[`platform/atrace-mcp/README.md`](platform/atrace-mcp/README.md)**；**合并采集**依赖 **`./gradlew deployMcp`** 将 JAR 写入 **`platform/atrace-provision/.../bundled_bin/`**（见 [工程文档与 atrace-tool](platform/atrace-mcp/README.md#工程文档与-atrace-tool)）

## 本地构建

```bash
# 编译并安装示例应用
./gradlew :sample:installDebug

# 将 SDK 发布到本机 Maven（~/.m2）
./gradlew publishToMavenLocal

# 为 MCP 准备合并采集等依赖并写入 atrace-mcp 目录（独立分发 MCP 时用）
./gradlew deployMcp
```

示例应用使用说明见 [`sdk/sample/README.md`](sdk/sample/README.md)。

## 快速开始

### ATrace SDK 集成及架构说明

**`atrace-api`** 与 **`atrace-core`** 分层如下；模块职责与数据流详见 [工程指南 · 第 1 节 仓库模块地图](docs/ATRACE_ENGINEERING_GUIDE.md#1-仓库模块地图)。

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              ATrace SDK                                 │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────── atrace-api（仅依赖 AndroidX）─────────────┐  │
│  │  ATrace 入口 │ TraceConfig / Builder │ TraceEngine 接口              │  │
│  │  TraceEngineImpl + 工厂注册（由 atrace-core 在启动前注入实现）        │  │
│  │  TracePlugin / PluginContext / SampleType │ ILibLoader │ ALog       │  │
│  └───────────────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────── atrace-core（API + JNI + SandHook 等）───────┐  │
│  │  TraceEngineCore：启停、导出、插件生命周期、系统属性合并配置          │  │
│  │  Native：栈采样、无锁缓冲、批量 Hook 标志位、ArtMethod 动态插桩      │  │
│  │  Java/Kotlin：ArtHookBackend（API 33+）/ SandHook+DexMaker（低版本）│  │
│  │  ClassLoadWatcher：WatchList 与类加载时自动 hook                     │  │
│  │  TraceServer（NanoHTTPD）：PC / atrace-tool / MCP 远程控制与下载     │  │
│  │  com.aspect.atrace.plugins.*：Binder/GC/Lock/IO 等内置插件           │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 通过 JitPack 集成（`com.github.xcleans:TraceMind:v1.0.8`）

在 **`settings.gradle.kts`**（或顶层 **`build.gradle.kts`** 的 `repositories`）中加入 **JitPack**，再在 app 模块依赖本仓库发布版本：

```kotlin
// settings.gradle.kts — dependencyResolutionManagement.repositories
maven { url = uri("https://jitpack.io") }
```

```kotlin
// app/build.gradle.kts
dependencies {
    implementation("com.github.xcleans:TraceMind:v1.0.8")
}
```

若你使用的 JitPack 构建产物为**多模块**形式（`artifactId` 为 `atrace-api` / `atrace-core`），可改为显式声明（版本号与 Tag 对齐）：

```kotlin
dependencies {
    implementation("com.github.xcleans.TraceMind:atrace-core:v1.0.8")
    // 一般无需再写 atrace-api（由 core 传递依赖）；如需显式对齐可再加同版本 atrace-api
}
```

更多发布与坐标说明见 [docs/PUBLISH.md](docs/PUBLISH.md)。

#### 应用内初始化

应用依赖 **`atrace-core`**（会传递依赖 **`atrace-api`**）。在 **`ATrace.init` 之前**必须注册引擎实现：在 **`Application.attachBaseContext`**（或等价时机）调用 **`TraceEngineCore.register()`**。若 Release 需零采样开销，可自行实现 **`TraceEngine`** 并通过 **`TraceEngineImpl.registerFactory`** 注册空实现，或不在 Release 包中依赖 **`atrace-core`**。

```kotlin
import android.app.Application
import android.content.Context
import com.aspect.atrace.ATrace
import com.aspect.atrace.core.TraceEngineCore
import com.aspect.atrace.plugins.BinderPlugin
import com.aspect.atrace.plugins.GCPlugin
import com.aspect.atrace.plugins.LockPlugin

class MyApp : Application() {

    override fun attachBaseContext(base: Context?) {
        super.attachBaseContext(base)
        TraceEngineCore.register()
    }

    override fun onCreate() {
        super.onCreate()
        // 若已在 attachBaseContext 中 register，此处 initTraceEngine 传空 lambda 即可
        ATrace.init(this, initTraceEngine = {}) {
            bufferCapacity = 100_000
            sampleInterval = 1_000_000L       // 主线程间隔；其他线程默认为 5×（纳秒）
            enablePlugins(BinderPlugin, GCPlugin, LockPlugin)
        }
    }
}
```

在界面或调试代码中启停与导出：

```kotlin
ATrace.start()
// …
val traceFile = ATrace.stopAndExport()
```

可选：在 **`init` 的第二个参数**中调用 `TraceEngineCore.register()`（与 `sample` 模块写法一致），但 **`init` 会先于引擎创建执行该 lambda**，仍需保证在首次 `init` 前完成注册。

### atrace-mcp 安装（摘要）

完整步骤与校验命令见 **[`platform/atrace-mcp/README.md`](platform/atrace-mcp/README.md)**。

| 步骤 | 做什么 |
|------|--------|
| 1 | **Python ≥ 3.10**，安装 [uv](https://docs.astral.sh/uv/) 或 pip + venv；**ADB** 可用。 |
| 2 | 仓库根 **`./dev-setup.sh uv`**（推荐）或 **`./dev-setup.sh`**，把 **`atrace-analyzer`**、**`atrace-capture`**、**`atrace-mcp`** 等以 editable 装入环境。 |
| 3 | 仓库根 **`./gradlew deployMcp`**，生成 **`atrace-tool.jar`** → **`atrace-provision/.../bundled_bin/`**（合并采集必需）。 |
| 4 | Cursor：按 **[「接入 Cursor MCP」](platform/atrace-mcp/README.md#接入-cursor-mcp)** 配置 **`mcp.json`**（`--directory` 指向 **`…/TraceMind/platform/atrace-mcp`**），**完全重启 Cursor**。 |

仅 wheel / zip、离线场景与常见错误见同一文档的 **安装**、**打包与分发**、**故障排查** 三节。工程级说明：[atrace-mcp/README.md「工程文档与 atrace-tool」](platform/atrace-mcp/README.md#工程文档与-atrace-tool)；本仓库 Cursor 示例：[`.cursor/mcp.json`](.cursor/mcp.json)、[`.cursor/README.md`](.cursor/README.md)。

### Prompt 与常用话术

| 内容 | 文档位置 |
|------|----------|
| **内置 Prompt 注册表**（`scroll_performance_workflow`、`iterative_diagnosis` 等） | [atrace-mcp/README.md — MCP Prompts](platform/atrace-mcp/README.md#mcp-prompts) |
| **可复制中文话术**（直接粘贴到 Cursor 对话框） | [atrace-mcp/README.md — 第 6.3 节](platform/atrace-mcp/README.md)（与 Prompt 编排一致） |
| **按问题类型选场景配置 + 采集 + 分析** | [atrace-mcp/README.md — Perfetto 场景配置](platform/atrace-mcp/README.md#perfetto-场景配置与-perfetto_config) |

**延伸阅读**：工程级数据流与工作流见 [docs/ATRACE_ENGINEERING_GUIDE.md](docs/ATRACE_ENGINEERING_GUIDE.md)；可复现实验见 [docs/ATRACE_MCP_DEMO_SCENARIOS.md](docs/ATRACE_MCP_DEMO_SCENARIOS.md)；MCP 安装与工具说明见 [atrace-mcp/README.md](platform/atrace-mcp/README.md)。

## Cursor MCP：AI 辅助下的轨迹分析

**能力与分工**  
在 **Cursor** 中启用 **`atrace-mcp`** 后，轨迹相关任务可由 **大语言模型通过 MCP 工具链辅助编排**。**采集**由 **ATrace SDK**（应用进程内）与本仓库 **MCP 内置采集实现** 协同完成，得到含系统事件与应用方法栈、插件切片等的 **合并轨迹**；**分析**由 **`load_trace`**、**`analyze_*`**、**`execute_sql`** 等 MCP 工具承担。

**相对纯手工工作流的主要收益**

| 维度 | 说明 |
|------|------|
| **端到端连贯** | 单次对话需求即可串联 **采集 → 加载 → 分析**，减少在多终端、Perfetto UI 与自建脚本之间的切换。 |
| **查询门槛** | 由模型按意图选用 `capture_trace`、`analyze_*`、`execute_sql` 等工具，降低对 **Perfetto 表结构** 与 **SQL 模板** 的依赖。 |
| **迭代排障** | 在同一会话中追加约束（进程、时间窗、锁 / Binder 等），便于 **多轮下钻**，贴近实际排障路径。 |
| **可交付产出** | 易于获得表格化或 JSON 形态的中间结果，便于写入报告、做 **版本间对比** 或团队同步。 |

**MCP 工具能力摘要**（前提：**应用已集成 ATrace**，且合并采集依赖已按文档就绪）

- **采集类**（如 **`capture_trace`**）：由 MCP 服务 **编排** 设备与宿主机侧步骤，将 **系统 Perfetto**（如 ftrace、FrameTimeline、logcat）与 **ATrace SDK 应用侧采样** 合并为 **单个 `.perfetto`**，支持在统一时间轴上查看 Java/Native 栈、阻塞与插件切片；相较仅使用 adb 侧 Perfetto，通常对 **应用层可见性** 更完整。
- **运行时控制**：经 ATrace SDK 提供的 **`TraceServer`**，可在 **不重新发包** 的前提下调整 **Binder / GC / Lock / IO** 等插件、采样参数、**WatchList / 精确 hook**、打标与抓栈，便于按场景扩展采集面。
- **分析类**：**`execute_sql`**、**`analyze_startup`**、**`analyze_jank`** 等对轨迹做结构化查询；可按需选用 **heap**、**simpleperf** 等 MCP 工具（详见 [`atrace-mcp/README.md`](platform/atrace-mcp/README.md)）。

**说明**：集成 ATrace **不依赖** MCP。若不使用 Cursor MCP，仍可使用 [Perfetto UI](https://ui.perfetto.dev) 与仓库内 [命令行采集文档](sdk/atrace-tool/README.md) 完成采集与查看；工作流需自行编排。

## 文档索引

| 主题 | 文档 |
|------|------|
| 采集流程、MCP 与工具链总览 | [docs/ATRACE_ENGINEERING_GUIDE.md](docs/ATRACE_ENGINEERING_GUIDE.md) |
| MCP 与场景配置 | [atrace-mcp/README.md](platform/atrace-mcp/README.md)、[atrace-capture/atrace_capture/config/perfetto/README.md](platform/atrace-capture/atrace_capture/config/perfetto/README.md) |
| **MCP 轨迹分析自动化样例**（冷启动 / 锁竞争、参数、SQL、结论校验） | [docs/ATRACE_MCP_DEMO_SCENARIOS.md](docs/ATRACE_MCP_DEMO_SCENARIOS.md) |
| WatchList / 方法级规则 | [docs/ARTMETHOD_WATCHLIST.md](docs/ARTMETHOD_WATCHLIST.md) |
| 卡顿与 Perfetto | [docs/PERFETTO_JANK_GUIDE.md](docs/PERFETTO_JANK_GUIDE.md)、[docs/JANK_CHECKLIST.md](docs/JANK_CHECKLIST.md) |
| PC 工具 | [sdk/atrace-tool/README.md](sdk/atrace-tool/README.md) |
| **atrace-mcp**（安装、接入 Cursor、Prompt / 话术、工具列表、打包） | [atrace-mcp/README.md](platform/atrace-mcp/README.md) |
| SDK 发布 | [docs/PUBLISH.md](docs/PUBLISH.md) |
| 示例应用 | [sdk/sample/README.md](sdk/sample/README.md) |

## License

Apache 2.0
