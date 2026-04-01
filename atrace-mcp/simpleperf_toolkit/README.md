# AOSP simpleperf 工具链（内置）

从 [AOSP platform/system/extras/simpleperf](https://android.googlesource.com/platform/system/extras/+/master/simpleperf) 提取的脚本，用于 `capture_cpu_profile` 优先使用 **app_profiler.py** 采集。

## 结构

- `simpleperf/scripts/` — Python 脚本（app_profiler.py、gecko_profile_generator.py 等）
- `simpleperf/scripts/bin/android/<arch>/` — 设备端 simpleperf 二进制，**首次使用时从 NDK 复制**

## 依赖

- **Android NDK**：需设置 `ANDROID_NDK_HOME` 或通过 Android Studio 安装。首次采集时会将 `simpleperf` 从 NDK 复制到 `scripts/bin/android/<arch>/`。
- 若无 NDK，`capture_cpu_profile` 会回退为设备端 simpleperf record（需设备有 simpleperf 或通过 NDK 推包）。

## 参考

- [Firefox Profiler - Android Profiling](https://profiler.firefox.com/docs/#/./guide-android-profiling)
- [simpleperf scripts reference](https://android.googlesource.com/platform/system/extras/+/master/simpleperf/doc/scripts_reference.md)
