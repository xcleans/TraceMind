# atrace-provision / bundled_bin

预构建的 **atrace-tool** fat JAR，与 **`atrace-provision`** 一起分发，供 `AtraceToolProvider` / MCP / `DeviceController` 通过 `java -jar` 调用。

## atrace-tool.jar

**作用**：合并 Perfetto 系统 trace 与 ATrace 应用采样为统一 `.perfetto`，供 PerfettoSQL / TraceAnalyzer 分析。

**构建 / 更新**（仓库根目录）：

```bash
./gradlew deployMcp
```

等价于 `:atrace-tool:deployToMcp`：构建 fat JAR 并复制到本目录 **`atrace-tool.jar`**（固定文件名）。

**运行环境**：本机需 **Java 11+**（`java` 在 `PATH` 中）。

## 分发说明

- **MCP / service** 通过 Python 依赖 **`atrace-provision`** 即可获得本 JAR（wheel/sdist 经 `MANIFEST.in` 打入）。
- 若单独拷贝旧文档中的 `atrace-mcp/bin/`，请改为安装 **`atrace-provision`** 或使用 **`$ATRACE_TOOL`** 指向本地 JAR。
