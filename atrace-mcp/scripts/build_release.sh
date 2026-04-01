#!/usr/bin/env bash
# build_release.sh — 一键打包 atrace-mcp 的两种分发格式
#
# 用法:
#   cd ATrace
#   ./atrace-mcp/scripts/build_release.sh [VERSION]
#
# 产物:
#   dist/atrace-mcp-<VERSION>.zip          （目录 zip 方式）
#   atrace-mcp/dist/atrace_mcp-<VERSION>-py3-none-any.whl  （whl 方式）
#
# 前置条件:
#   - Java (./gradlew 需要)
#   - uv (pip install uv  或  brew install uv)

set -euo pipefail

# ── 路径 ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MCP_DIR="${REPO_ROOT}/atrace-mcp"

# ── 版本 ─────────────────────────────────────────────────────────────────────
# 优先取命令行参数，其次从 pyproject.toml 读取
VERSION="${1:-}"
if [[ -z "${VERSION}" ]]; then
    VERSION=$(grep -E '^version\s*=' "${MCP_DIR}/pyproject.toml" | head -1 | sed 's/.*= *"//; s/".*//')
fi
if [[ -z "${VERSION}" ]]; then
    echo "❌ 无法读取版本号，请在 pyproject.toml 中设置 version，或通过参数传入: $0 0.1.0" >&2
    exit 1
fi

echo "=========================================="
echo " atrace-mcp  打包脚本  v${VERSION}"
echo "=========================================="

# ── Step 1: 构建 atrace-tool.jar ──────────────────────────────────────────────
echo ""
echo "▶ Step 1/3  构建 atrace-tool.jar（./gradlew deployMcp）"
cd "${REPO_ROOT}"
./gradlew deployMcp
JAR_PATH="${MCP_DIR}/bin/atrace-tool.jar"
if [[ ! -f "${JAR_PATH}" ]]; then
    echo "❌ deployMcp 完成但找不到 ${JAR_PATH}" >&2
    exit 1
fi
echo "   ✓ JAR: ${JAR_PATH}"

# ── Step 2: 构建 wheel ────────────────────────────────────────────────────────
echo ""
echo "▶ Step 2/3  构建 Python wheel（uv build）"
cd "${MCP_DIR}"

# 清理旧产物，避免混淆
rm -rf dist build "*.egg-info" atrace_mcp.egg-info

uv build
WHL=$(ls dist/atrace_mcp-*.whl 2>/dev/null | head -1)
if [[ -z "${WHL}" ]]; then
    echo "❌ uv build 失败，dist/ 下没有找到 .whl 文件" >&2
    exit 1
fi
echo "   ✓ wheel: ${WHL}"

# ── Step 3: 打 zip ────────────────────────────────────────────────────────────
echo ""
echo "▶ Step 3/3  打 zip（目录分发方式）"
cd "${REPO_ROOT}"
ZIP_NAME="atrace-mcp-v${VERSION}.zip"
ZIP_PATH="${REPO_ROOT}/dist/${ZIP_NAME}"
mkdir -p "${REPO_ROOT}/dist"

zip -r "${ZIP_PATH}" atrace-mcp \
  --exclude "atrace-mcp/__pycache__/*" \
  --exclude "atrace-mcp/*.pyc" \
  --exclude "atrace-mcp/test_*.py" \
  --exclude "atrace-mcp/.DS_Store" \
  --exclude "atrace-mcp/dist/*" \
  --exclude "atrace-mcp/build/*" \
  --exclude "atrace-mcp/*.egg-info/*" \
  --exclude "atrace-mcp/atrace_mcp.egg-info/*" \
  --exclude "atrace-mcp/uv.lock" \
  --exclude "atrace-mcp/.venv/*"

echo "   ✓ zip:   ${ZIP_PATH}"

# ── 汇总 ─────────────────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo " 打包完成 🎉"
echo ""
echo " 方式一（目录 zip）:"
echo "   ${ZIP_PATH}"
echo ""
echo " 方式二（wheel）:"
echo "   ${REPO_ROOT}/atrace-mcp/${WHL#${MCP_DIR}/}"
echo ""
echo " 发送任意一个文件给接收方即可，详见 README.md「打包与分发」。"
echo "=========================================="
