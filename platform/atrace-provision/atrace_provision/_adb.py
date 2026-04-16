"""Thin ADB helpers shared across providers.

These are low-level wrappers used only for tool provisioning (checking device
PATH, pushing binaries).  Application-level ADB operations belong in the
atrace-device package.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def adb_run(
    *args: str,
    serial: str | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def device_abi(serial: str | None = None) -> str:
    r = adb_run("shell", "getprop", "ro.product.cpu.abi", serial=serial)
    abi = r.stdout.strip()
    return abi if abi else "arm64-v8a"


def tool_on_device(tool_name: str, serial: str | None = None) -> bool:
    r = adb_run("shell", "which", tool_name, serial=serial)
    return r.returncode == 0 and tool_name in r.stdout


def push_executable(
    local_path: Path, remote_path: str, serial: str | None = None
) -> bool:
    r = adb_run("push", str(local_path), remote_path, serial=serial)
    if r.returncode != 0:
        return False
    adb_run("shell", "chmod", "+x", remote_path, serial=serial)
    return True
