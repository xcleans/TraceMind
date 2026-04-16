# AOSP simpleperf（vendored）

从 [AOSP platform/system/extras/simpleperf](https://android.googlesource.com/platform/system/extras/+/master/simpleperf) 提取的脚本，随 **`atrace-provision`** 分发，供 `SimpleperfToolkitProvider` / `DeviceController` 等走 **app_profiler.py** 等主机侧路径。

## 位置

本目录为包内 **`atrace_provision/bundled_simpleperf/`**（原在 `atrace-mcp/simpleperf_toolkit/simpleperf/`）。

## 结构

- `scripts/` — Python 脚本（app_profiler.py、gecko_profile_generator.py 等）
- `scripts/bin/android/<arch>/` — 设备端 simpleperf 二进制，**首次使用时从 NDK 复制**

## 依赖

- **Android NDK**：`ANDROID_NDK_HOME` 或 Android Studio 安装的 NDK。首次采集时会将 `simpleperf` 从 NDK 复制到 `scripts/bin/android/<arch>/`。
- 若无 NDK，采集逻辑会回退为设备端 `simpleperf record` 等路径。

## 参考

- [Firefox Profiler - Android Profiling](https://profiler.firefox.com/docs/#/./guide-android-profiling)
- [simpleperf scripts reference](https://android.googlesource.com/platform/system/extras/+/master/simpleperf/doc/scripts_reference.md)
