# TraceMind / ATrace

## 产品说明

**ATrace**（Advanced Android Trace）是本仓库提供的 Android **方法级性能追踪 SDK**。采集以 **堆栈采样** 为主，支持按需启用 **ART 方法插桩**；结果可导出为 **Perfetto** 与 **Chrome Trace** 等标准格式，适用于 Perfetto UI 或既有分析流水线。

**TraceMind** 为 Gradle 工程名及发布坐标所用名称（如 JitPack），与 **ATrace** 指同一产品能力。

**基于 MCP 的轨迹分析自动化（Cursor，可选）**：在 **Cursor** 中接入 **`atrace-mcp`** 后，可通过自然语言驱动 MCP 工具，完成 **设备侧采集 → 轨迹合并 → 加载 → Perfetto SQL / 内置分析** 的连贯流程。该流程依赖两类组件：**（1）应用内 ATrace SDK**（增强采样、内置插件、**`TraceServer`** 等）；**（2）MCP 服务端所调用的本仓库采集实现**，将 **系统 Perfetto** 与 **应用侧 ATrace 数据** 合并为 **单个 `.perfetto` 文件**，使系统事件与应用栈在同一时间轴对齐。相对纯手工排障，有利于降低 **PerfettoSQL** 与脚本编写成本、由模型 **辅助选用工具并迭代查询**、在会话内 **多轮下钻**，并输出 **便于归档与对比的结构化结果**。复现实验与参数见 [docs/ATRACE_MCP_DEMO_SCENARIOS.md](docs/ATRACE_MCP_DEMO_SCENARIOS.md)。

## 特性

- **基于 MCP 的轨迹分析自动化**（可选）：在 **Cursor** 中配置 **`atrace-mcp`**，以对话方式完成采集、加载及 **Perfetto SQL / 内置分析**（如 `analyze_startup`、`analyze_jank`）。**前置条件**：应用已集成 **ATrace SDK**，并按文档完成 MCP **采集侧依赖**部署（**`./gradlew deployMcp`**，详见 [`atrace-mcp/README.md`](atrace-mcp/README.md)）。适用于在 **系统与应用合一轨迹** 上快速定位问题，并支撑回归与报告（见 **快速开始** 中 **atrace-mcp 安装** / **Prompt 与常用话术**，以及下文 **Cursor MCP** 与 [效果样例](docs/ATRACE_MCP_DEMO_SCENARIOS.md)）
- **高性能**：无锁环形缓冲区，极低采样开销
- **可扩展**：插件化 Hook 架构，易于添加新采样点
- **兼容性强**：`minSdk 21`，`compileSdk`/`targetSdk` 与当前工程一致（见 `gradle/libs.versions.toml`）；已针对多版本系统与 **ARM（arm64-v8a / armeabi-v7a）** 构建
- **安全可靠**：符号动态解析，自适应版本变化
- **多格式输出**：支持 Perfetto / Chrome Trace 格式
- **易于集成**：一行代码接入，无侵入式设计

## 仓库结构

