"""File transfer — download traces from device via ADB or App HTTP."""

from __future__ import annotations

import time
from pathlib import Path

from atrace_device.adb_bridge import AdbBridge
from atrace_device.app_client import AppHttpClient


class FileTransfer:
    """Handles trace file download from device."""

    def __init__(self, adb: AdbBridge, app: AppHttpClient):
        self._adb = adb
        self._app = app

    def download_trace(self, output_dir: str) -> dict[str, str]:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())

        sampling = out / f"sampling_{ts}.perfetto"
        mapping = out / f"sampling_{ts}.perfetto.mapping"

        self._app._download("sampling", str(sampling))
        self._app._download("sampling-mapping", str(mapping))

        return {"sampling": str(sampling), "mapping": str(mapping)}

    def pull_file(self, remote: str, local: str) -> bool:
        return self._adb.pull(remote, local)

    def push_file(self, local: str, remote: str) -> bool:
        return self._adb.push(local, remote)
