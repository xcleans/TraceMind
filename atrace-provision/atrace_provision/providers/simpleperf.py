"""Simpleperf binary provisioner — locate from NDK and push to device."""

from __future__ import annotations

from pathlib import Path

from atrace_provision._adb import adb_run, device_abi, push_executable, tool_on_device
from atrace_provision._ndk import find_ndk
from atrace_provision.providers.base import ToolProvider

REMOTE_TMP = "/data/local/tmp"

SIMPLEPERF_NDK_PATHS: dict[str, str] = {
    "arm64-v8a": "prebuilt/android-arm64/simpleperf/simpleperf",
    "armeabi-v7a": "prebuilt/android-arm/simpleperf/simpleperf",
    "x86_64": "prebuilt/android-x86_64/simpleperf/simpleperf",
    "x86": "prebuilt/android-x86/simpleperf/simpleperf",
}


class SimpleperfProvider(ToolProvider):
    """Provision ``simpleperf`` on a connected Android device via NDK."""

    @property
    def name(self) -> str:
        return "simpleperf"

    def resolve_host(self) -> Path | None:
        return None  # device-side binary

    def resolve_device(self, serial: str | None = None) -> str:
        """Ensure simpleperf is available on the device.

        Strategy: device PATH → already pushed → NDK push → error.
        """
        if tool_on_device("simpleperf", serial):
            print("[provision] simpleperf found on device (system)")
            return "simpleperf"

        remote = f"{REMOTE_TMP}/simpleperf"

        r = adb_run("shell", "ls", remote, serial=serial)
        if r.returncode == 0:
            print(f"[provision] simpleperf already at {remote}")
            return remote

        abi = device_abi(serial)
        ndk = find_ndk()
        if ndk:
            rel = SIMPLEPERF_NDK_PATHS.get(abi)
            if rel:
                ndk_bin = ndk / rel
                if ndk_bin.exists():
                    print(f"[provision] Pushing simpleperf from NDK ({ndk_bin})")
                    if push_executable(ndk_bin, remote, serial):
                        return remote

            scripts_bin = (
                ndk / "simpleperf" / "bin" / "android"
                / abi.replace("-", "_") / "simpleperf"
            )
            if scripts_bin.exists():
                print(f"[provision] Pushing simpleperf from NDK scripts ({scripts_bin})")
                if push_executable(scripts_bin, remote, serial):
                    return remote

        raise RuntimeError(
            f"simpleperf not found on device (ABI={abi}) and NDK not available.\n"
            f"Options:\n"
            f"  1. Install Android NDK and set $ANDROID_NDK_HOME\n"
            f"  2. Use a device with API 28+ (simpleperf is pre-installed)\n"
            f"  3. Run: adb push <NDK>/prebuilt/android-<arch>/simpleperf/simpleperf {remote}"
        )
