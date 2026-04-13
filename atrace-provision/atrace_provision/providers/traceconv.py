"""Traceconv host-side binary provisioner."""

from __future__ import annotations

import platform
import stat
import sys
from pathlib import Path

from atrace_provision._download import download_cached
from atrace_provision.providers.base import ToolProvider
from atrace_provision.providers.perfetto import PERFETTO_VERSION

TRACECONV_MANIFEST: list[dict] = [
    {
        "platform": "darwin",
        "machine": ["arm64"],
        "file_name": "traceconv",
        "url": f"https://commondatastorage.googleapis.com/perfetto-luci-artifacts/{PERFETTO_VERSION}/mac-arm64/traceconv",
    },
    {
        "platform": "darwin",
        "machine": ["x86_64"],
        "file_name": "traceconv",
        "url": f"https://commondatastorage.googleapis.com/perfetto-luci-artifacts/{PERFETTO_VERSION}/mac-amd64/traceconv",
    },
    {
        "platform": "linux",
        "machine": ["x86_64"],
        "file_name": "traceconv",
        "url": f"https://commondatastorage.googleapis.com/perfetto-luci-artifacts/{PERFETTO_VERSION}/linux-amd64/traceconv",
    },
    {
        "platform": "linux",
        "machine": ["aarch64"],
        "file_name": "traceconv",
        "url": f"https://commondatastorage.googleapis.com/perfetto-luci-artifacts/{PERFETTO_VERSION}/linux-arm64/traceconv",
    },
    {
        "platform": "win32",
        "machine": ["amd64", "x86_64"],
        "file_name": "traceconv.exe",
        "url": f"https://commondatastorage.googleapis.com/perfetto-luci-artifacts/{PERFETTO_VERSION}/windows-amd64/traceconv.exe",
    },
]


class TraceconvProvider(ToolProvider):
    """Provision ``traceconv`` on the host for trace format conversion."""

    @property
    def name(self) -> str:
        return "traceconv"

    def resolve_host(self) -> Path | None:
        plat = sys.platform
        machine = platform.machine().lower()

        for entry in TRACECONV_MANIFEST:
            if entry.get("platform") and entry["platform"] != plat:
                continue
            machines = entry.get("machine", [])
            if machines and machine not in [m.lower() for m in machines]:
                continue
            cache_name = f"traceconv_{PERFETTO_VERSION}_{plat}_{machine}"
            if entry.get("file_name", "").endswith(".exe"):
                cache_name += ".exe"
            try:
                local = download_cached(cache_name, entry["url"])
                local.chmod(
                    local.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
                )
                print(f"[provision] traceconv at {local}")
                return local
            except Exception as e:
                print(f"[provision] traceconv download failed: {e}")
                return None

        print(f"[provision] No traceconv prebuilt for {plat}/{machine}")
        return None

    def resolve_device(self, serial: str | None = None) -> str | None:
        return None  # host-only tool
