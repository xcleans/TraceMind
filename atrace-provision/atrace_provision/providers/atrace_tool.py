"""atrace-tool JVM CLI provisioner."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from atrace_provision.providers.base import ToolProvider


class AtraceToolProvider(ToolProvider):
    """Locate the ``atrace-tool`` fat-JAR or install script.

    Search order:
      1. ``$ATRACE_TOOL`` env override
      2. ``<mcp_dir>/bin/atrace-tool.jar`` (``./gradlew deployMcp`` artifact)
      3. ``<project>/atrace-tool/build/install/atrace-tool/bin/atrace-tool``
      4. ``<project>/atrace-tool/build/libs/atrace-tool*.jar``
    """

    def __init__(self, project_root: Path | None = None):
        self._project_root = project_root

    @property
    def name(self) -> str:
        return "atrace-tool"

    def _guess_project_root(self) -> Path:
        if self._project_root:
            return self._project_root
        return Path(__file__).resolve().parents[3]

    def resolve_host(self) -> Path | None:
        cmd = self.resolve_command()
        if cmd is None:
            return None
        return Path(cmd[-1])

    def resolve_device(self, serial: str | None = None) -> str | None:
        return None  # host-only JVM tool

    def resolve_command(self) -> list[str] | None:
        """Return the command tokens to invoke atrace-tool, or None."""
        project_root = self._guess_project_root()
        mcp_dir = project_root / "atrace-mcp"

        from_env = os.environ.get("ATRACE_TOOL", "").strip()
        if from_env and Path(from_env).exists():
            return _jar_cmd(Path(from_env))

        bundled_jar = mcp_dir / "bin" / "atrace-tool.jar"
        if bundled_jar.is_file():
            java = shutil.which("java")
            if java:
                return [java, "-jar", str(bundled_jar)]

        install_script = (
            project_root / "atrace-tool" / "build" / "install"
            / "atrace-tool" / "bin" / "atrace-tool"
        )
        if install_script.is_file():
            install_script.chmod(install_script.stat().st_mode | stat.S_IEXEC)
            return [str(install_script)]

        libs_dir = project_root / "atrace-tool" / "build" / "libs"
        if libs_dir.is_dir():
            jars = sorted(
                libs_dir.glob("atrace-tool*.jar"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if jars:
                java = shutil.which("java")
                if java:
                    return [java, "-jar", str(jars[0])]

        return None

    @staticmethod
    def build_hint() -> str:
        return (
            "atrace-tool not built. Run from the project root:\n\n"
            "  ./gradlew deployMcp\n\n"
            "This builds the fat-JAR and copies it to atrace-mcp/bin/atrace-tool.jar."
        )


def _jar_cmd(jar_path: Path) -> list[str] | None:
    java = shutil.which("java")
    if java:
        return [java, "-jar", str(jar_path)]
    return None
