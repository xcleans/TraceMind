# atrace-service

TraceMind 仓库内的独立 HTTP 服务：用 FastAPI 包装 `TraceAnalyzer`，分析 Perfetto trace，**不依赖 MCP / Cursor**。

## 前置条件

- **Python** ≥ 3.10  
- **仓库布局**：默认从 monorepo 根目录启动时，需与 **`atrace-mcp/`** 同级（服务通过 `engine.py` 把 `atrace-mcp` 加入 `sys.path` 以导入 `trace_analyzer`）。若你已单独安装可提供 `trace_analyzer` 的环境，也可脱离该布局运行。  
- **网络**：首次使用 Perfetto `TraceProcessor` 时，Python 包可能会下载 trace processor shell，需能访问外网（或已缓存二进制）。

## 安装依赖

在 **`atrace-service/`** 目录下执行（推荐使用 [uv](https://github.com/astral-sh/uv)）：

```bash
cd atrace-service
uv sync
```

或使用 pip 可编辑安装：

```bash
cd atrace-service
pip install -e .
```

## 如何启动

### 方式一：`uv run` + 入口脚本（推荐）

```bash
cd atrace-service
uv run atrace-service --host 127.0.0.1 --port 7788
```

开发时开启自动重载：

```bash
uv run atrace-service --host 127.0.0.1 --port 7788 --reload
```

### 方式一补充：启动前自动清理占用端口的残留进程

当你遇到 `address already in use`（例如 `127.0.0.1:7788`）时，可使用内置启动脚本：

```bash
cd atrace-service
bash scripts/start-atrace-service.sh --reload
```

脚本会先检查端口监听进程，自动清理疑似 `atrace-service/uvicorn` 残留进程，再启动服务。  
若要强制清理任意占用进程，可追加 `--force-clean`。

### 方式二：`uv run` + uvicorn

与仓库内 `main.py` 文档字符串一致：

```bash
cd atrace-service
uv run uvicorn atrace_service.main:app --host 127.0.0.1 --port 7788 --reload
```

### 方式三：已 `pip install -e .` 后直接使用命令名

```bash
atrace-service --port 7788
atrace-service --reload --port 7788
```

### 方式四：以模块方式运行

```bash
cd atrace-service
uv run python -m atrace_service.main --port 7788
```

（`main` 末尾会调用 `start()`。）

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
