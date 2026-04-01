# Perfetto 场景配置（`.txtpb`）

本目录为 **文本格式 Perfetto 配置**，供 **`adb shell perfetto`**、`record_android_trace` 或 **`atrace-mcp` → `capture_trace(..., perfetto_config=...)`** 使用。

## 文件一览

| 文件 | 用途 |
|------|------|
| [scroll.txtpb](scroll.txtpb) | 列表滑动 / 滚动卡顿 |
| [startup.txtpb](startup.txtpb) | 冷启动 / 温启动 |
| [memory.txtpb](memory.txtpb) | 内存、GC、heapprofd（开销大） |
| [binder.txtpb](binder.txtpb) | Binder / 跨进程瓶颈 |
| [animation.txtpb](animation.txtpb) | 动画 / 转场（精简噪声） |
| [config.txtpb](config.txtpb) | 全量模板，**不建议**直接用于日常采集 |

## 使用前必改

将所有文件中的 **`atrace_apps: "com.your.app"`** 改为被测包名；`memory.txtpb` 中若配置了 **heapprofd `process_cmdline`**，需与包名/进程一致。

## 与 MCP、问题选型

完整说明（发布流程、Prompt 话术、`capture_trace` 与 `perfetto_config`）见：

[**atrace-mcp/README.md**](../atrace-mcp/README.md) 中的 **「Perfetto 场景配置（docs/configs）」** 等章节。

**MCP 资源 URI**（连接 `atrace` MCP 后由 AI 读取，内容与上表文件一致）：`atrace://configs/index`、`atrace://configs/readme`、`atrace://configs/startup`、`scroll`、`memory`、`binder`、`animation`、`full-template`。若 `atrace-mcp` 不在仓库内，可设置环境变量 **`ATRACE_DOCS_CONFIGS`** 指向本目录。

**MCP 轨迹分析自动化样例**（冷启动 / 锁竞争、参数与 SQL）：[`docs/ATRACE_MCP_DEMO_SCENARIOS.md`](../ATRACE_MCP_DEMO_SCENARIOS.md)。
