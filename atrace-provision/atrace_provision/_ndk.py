"""NDK discovery helpers."""

from __future__ import annotations

import os
from pathlib import Path


def find_ndk() -> Path | None:
    """Locate the Android NDK on the host.

    Search order: ANDROID_NDK_HOME → NDK_HOME → ANDROID_NDK_ROOT →
    ANDROID_HOME/ndk/<latest> → ~/Library/Android/sdk/ndk/<latest>.
    """
    for env_var in ("ANDROID_NDK_HOME", "NDK_HOME", "ANDROID_NDK_ROOT"):
        val = os.environ.get(env_var)
        if val and Path(val).is_dir():
            return Path(val)

    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or ""
    ndk_dir = Path(sdk) / "ndk" if sdk else Path.home() / "Library" / "Android" / "sdk" / "ndk"
    if ndk_dir.is_dir():
        versions = sorted(ndk_dir.iterdir(), reverse=True)
        for v in versions:
            if v.is_dir():
                return v
    return None
