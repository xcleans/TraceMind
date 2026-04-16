# ATrace Sample

示例应用，用于演示和测试 ATrace SDK 的各项能力。

## 功能说明

- **基础控制**：开始追踪、停止追踪、停止并导出、手动捕获堆栈
- **功能测试**：通过按钮触发 Binder、GC、锁、对象分配、IO、JNI、多线程、MessageQueue 等场景，便于在 trace 中观察对应事件

## 运行方式

1. 用 Android Studio 打开 ATrace 工程，选择 `sample` 运行配置，安装到设备或模拟器。
2. 或命令行：
   ```bash
   ./gradlew :sample:installDebug
   adb shell am start -n com.aspect.atrace.sample/.MainActivity
   ```

## 使用建议

1. 点击「开始追踪」后再操作各「功能测试」按钮，便于在导出的 trace 中看到对应采样与事件。
2. 使用「停止并导出」可将当前缓冲区数据导出到应用私有目录；配合 PC 端 `atrace-tool` 可拉取并合并系统 trace。
3. 若需测试对象分配，请在 `App.kt` 的 `enablePlugins` 中取消注释 `AllocPlugin`（注意：分配追踪开销较大）。

## 与 PC 工具配合

设备上已启用 HTTP 服务（`enableHttpServer = true`）时，可在 PC 上使用 [atrace-tool](../atrace-tool/README.md) 进行：

- 开始/停止追踪
- 下载 trace 数据
- 解码并转换为 Perfetto 格式
- 与系统 trace 合并

确保设备与 PC 在同一网络或通过 USB 端口转发访问设备上的 ATrace HTTP 端口。
