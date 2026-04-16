# atrace-service

TraceMind 仓库内的独立 HTTP 服务：用 FastAPI 包装 **`atrace_analyzer.TraceAnalyzer`**，分析 Perfetto trace，**不依赖 MCP / Cursor**。

## 前置条件

- **Python** ≥ 3.10  
- **分析引擎**：须能 `import atrace_analyzer`（在 monorepo 中从仓库根启动时依赖 **`platform/_monorepo.py`** 的 **`bootstrap()`** 与 sibling 包；或已 **`pip install` / `uv pip install` `atrace-analyzer`**）。  
- **网络**：首次使用 Perfetto `TraceProcessor` 时，Python 包可能会下载 trace processor shell，需能访问外网（或已缓存二进制）。

## 安装依赖

在 **`atrace-service/`** 目录下执行（推荐使用 [uv](https://github.com/astral-sh/uv)）：

```bash
cd atrace-service
uv sync
```

## 如何启动

### 推荐：`uv run` + 入口脚本

```bash
cd atrace-service
uv run atrace-service --host 127.0.0.1 --port 7788
```

开发时开启自动重载：

```bash
uv run atrace-service --host 127.0.0.1 --port 7788 --reload
```

### 端口占用时：内置启动脚本

遇到 `address already in use`（例如 `127.0.0.1:7788`）时：

```bash
cd atrace-service
python scripts/start_atrace_service.py --reload
```

Python 启动脚本会先检查端口监听进程，自动清理疑似 `atrace-service` / `uvicorn` 残留进程，再启动服务。若要强制清理任意占用进程，可追加 `--force-clean`。如需兼容旧命令，`bash scripts/start-atrace-service.sh` 会转发到该 Python 脚本。

### 备选：直接 uvicorn

```bash
cd atrace-service
uv run uvicorn atrace_service.main:app --host 127.0.0.1 --port 7788 --reload
```

（与 `main.py` 文档字符串一致。）

## 启动后如何验证

- **健康检查**：`curl http://127.0.0.1:7788/health`  
- **环境探测**（ADB、perfetto 包等）：浏览器或 `curl` 打开 `http://127.0.0.1:7788/env-check`  
- **交互式 API 文档**：浏览器打开 [http://127.0.0.1:7788/docs](http://127.0.0.1:7788/docs)  

## 常用参数说明

| 参数 | 含义 | 默认 |
|------|------|------|
| `--host` | 监听地址 | `127.0.0.1` |
| `--port` | 监听端口 | `7788` |
| `--reload` | 代码变更自动重启（开发用） | 关闭 |

## 典型调用流程（API）

1. `POST /trace/load`，body 示例：`{"trace_path": "/path/to/file.perfetto"}`  
2. 从响应中取得 trace 标识，再调用 `/trace/{trace_id}/...` 或 `/analyze/{trace_id}/...`  

具体路径以 `/docs` 中的 OpenAPI 为准。
