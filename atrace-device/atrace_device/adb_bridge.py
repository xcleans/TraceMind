"""ADB bridge — thin wrapper over the ``adb`` command-line tool.

Only exposes operations needed by the capture and control layers.
Does NOT include capture orchestration or analysis logic.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field


@dataclass
class AdbDevice:
    serial: str
    state: str = "device"
    model: str = ""
    transport_id: str = ""


class AdbBridge:
    """Stateless ADB command dispatcher bound to an optional device serial."""

    def __init__(self, serial: str | None = None):
        self.serial = serial

    def run(
        self, *args: str, check: bool = False, timeout: int = 15,
    ) -> subprocess.CompletedProcess[str]:
        cmd = ["adb"]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += list(args)
        try:
            return subprocess.run(
                cmd, capture_output=True, text=True, check=check, timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"adb command timed out after {timeout}s: {' '.join(cmd)}"
            ) from e

    # ── Device discovery ─────────────────────────────────────

    def list_devices(self) -> list[AdbDevice]:
        r = self.run("devices", "-l")
        devices: list[AdbDevice] = []
        for line in r.stdout.strip().splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                serial = parts[0]
                model = ""
                for p in parts[2:]:
                    if p.startswith("model:"):
                        model = p.split(":", 1)[1]
                devices.append(AdbDevice(serial=serial, model=model))
        return devices

    def list_device_serials(self) -> list[str]:
        return [d.serial for d in self.list_devices()]

    # ── Properties ───────────────────────────────────────────

    def getprop(self, key: str) -> str:
        r = self.run("shell", "getprop", key, check=False)
        return r.stdout.strip()

    # ── App lifecycle ────────────────────────────────────────

    def force_stop(self, package: str) -> None:
        self.run("shell", "am", "force-stop", package, check=False)

    def cold_start_app(
        self,
        package: str,
        activity: str | None = None,
        force_stop_wait_ms: int = 500,
    ) -> str:
        self.force_stop(package)
        time.sleep(max(0, force_stop_wait_ms) / 1000.0)
        r = self.run(
            "shell", "monkey", "-p", package, "-c",
            "android.intent.category.LAUNCHER", "1", check=False,
        )
        return r.stdout + r.stderr

    def hot_start_app(self, package: str, home_wait_ms: int = 300) -> str:
        self.run("shell", "input", "keyevent", "KEYCODE_HOME", check=False)
        time.sleep(max(0, home_wait_ms) / 1000.0)
        r = self.run(
            "shell", "monkey", "-p", package, "-c",
            "android.intent.category.LAUNCHER", "1", check=False,
        )
        return r.stdout + r.stderr

    # ── Input ────────────────────────────────────────────────

    def scroll_screen(
        self,
        duration_ms: int = 300,
        dy: int = 500,
        start_x: int = 540,
        start_y: int = 1200,
        end_x: int | None = None,
        end_y: int | None = None,
    ) -> str:
        if end_x is not None and end_y is not None:
            ex, ey = end_x, end_y
        elif end_x is not None or end_y is not None:
            raise ValueError(
                "end_x and end_y must both be set or both omitted"
            )
        else:
            ex, ey = start_x, start_y - dy
        r = self.run(
            "shell", "input", "swipe",
            str(start_x), str(start_y), str(ex), str(ey),
            str(max(1, duration_ms)), check=False,
        )
        return r.stdout or ""

    def tap(self, x: int, y: int) -> str:
        r = self.run("shell", "input", "tap", str(x), str(y), check=False)
        return r.stdout

    # ── Process / activity info ──────────────────────────────

    def get_current_activity(self) -> str:
        r = self.run("shell", "dumpsys", "activity", "activities", check=False)
        for line in r.stdout.split("\n"):
            if "mResumedActivity" in line or "topResumedActivity" in line:
                return line.strip()
        return "unknown"

    def get_pid(self, package: str) -> int | None:
        r = self.run("shell", "pidof", "-s", package, check=False)
        pid_str = r.stdout.strip()
        if pid_str.isdigit():
            return int(pid_str)
        r2 = self.run("shell", "ps", "-e", check=False)
        for line in r2.stdout.splitlines():
            if package in line:
                parts = line.split()
                if len(parts) > 1 and parts[1].isdigit():
                    return int(parts[1])
        return None

    def list_process_threads(self, package: str) -> dict:
        pid = self.get_pid(package)
        if pid is None:
            return {"error": f"Process not found: {package}"}
        r = self.run("shell", "ps", "-T", "-p", str(pid), check=False)
        if r.returncode != 0:
            return {"error": f"ps -T failed: {r.stderr}", "pid": pid}
        lines = (r.stdout or "").strip().split("\n")
        threads = []
        for line in lines:
            parts = line.split(None, 9)
            if len(parts) >= 3:
                tid_str = parts[2]
                name = parts[9] if len(parts) > 9 else ""
                try:
                    tid_int = int(tid_str)
                    threads.append({
                        "tid": tid_int,
                        "name": name.strip(),
                        "is_main": tid_int == pid,
                    })
                except ValueError:
                    pass
        return {
            "package": package, "pid": pid,
            "thread_count": len(threads), "threads": threads,
        }

    # ── Port forwarding ──────────────────────────────────────

    def forward(self, local_port: int, remote_port: int) -> None:
        self.run("forward", f"tcp:{local_port}", f"tcp:{remote_port}")

    def remove_forward(self, local_port: int) -> None:
        self.run("forward", "--remove", f"tcp:{local_port}", check=False)

    def get_http_port_from_content_provider(self, package: str) -> int | None:
        uri = f"content://{package}.atrace/atrace/port"
        r = self.run("shell", "content", "query", "--uri", uri, check=False)
        if r.returncode != 0:
            return None
        m = re.search(r"port=(-?\d+)", r.stdout)
        return int(m.group(1)) if m else None

    # ── File transfer ────────────────────────────────────────

    def push(self, local: str, remote: str) -> bool:
        r = self.run("push", local, remote, check=False)
        return r.returncode == 0

    def pull(self, remote: str, local: str) -> bool:
        r = self.run("pull", remote, local, check=False)
        return r.returncode == 0

    def shell(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.run("shell", *args, check=False)
