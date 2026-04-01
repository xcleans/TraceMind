# ATrace - Advanced Android Trace Tool

一个高性能、可扩展的 Android 方法级追踪工具，基于堆栈采样技术。

## 特性

- 🚀 **高性能**：无锁环形缓冲区，极低采样开销
- 🔧 **可扩展**：插件化Hook架构，易于添加新采样点
- 📱 **兼容性强**：支持 Android 8.0-15，ARM/x86 双架构
- 🔒 **安全可靠**：符号动态解析，自适应版本变化
- 📊 **多格式输出**：支持 Perfetto/Chrome Trace 格式
- 🛠️ **易于集成**：一行代码接入，无侵入式设计
- ⚡ **Shadow Pause**：快速重启追踪，多次追踪性能提升 40x

## 架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              ATrace SDK                                 │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────── atrace-api（仅依赖 AndroidX）─────────────┐  │
│  │  ATrace 入口 │ TraceConfig / Builder │ TraceEngine 接口              │  │
│  │  TraceEngineImpl + 工厂注册（由 core/noop 在启动前注入实现）          │  │
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

## 快速开始

应用依赖 **`atrace-core`**（会传递依赖 **`atrace-api`**）。在 **`ATrace.init` 之前**必须注册引擎实现：Debug/分析构建使用 **`TraceEngineCore.register()`**，Release 可换 **`NoopATrace.register()`**（空实现，见 Maven **`atrace-noop`**）。

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
            shadowPause = true
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

### Shadow Pause 模式

Shadow Pause 是一种优化的追踪停止模式，在停止时保留 Hook 不卸载，大幅提升多次追踪的启动速度：

| 操作 | 正常模式 | Shadow Pause | 提升 |
|------|---------|-------------|------|
| 再次 Start | ~200ms | ~5ms | **40x** |
| Stop | ~100ms | ~1ms | **100x** |

详见：[Shadow Pause 文档](docs/SHADOW_PAUSE.md)

```kotlin
// 假定已调用 TraceEngineCore.register()
ATrace.init(this, initTraceEngine = {}) {
    shadowPause = true
}

// 或通过系统属性动态启用
// adb shell setprop debug.atrace.shadowPause 1
```

## 模块说明

| 模块 | 说明 |
|------|------|
| `atrace-api` | 稳定对外契约：无 Native、无 SandHook；供集成方编译期依赖 |
| `atrace-core` | 完整运行时：JNI、`TraceEngineCore`、HTTP 服务、内置插件、动态插桩后端 |
| `atrace-noop` | **Maven 工件**：空引擎注册，Release 零开销占位（本仓库源码树不单独 include 该模块） |
| `atrace-tool` | PC 端合并系统 Perfetto 与应用采样 |
| `atrace-mcp` | Cursor / MCP：采集、Perfetto SQL 分析、设备控制 |
| `sample` | 集成示例（含 WatchList / 自动 hook 等） |

### `atrace-api`（工程职责）

- **`ATrace`**：对外唯一推荐入口（`start` / `stop` / `stopAndExport`、`capture`、`mark`、`beginSection` / `endSection`）。
- **`TraceConfig` + `Builder`**：缓冲区容量、主/后台线程采样间隔、堆栈深度、时钟与输出格式（Perfetto / Chrome / RAW）、HTTP 开关、Shadow Pause、`ILibLoader` 等。
- **`TraceEngine` 接口** 与 **`TraceEngineImpl`**：工厂由 `atrace-core` 或 `atrace-noop` 在启动阶段 `registerFactory`，避免 API 模块反向依赖实现。
- **`TracePlugin` / `PluginContext` / `SampleType`**：插件扩展协议；**`ALog`**：日志门面。

### `atrace-core`（工程职责）

- **`TraceEngineCore`**：`TraceEngine` 的实现；合并 **`TraceProperties` 系统属性**与代码配置；调度插件与 Native 启停；导出二进制采样供 **`atrace-tool`** 解码。
- **Native（CMake）**：栈采样、环形缓冲、按位批量安装系统级 Hook（Binder/GC/Lock/JNI/SO/Alloc/MessageQueue/IO 等与 `HookFlags` 对应）。
- **Art 方法级追踪**：高版本 **`NativeArtHookBackend`**；低版本 **`SandHookDexMakerBackend`**（DexMaker 生成桩 + SandHook）；**`ClassLoadWatcher`** + **`ATrace.addWatchedRule` / `enableAutoHook`** 等完成 WatchList 与按需插桩（详见 [动态插桩说明](docs/PHASE3_DYNAMIC_INSTRUMENTATION.md)）。
- **`TraceServer` + `ServerManager`**：本地 HTTP（默认动态端口），供 **`atrace-tool` / MCP** 启停 trace、插件开关、采样间隔、WatchList、精确 hook、下载文件等。
- **内置插件**：包名 **`com.aspect.atrace.plugins`**（如 `BinderPlugin`、`GCPlugin`、`LockPlugin`），与 Native 标志位联动。

集成时通常只声明 **`implementation(project(":atrace-core"))`**（或等价 Maven 坐标），无需单独再依赖 `atrace-api`。

## Cursor MCP（AI 客户端）

本仓库在 [`.cursor/mcp.json`](.cursor/mcp.json) 中接入了 **atrace** MCP，打开本工程后重启 Cursor 即可使用（需安装 **uv**）。说明见 [`.cursor/README.md`](.cursor/README.md) 与 [`atrace-mcp/README.md`](atrace-mcp/README.md)。

## 文档

- [工程指南：采集 / atrace-tool / MCP 分析](docs/ATRACE_ENGINEERING_GUIDE.md)
- [ATrace MCP：工具、场景配置、Prompt、打包分发](atrace-mcp/README.md)
- [Shadow Pause 模式](docs/SHADOW_PAUSE.md)
- [PC 工具使用](atrace-tool/README.md)
- [ATrace MCP 接入与工具列表](atrace-mcp/README.md)
- [SDK 发布指南](docs/PUBLISH.md)

## License

Apache 2.0

