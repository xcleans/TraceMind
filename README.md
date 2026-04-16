# TraceMind 蓝图说明

## 项目定位与目标

TraceMind = `SDK`（应用侧增强采集） + `MCP`（采集/分析编排） + `WebUI`（可视化入口）。

目标是把性能分析流程标准化为：**采集 -> 合并 -> 分析 -> 输出结论**。

**TraceMind（ATrace 工具链 + MCP）** 把 Android 端性能问题从「只有少数人会看 trace 的专家活」变成 **可重复、可协作、可被 AI 辅助的标准流程**，端到端覆盖三件事。

## 目录分层（只看这两层）

- `sdk/`：客户端 SDK 与 Android 相关模块
- `platform/`：平台侧能力（MCP、WebUI、分析内核、服务端）

### `sdk/` 主要内容

- `sdk/atrace-api`：对外 API
- `sdk/atrace-core`：运行时与采样核心实现
- `sdk/atrace-tool`：本地/命令行采集工具
- `sdk/sample`：示例应用
- `sdk/third_party`：第三方依赖源码（如 SandHook）

### `platform/` 主要内容

- `platform/atrace-mcp`：MCP 服务（供 Cursor/Agent 调用）
- `platform/atrace-service`：服务端与 WebUI 入口
- `platform/atrace-analyzer`：分析内核（启动/滑动/jank 等）
- `platform/atrace-capture`：采集配置与路由
- `platform/atrace-device`：设备控制能力（ADB/传输等）
- `platform/atrace-ai` / `platform/atrace-orchestrator`：AI 编排能力
- `platform/atrace-provision`：打包资源与工具供给

## SDK / MCP / WebUI 三者关系

1. **SDK（运行在 App 内）**  
   负责应用侧增强数据采集（方法栈、插件切片、运行时控制入口等）。

2. **MCP（运行在平台侧）**  
   对外提供标准工具接口（load_trace、analyze、capture 等），串联设备采集、轨迹加载、结构化分析。

3. **WebUI（运行在平台侧）**  
   提供可视化操作入口，调用 `atrace-service`，由服务进一步调用 MCP/分析内核。

可理解为：**SDK 产数据，MCP 做能力编排，WebUI 做交互承载**。

```text
+-------------------- sdk/ ---------------------+
| App -> atrace-api/core -> trace + runtime ctl |
+------------------ data flow ------------------+
                     |
                     v
+--------------- platform/ ---------------------+
| WebUI(atrace-service) -> MCP(atrace-mcp)      |
|                        -> analyzer/capture     |
+------------------------------------------------+
```

## 推荐阅读顺序

1. `platform/atrace-mcp/README.md`（MCP 安装与工具）
2. `platform/atrace-service/README.md`（WebUI/服务启动）
3. `sdk/sample/README.md`（App 侧集成示例）

## License

Apache 2.0
