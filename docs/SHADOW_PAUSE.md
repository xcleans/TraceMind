# Shadow Pause 模式

Shadow Pause 是 ATrace 在 **停止追踪（Stop）** 时的一种优化策略：**不卸载 Native Hook，只暂停采样**；再次 **Start** 时复用已安装的 Hook，从而显著缩短「停—再起」的间隔。实现位于 Native 层 `TraceEngine::Start` / `Stop`（见 `atrace-core/src/main/cpp/core/TraceEngine.cpp`）。

## 行为对比

| 阶段 | 默认模式（`shadowPause = false`） | Shadow Pause（`shadowPause = true`） |
|------|-----------------------------------|--------------------------------------|
| **Stop** | 将 `tracing_` 置为 false，并 **卸载** Hook | 将 `tracing_` 置为 false，**保留** Hook，仅将内部 `paused_` 置为 true，采样路径直接跳过 |
| **再次 Start** | 若 Hook 未安装则重新 **InstallHooks**（成本高） | Hook 已存在则 **跳过安装**，只清除 `paused_` 并恢复采样（成本低） |

采样请求在 `paused_` 为 true 时返回 `kSkipped`，与「未在追踪」区分逻辑在 `RequestSample` 中处理。

## 如何开启

### 1. 代码（`TraceConfig`）

```kotlin
ATrace.init(this, initTraceEngine = {}) {
    shadowPause = true
}
```

`TraceConfig.Builder.shadowPause` 默认 `false`。字段含义见 `atrace-api` 中 `TraceConfig` 注释：*stop 时不卸载 Hook，只停止采集，便于快速重启*。

### 2. 系统属性（与代码 **或** 关系）

合并逻辑在 `ConfigBuilder.merge`：

```text
shadowPause = codeConfig.shadowPause || TraceProperties.isShadowPauseEnabled()
```

属性键：`debug.atrace.shadowPause`，非 0 / 真值视为启用（与 `TraceProperties` 中其它布尔项一致）。

```bash
adb shell setprop debug.atrace.shadowPause 1
```

仅使用 `fromSystemProperties` 构建配置时，也会读取该属性。

## 适用场景与代价

- **适合**：调试或压测时需要 **短时间内多次** `start` → `stop`（或等价 API），希望减少 Hook 安装/卸载带来的延迟。
- **代价**：Stop 之后 Hook 仍驻留，会保留与 Hook 相关的 **内存与少量运行时开销**；若希望 Stop 后进程内完全回到「未插桩」状态，应关闭 Shadow Pause。
- **引擎销毁**：`TraceEngine` 析构时会 `reset` Hook 管理器；进程退出或引擎释放时仍会清理 Native 资源，**不会**因 Shadow Pause 永久泄漏引擎级资源（具体以当前实现为准）。

## 性能数据说明

README 等处的「再次 Start ~5ms、约 40×」等数字为 **典型环境下的经验量级**，随设备、已启用插件数量、Art 版本等变化，以实测为准。

## 相关代码索引

| 位置 | 说明 |
|------|------|
| `atrace-core/.../TraceEngine.cpp` | `Start` / `Stop` 与 `paused_`、`hooks_installed_` |
| `atrace-core/.../include/atrace.h` | `Config::shadow_pause` |
| `atrace-api/.../TraceConfig.kt` | `shadowPause` 配置项 |
| `atrace-core/.../config/ConfigBuilder.kt` | 与系统属性合并 |
| `atrace-core/.../config/TraceProperties.kt` | `debug.atrace.shadowPause` |
