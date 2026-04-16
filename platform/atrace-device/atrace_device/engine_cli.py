"""EngineCLI — unified dispatcher for atrace-tool CLI subcommands.

All Python ↔ Kotlin interaction flows through this single class.
Protocol: ``atrace-tool --json <subcommand> [args]`` → JSON on stdout.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EngineResult:
    """Structured result from an atrace-tool invocation."""
    status: str = "error"
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    raw_stdout: str = ""
    raw_stderr: str = ""
    returncode: int = -1

    @staticmethod
    def from_json(stdout: str, stderr: str, returncode: int) -> EngineResult:
        stdout = (stdout or "").strip()
        stderr = (stderr or "").strip()
        try:
            data = json.loads(stdout) if stdout else {}
            return EngineResult(
                status=data.get("status", "unknown"),
                data=data,
                raw_stdout=stdout,
                raw_stderr=stderr,
                returncode=returncode,
            )
        except json.JSONDecodeError:
            return EngineResult(
                status="error",
                message="Non-JSON output from atrace-tool",
                data={
                    "stdout_tail": stdout[-2000:],
                    "stderr_tail": stderr[-1000:],
                },
                raw_stdout=stdout,
                raw_stderr=stderr,
                returncode=returncode,
            )

    @property
    def success(self) -> bool:
        return self.status == "success"


class EngineCLI:
    """Dispatch atrace-tool subcommands with JSON protocol."""

    def __init__(self, atrace_tool_cmd: list[str] | None = None, serial: str | None = None):
        self._cmd = atrace_tool_cmd
        self._serial = serial

    @property
    def available(self) -> bool:
        return self._cmd is not None

    def invoke(
        self,
        subcommand: str,
        args: list[str],
        timeout: int = 300,
    ) -> EngineResult:
        if not self._cmd:
            return EngineResult(
                status="error",
                message="atrace-tool not available",
            )

        extra = list(args)
        if self._serial:
            extra = ["-s", self._serial] + extra

        cmd = list(self._cmd) + ["--json", subcommand] + extra
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return EngineResult(
                status="error",
                message=f"atrace-tool {subcommand} timed out after {timeout}s",
            )
        except FileNotFoundError as e:
            return EngineResult(status="error", message=f"atrace-tool not found: {e}")

        return EngineResult.from_json(result.stdout, result.stderr, result.returncode)

    # ── Convenience methods ──────────────────────────────────

    def capture(
        self,
        package: str,
        duration_s: int,
        output_file: str,
        port: int = 9090,
        buffer_size: str = "64mb",
        cold_start: bool = False,
        activity: str | None = None,
        perfetto_config: str | None = None,
        proguard_mapping: str | None = None,
        extra_args: list[str] | None = None,
    ) -> EngineResult:
        args = [
            "-a", package, "-t", str(duration_s),
            "-o", output_file, "-port", str(port), "-b", buffer_size,
        ]
        if cold_start:
            args += ["-r"]
            if activity:
                args += ["-launcher", activity]
        if perfetto_config:
            args += ["-c", perfetto_config]
        if proguard_mapping:
            args += ["-m", proguard_mapping]
        if extra_args:
            args += extra_args

        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        return self.invoke("capture", args, timeout=duration_s + 180)

    def cpu(
        self,
        package: str,
        duration_s: int,
        output_dir: str,
        event: str = "cpu-cycles",
        freq: int = 1000,
        call_graph: str = "dwarf",
    ) -> EngineResult:
        args = [
            "-a", package, "-t", str(duration_s), "-o", output_dir,
            "-e", event, "-f", str(freq), "--call-graph", call_graph,
        ]
        return self.invoke("cpu", args, timeout=duration_s + 60)

    def heap(
        self,
        package: str,
        duration_s: int,
        output_file: str,
        mode: str = "native",
        sampling_bytes: int = 4096,
        no_block: bool = False,
    ) -> EngineResult:
        args = [
            "-a", package, "-t", str(duration_s), "-o", output_file,
            "--mode", mode,
        ]
        if mode == "native":
            args += ["--sampling-bytes", str(sampling_bytes)]
            if no_block:
                args += ["--no-block"]
        return self.invoke("heap", args, timeout=duration_s + 60)

    def devices(self) -> EngineResult:
        return self.invoke("devices", [], timeout=15)
