# 文档已合并至 atrace-mcp/README.md

本页为 **索引**：详细正文已统一维护于 **`atrace-mcp/README.md`**，请勿在别处重复撰写相同内容。

在 **Cursor** 中配置 **atrace** MCP 后，可通过对话驱动 **轨迹采集、加载、Perfetto SQL 及结构化分析**；可复现实验见下表末行。

请按下表主题查阅：

| 主题 | 链接 |
|------|------|
| **安装**（uv / pip、依赖校验） | [atrace-mcp/README.md § 安装](../atrace-mcp/README.md#安装) |
| **接入 Cursor MCP**（`mcp.json`、全局配置、生效验证） | [atrace-mcp/README.md § 接入 Cursor MCP](../atrace-mcp/README.md#接入-cursor-mcp) |
| **Perfetto 场景配置**（`docs/configs` 文件说明、问题类型选型、`perfetto_config`） | [atrace-mcp/README.md § Perfetto 场景配置](../atrace-mcp/README.md#perfetto-场景配置) |
| **工程文档、端到端接入、功能一览** | [atrace-mcp/README.md § 工程文档与 atrace-tool](../atrace-mcp/README.md#工程文档与-atrace-tool) |
| **工具说明**（`capture_trace` 等） | [atrace-mcp/README.md § 工具说明](../atrace-mcp/README.md#工具说明) |
| **Prompt 注册表**（`register_prompts`、场景与工具编排） | [atrace-mcp/README.md § Prompt 说明（register_prompts）](../atrace-mcp/README.md#prompt-说明register_prompts) |
| **常用话术（可复制到 Cursor）** | [atrace-mcp/README.md § 常用话术集合](../atrace-mcp/README.md#常用话术集合可直接粘贴到-cursor-对话框) |
| **打包与分发（zip / whl）** | [atrace-mcp/README.md § 打包与分发](../atrace-mcp/README.md#打包与分发) |
| **MCP 轨迹分析自动化样例**（合并采集、冷启动 / 锁竞争、SQL、结论说明） | [ATRACE_MCP_DEMO_SCENARIOS.md](ATRACE_MCP_DEMO_SCENARIOS.md) |

`docs/configs` 文件索引仍见 [`docs/configs/README.md`](configs/README.md)。
