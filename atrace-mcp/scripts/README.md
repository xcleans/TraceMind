# record_android_trace 脚本

来自 [Perfetto](https://github.com/google/perfetto) 的官方脚本，用于在主机上通过 ADB 录制设备端 Perfetto 轨迹。

- **record_android_trace**：Mac / Linux，`#!/usr/bin/env python3`
- **record_android_trace_win**：Windows

atrace-mcp 在采集 **heapprofd** 时优先使用该脚本：配置通过 **stdin** 传给设备上的 perfetto，避免在设备上写配置文件导致的 Permission denied（如 `/data/local/tmp` 无法被系统 perfetto 读取）。同时支持 **Mac 与 Windows**，无需区分平台写两套 adb 逻辑。

用法示例（与 atrace-mcp 内部调用一致）：

```bash
# Mac/Linux
python3 record_android_trace -c /path/to/heap.pbtxt -o /tmp/atrace/heap.perfetto -n -s <serial>

# Windows
python record_android_trace_win -c /path/to/heap.pbtxt -o /tmp/atrace/heap.perfetto -n -s <serial>
```

`-n` 表示不自动打开浏览器；`-c` 使用完整 Perfetto 配置（含 duration_ms、heapprofd_config 等）。
