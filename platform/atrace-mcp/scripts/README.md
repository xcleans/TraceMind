# MCP 辅助脚本

- **`build_release.py`**：跨平台主实现，构建 / 发布 MCP wheel 与离线 zip（版本号见 `platform/atrace-mcp/pyproject.toml`）。
- **`build_release.sh`**：Unix 兼容包装器，内部转发到 `build_release.py`。
- **在浏览器打开本地 trace**：使用 MCP 工具 **`open_trace_in_perfetto_browser`**，实现位于 **`atrace_capture.perfetto_viewer`**（与 Perfetto `record_android_trace` 同源思路：本机 HTTP + CORS + ui.perfetto.dev 深链）。

## record_android_trace

**Perfetto 官方** `record_android_trace` / `record_android_trace_win` 已迁至 **`atrace-provision`** 包内：

`platform/atrace-provision/atrace_provision/bundled_record_android_trace/`

`atrace-capture` 在 **heapprofd** 等场景通过 `atrace_provision.bundled_paths.record_android_trace_script_path()` 解析路径；`atrace-tool` JAR 内仍自带同名资源用于 `capture` / `heap`。

用法示例（在仓库根目录，相对路径）：

```bash
python3 platform/atrace-provision/atrace_provision/bundled_record_android_trace/record_android_trace \
  -c /path/to/heap.pbtxt -o /tmp/atrace/heap.perfetto -n -s <serial>
```

Windows 使用同目录下的 `record_android_trace_win`。
