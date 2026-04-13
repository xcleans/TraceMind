"""Perfetto binary provisioner — download prebuilt and push to device."""

from __future__ import annotations

import stat
from pathlib import Path

from atrace_provision._adb import adb_run, device_abi, push_executable, tool_on_device
from atrace_provision._download import download_cached
from atrace_provision.providers.base import ToolProvider

PERFETTO_VERSION = "v47.0"

REMOTE_TMP = "/data/local/tmp"

PERFETTO_DEVICE_MANIFEST: dict[str, dict[str, str]] = {
    "arm64-v8a": {
        "file_name": "perfetto",
        "url": f"https://commondatastorage.googleapis.com/perfetto-luci-artifacts/{PERFETTO_VERSION}/android-arm64/perfetto",
    },
    "armeabi-v7a": {
        "file_name": "perfetto",
        "url": f"https://commondatastorage.googleapis.com/perfetto-luci-artifacts/{PERFETTO_VERSION}/android-arm/perfetto",
    },
    "x86_64": {
        "file_name": "perfetto",
        "url": f"https://commondatastorage.googleapis.com/perfetto-luci-artifacts/{PERFETTO_VERSION}/android-x64/perfetto",
    },
    "x86": {
        "file_name": "perfetto",
        "url": f"https://commondatastorage.googleapis.com/perfetto-luci-artifacts/{PERFETTO_VERSION}/android-x86/perfetto",
    },
}


class PerfettoProvider(ToolProvider):
    """Provision the ``perfetto`` binary on a connected Android device."""

    @property
    def name(self) -> str:
        return "perfetto"

    def resolve_host(self) -> Path | None:
        return None  # perfetto is a device-side binary

    def resolve_device(
        self,
        serial: str | None = None,
        *,
        force_push: bool = False,
    ) -> str:
        """Ensure perfetto is available on the device.

        When *force_push* is True the binary is always pushed to
        ``/data/local/tmp`` (needed for heapprofd where the system binary
        cannot read configs due to SELinux).
        """
        remote = f"{REMOTE_TMP}/perfetto"

        if not force_push and tool_on_device("perfetto", serial):
            print("[provision] perfetto found on device (system)")
            return "perfetto"

        r = adb_run("shell", "ls", remote, serial=serial)
        if r.returncode == 0:
            print(f"[provision] perfetto already at {remote}")
            return remote

        abi = device_abi(serial)
        entry = PERFETTO_DEVICE_MANIFEST.get(abi)
        if not entry:
            entry = PERFETTO_DEVICE_MANIFEST["arm64-v8a"]
            print(f"[provision] Unknown ABI {abi}, falling back to arm64-v8a")

        cache_name = f"perfetto_{PERFETTO_VERSION}_{abi}"
        print(f"[provision] Downloading perfetto prebuilt for {abi} ({PERFETTO_VERSION})...")
        local = download_cached(cache_name, entry["url"])
        local.chmod(local.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        print(f"[provision] Pushing perfetto to device {remote}")
        if not push_executable(local, remote, serial):
            raise RuntimeError("Failed to push perfetto binary to device")

        return remote
