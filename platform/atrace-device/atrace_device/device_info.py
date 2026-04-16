"""Device information — hardware and software metadata."""

from __future__ import annotations

from dataclasses import dataclass

from atrace_device.adb_bridge import AdbBridge


@dataclass
class DeviceInfo:
    serial: str
    model: str
    sdk: str
    android_version: str
    abi: str
    manufacturer: str


def get_device_info(adb: AdbBridge) -> DeviceInfo:
    return DeviceInfo(
        serial=adb.serial or "",
        model=adb.getprop("ro.product.model"),
        sdk=adb.getprop("ro.build.version.sdk"),
        android_version=adb.getprop("ro.build.version.release"),
        abi=adb.getprop("ro.product.cpu.abi"),
        manufacturer=adb.getprop("ro.product.manufacturer"),
    )


def get_device_info_dict(adb: AdbBridge, timeout: int = 10) -> dict[str, str]:
    """Return device info as a plain dict (convenient for JSON serialization)."""
    def _prop(key: str) -> str:
        r = adb.run("shell", "getprop", key, check=False, timeout=timeout)
        return r.stdout.strip()

    return {
        "model": _prop("ro.product.model"),
        "sdk": _prop("ro.build.version.sdk"),
        "android_version": _prop("ro.build.version.release"),
        "abi": _prop("ro.product.cpu.abi"),
        "manufacturer": _prop("ro.product.manufacturer"),
    }
