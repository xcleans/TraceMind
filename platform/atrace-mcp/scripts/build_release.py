#!/usr/bin/env python3
"""Cross-platform release builder for atrace-mcp artifacts.

Build outputs:
  - dist/atrace_capture-*.whl
  - dist/atrace_mcp-*.whl
  - dist/atrace-mcp-v<MCP_VERSION>.zip
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
MCP_DIR = REPO_ROOT / "platform" / "atrace-mcp"
CAPTURE_DIR = REPO_ROOT / "platform" / "atrace-capture"
DIST_ROOT = REPO_ROOT / "dist"
CAPTURE_PERFETTO = CAPTURE_DIR / "atrace_capture" / "config" / "perfetto"
JAR_PATH = REPO_ROOT / "platform" / "atrace-provision" / "atrace_provision" / "bundled_bin" / "atrace-tool.jar"

ZIP_INPUTS = [
    Path("platform/_monorepo.py"),
    Path("platform/atrace-mcp"),
    Path("platform/atrace-capture"),
    Path("platform/atrace-device"),
    Path("platform/atrace-provision"),
    Path("platform/atrace-analyzer"),
]


def run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def clean_build_artifacts(pkg_dir: Path) -> None:
    for d in ("dist", "build"):
        target = pkg_dir / d
        if target.exists():
            shutil.rmtree(target)
    for egg in pkg_dir.glob("*.egg-info"):
        if egg.is_dir():
            shutil.rmtree(egg)


def first_match(pattern: str, base: Path) -> Path:
    matches = sorted(base.glob(pattern))
    if not matches:
        raise RuntimeError(f"No file matches {pattern} under {base}")
    return matches[0]


def read_mcp_version(arg_version: str | None) -> str:
    if arg_version:
        return arg_version
    text = (MCP_DIR / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    if not m:
        raise RuntimeError("Cannot read MCP version from platform/atrace-mcp/pyproject.toml")
    return m.group(1)


def should_exclude(path: Path) -> bool:
    name = path.name
    parts = set(path.parts)
    if "__pycache__" in parts:
        return True
    if any(p in parts for p in (".venv", ".git", "dist", "build")):
        return True
    if any(p.endswith(".egg-info") for p in path.parts):
        return True
    if name.endswith(".pyc") or name == ".DS_Store" or name == "uv.lock":
        return True
    if name.startswith("test_") and name.endswith(".py"):
        return True
    return False


def write_zip(zip_path: Path) -> None:
    inputs = list(ZIP_INPUTS)
    if (REPO_ROOT / "platform" / "_logging.py").is_file():
        inputs.append(Path("platform/_logging.py"))

    with ZipFile(zip_path, mode="w", compression=ZIP_DEFLATED) as zf:
        for rel in inputs:
            src = REPO_ROOT / rel
            if src.is_file():
                if not should_exclude(rel):
                    zf.write(src, rel.as_posix())
                continue
            if not src.is_dir():
                raise RuntimeError(f"Missing zip input: {src}")
            for p in src.rglob("*"):
                if not p.is_file():
                    continue
                relp = p.relative_to(REPO_ROOT)
                if should_exclude(relp):
                    continue
                zf.write(p, relp.as_posix())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build atrace-mcp release artifacts")
    parser.add_argument("mcp_version", nargs="?", help="Override MCP version")
    args = parser.parse_args(argv)

    mcp_version = read_mcp_version(args.mcp_version)
    print("==========================================")
    print(f" atrace-mcp  打包脚本  MCP v{mcp_version}")
    print("==========================================")

    scroll_cfg = CAPTURE_PERFETTO / "scroll.txtpb"
    if not scroll_cfg.is_file():
        raise RuntimeError(f"Missing Perfetto config: {scroll_cfg}")

    print("\n▶ Step 1/4  构建 atrace-tool.jar（./gradlew deployMcp）")
    run(["./gradlew", "deployMcp"], cwd=REPO_ROOT)
    if not JAR_PATH.is_file():
        raise RuntimeError(f"deployMcp finished but jar missing: {JAR_PATH}")
    print(f"   ✓ JAR: {JAR_PATH}")

    print("\n▶ Step 2/4  构建 atrace-capture wheel（config/perfetto/*.txtpb）")
    clean_build_artifacts(CAPTURE_DIR)
    run(["uv", "build"], cwd=CAPTURE_DIR)
    capture_whl = first_match("atrace_capture-*.whl", CAPTURE_DIR / "dist")
    print(f"   ✓ wheel: {capture_whl}")

    print("\n▶ Step 3/4  构建 atrace-mcp wheel（uv build）")
    clean_build_artifacts(MCP_DIR)
    run(["uv", "build"], cwd=MCP_DIR)
    mcp_whl = first_match("atrace_mcp-*.whl", MCP_DIR / "dist")
    print(f"   ✓ wheel: {mcp_whl}")

    print("\n▶ Step 4/4  复制 wheel 到仓库 dist/ 并打 zip")
    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(capture_whl, DIST_ROOT / capture_whl.name)
    shutil.copy2(mcp_whl, DIST_ROOT / mcp_whl.name)
    print(f"   ✓ 已复制: {capture_whl.name} , {mcp_whl.name} → {DIST_ROOT}/")

    zip_name = f"atrace-mcp-v{mcp_version}.zip"
    zip_path = DIST_ROOT / zip_name
    write_zip(zip_path)
    print(f"   ✓ zip:   {zip_path}")

    print("\n==========================================")
    print(" 打包完成")
    print("")
    print(" 目录 zip（解压后根目录须含 platform/atrace-mcp、capture、device、provision、analyzer 与 platform/_monorepo.py；再 uv run --directory …/platform/atrace-mcp）:")
    print(f"   {zip_path}")
    print("")
    print(f" Wheel（已复制到 {DIST_ROOT}/）:")
    print(f"   {capture_whl.name}")
    print(f"   {mcp_whl.name}")
    print("")
    print(" pip 安装（需两者，先 capture）:")
    print(f"   pip install {DIST_ROOT}/atrace_capture-*.whl {DIST_ROOT}/atrace_mcp-*.whl")
    print("")
    print(" 详见 platform/atrace-mcp/README.md「打包与分发」。")
    print("==========================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
