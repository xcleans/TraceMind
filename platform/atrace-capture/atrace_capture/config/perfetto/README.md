# Perfetto 场景配置（`.txtpb`）

本目录为 **文本格式 Perfetto 配置**，随 **`atrace-capture`** 打包；供 **`adb shell perfetto`**、`record_android_trace` 或 **`atrace-mcp` → `capture_trace(..., perfetto_config=...)`** 使用。

仓库内路径：`platform/atrace-capture/atrace_capture/config/perfetto/`。

## 文件一览

| 文件 | 用途 |
|------|------|
| [scroll.txtpb](scroll.txtpb) | 列表滑动 / 滚动卡顿 |
| [startup.txtpb](startup.txtpb) | 冷启动 / 温启动 |
| [memory.txtpb](memory.txtpb) | 内存、GC、heapprofd（开销大） |
| [binder.txtpb](binder.txtpb) | Binder / 跨进程瓶颈 |
| [animation.txtpb](animation.txtpb) | 动画 / 转场（精简噪声） |
| [config.txtpb](config.txtpb) | 全量模板，**不建议**直接用于日常采集 |
| [full.txtpb](full.txtpb) | 历史备用全量变体（与 `config.txtpb` 不同；按需选用） |

## 使用前必改

将所有文件中的 **`atrace_apps: "com.your.app"`** 改为被测包名；`memory.txtpb` 中若配置了 **heapprofd `process_cmdline`**，需与包名/进程一致。

## 与 MCP、问题选型

完整说明见 **[`atrace-mcp/README.md`](../../../../atrace-mcp/README.md)** 中的 **「Perfetto 场景配置」** 等章节。

**MCP 资源 URI**（连接 `atrace` MCP 后由 AI 读取）：`atrace://configs/index`、`atrace://configs/readme`、`atrace://configs/startup`、`scroll`、`memory`、`binder`、`animation`、`full-template`。内容由本目录提供。可设置 **`ATRACE_DOCS_CONFIGS`** 或 **`ATRACE_PERFETTO_CONFIGS`** 指向替代目录（覆盖默认）。

**Python 解析**：短名（如 `scroll`）由 `_monorepo.resolve_perfetto_config` 或 `atrace_capture.config.schema.CaptureConfig` 解析到本目录；仅安装 wheel 时依赖 **`atrace-capture` 的 package-data**。

**MCP 轨迹分析自动化样例**：[`docs/ATRACE_MCP_DEMO_SCENARIOS.md`](../../../../docs/ATRACE_MCP_DEMO_SCENARIOS.md)。