| 路径 | 说明 | 文档 |
|------|------|------|
| `atrace-api` | 对外稳定 API（无 Native / SandHook） | [工程指南 · §1 仓库模块地图](docs/ATRACE_ENGINEERING_GUIDE.md#1-仓库模块地图) |
| `atrace-core` | 运行时：JNI、引擎、HTTP 服务、内置插件、Native CMake | [工程指南 · §1 仓库模块地图](docs/ATRACE_ENGINEERING_GUIDE.md#1-仓库模块地图) |
| `atrace-tool` | 采集链路组件：供 MCP（及 CLI）合并系统 Perfetto 与应用侧 ATrace 数据 | [`atrace-tool/README.md`](atrace-tool/README.md) |
| `atrace-mcp` | **Cursor / MCP 服务**：对话式采集编排、Perfetto SQL、设备与运行时控制（Python） | [`atrace-mcp/README.md`](atrace-mcp/README.md) |
| `sample` | 集成示例应用 | [`sample/README.md`](sample/README.md) |
| `third_party/SandHook` | 源码集成的 SandHook 子工程（`settings.gradle.kts` 中 `sandhook-*`） | [WatchList / 方法级插桩说明](docs/ARTMETHOD_WATCHLIST.md)（本仓库集成用法） |

## 环境要求

- **JDK**：11+（与 `libs.versions.toml` 中 `javaVersion` 一致）
- **Android 构建**：Android Studio 或命令行 Gradle；**AGP / Kotlin** 版本见根目录 `gradle/libs.versions.toml`
- **NDK**：构建 `atrace-core` 原生代码时需要（版本见 `ndkVersion`）
- **MCP / `atrace-mcp`**（可选）：**Python ≥ 3.10**、[uv](https://docs.astral.sh/uv/)；**合并采集类工具**依赖 `./gradlew deployMcp` 写入 MCP 目录的采集 JAR（详见 [`atrace-mcp/README.md`](atrace-mcp/README.md)）

## 本地构建

```bash
# 编译并安装示例应用
./gradlew :sample:installDebug

# 将 SDK 发布到本机 Maven（~/.m2）
./gradlew publishToMavenLocal

# 为 MCP 准备合并采集等依赖并写入 atrace-mcp 目录（独立分发 MCP 时用）
./gradlew deployMcp
```

示例应用使用说明见 [`sample/README.md`](sample/README.md)。

## 快速开始

### ATrace SDK 集成及架构说明

**`atrace-api`** 与 **`atrace-core`** 分层如下；模块职责与数据流详见 [工程指南 · §1 仓库模块地图](docs/ATRACE_ENGINEERING_GUIDE.md#1-仓库模块地图)。

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

### atrace-mcp 安装

1. **运行环境**：**Python ≥ 3.10**；推荐安装 [uv](https://docs.astral.sh/uv/)。**ADB** 已配置且设备可连。
2. **安装 Python 依赖**：在仓库内进入 **`atrace-mcp`**，执行 `uv run python run_mcp.py --help`（首次会拉取依赖）；或使用 pip + 虚拟环境。完整命令见 [atrace-mcp/README.md § 安装](atrace-mcp/README.md#安装)。
3. **合并采集依赖**（`capture_trace` 等需要）：在**仓库根目录**执行 **`./gradlew deployMcp`**（或 `./gradlew :atrace-tool:deployToMcp`），将采集 JAR 写入 **`atrace-mcp/bin/`**。说明见 [`.cursor/README.md`](.cursor/README.md) 与 [atrace-mcp/README.md § 工程文档与 atrace-tool](atrace-mcp/README.md#工程文档与-atrace-tool)。
4. **接入 Cursor**：本仓库 [`.cursor/mcp.json`](.cursor/mcp.json) 使用 `uv run --directory ${workspaceFolder}/atrace-mcp python run_mcp.py`；亦可按 [atrace-mcp/README.md § 接入 Cursor MCP](atrace-mcp/README.md#接入-cursor-mcp) 配置全局 **`~/.cursor/mcp.json`**。修改配置后须 **完全重启 Cursor**；在 Cursor **设置 → MCP** 中确认出现 `load_trace`、`capture_trace` 等工具。
5. **详细排障与工具列表**：[atrace-mcp/README.md](atrace-mcp/README.md)（含 [§ 故障排查](atrace-mcp/README.md#故障排查)）。

### Prompt 与常用话术

| 内容 | 文档位置 |
|------|----------|
| **内置 Prompt 注册表**（`scroll_performance_workflow`、`iterative_diagnosis` 等及适用场景） | [atrace-mcp/README.md § Prompt 说明（register_prompts）](atrace-mcp/README.md#prompt-说明register_prompts) |
| **可复制中文话术**（直接粘贴到 Cursor 对话框） | [atrace-mcp/README.md § 常用话术集合](atrace-mcp/README.md#常用话术集合可直接粘贴到-cursor-对话框) |
| **按问题类型选场景配置 + Prompt + 分析工具** | [atrace-mcp/README.md § Perfetto 场景配置](atrace-mcp/README.md#perfetto-场景配置) 内「问题类型 → 配置 + `capture_trace` + 分析」表 |

**延伸阅读**：工程级数据流与工作流见 [docs/ATRACE_ENGINEERING_GUIDE.md](docs/ATRACE_ENGINEERING_GUIDE.md)；可复现实验见 [docs/ATRACE_MCP_DEMO_SCENARIOS.md](docs/ATRACE_MCP_DEMO_SCENARIOS.md)；索引页 [docs/ATRACE_MCP_AND_CONFIGS.md](docs/ATRACE_MCP_AND_CONFIGS.md)。

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
- **分析类**：**`execute_sql`**、**`analyze_startup`**、**`analyze_jank`** 等对轨迹做结构化查询；可按需选用 **heap**、**simpleperf** 等 MCP 工具（详见 [`atrace-mcp/README.md`](atrace-mcp/README.md)）。

**说明**：集成 ATrace **不依赖** MCP。若不使用 Cursor MCP，仍可使用 [Perfetto UI](https://ui.perfetto.dev) 与仓库内 [命令行采集文档](atrace-tool/README.md) 完成采集与查看；工作流需自行编排。

## 文档索引

| 主题 | 文档 |
|------|------|
| 采集流程、MCP 与工具链总览 | [docs/ATRACE_ENGINEERING_GUIDE.md](docs/ATRACE_ENGINEERING_GUIDE.md) |
| MCP 与场景配置 | [docs/ATRACE_MCP_AND_CONFIGS.md](docs/ATRACE_MCP_AND_CONFIGS.md)、[docs/configs/README.md](docs/configs/README.md) |
| **MCP 轨迹分析自动化样例**（冷启动 / 锁竞争、参数、SQL、结论校验） | [docs/ATRACE_MCP_DEMO_SCENARIOS.md](docs/ATRACE_MCP_DEMO_SCENARIOS.md) |
| WatchList / 方法级规则 | [docs/ARTMETHOD_WATCHLIST.md](docs/ARTMETHOD_WATCHLIST.md) |
| 卡顿与 Perfetto | [docs/PERFETTO_JANK_GUIDE.md](docs/PERFETTO_JANK_GUIDE.md)、[docs/JANK_CHECKLIST.md](docs/JANK_CHECKLIST.md) |
| PC 工具 | [atrace-tool/README.md](atrace-tool/README.md) |
| **atrace-mcp**（安装、接入 Cursor、Prompt / 话术、工具列表、打包） | [atrace-mcp/README.md](atrace-mcp/README.md) |
| SDK 发布 | [docs/PUBLISH.md](docs/PUBLISH.md) |
| 示例应用 | [sample/README.md](sample/README.md) |

## License

Apache 2.0
