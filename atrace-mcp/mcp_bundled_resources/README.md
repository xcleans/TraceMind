# MCP 打包资源（独立分发）

本目录随 **`atrace-mcp/`** 目录或 **pip wheel** 分发，使在未检出完整 TraceMind 仓库时仍能使用 MCP 资源：

- **`configs/`**：与仓库 `docs/configs/` 同步的 Perfetto `.txtpb` 与说明。
- **`perfetto-trace-processor-reference.md`**：与仓库 `.conversation/perfetto-trace-processor-reference.md` 同步，供 `atrace://perfetto-sql-reference` 节选使用。

**维护**：更新仓库侧源文件后，请重新拷贝到本目录（或后续用脚本/CI 同步），再发版。

**查找顺序**（`server.py`）：环境变量覆盖 → 本目录（与 `server.py` 相邻或 `pip` 的 `sys.prefix/atrace_mcp/mcp_bundled_resources`）→ 单体仓库路径 `../docs/configs`、`../.conversation/`。
