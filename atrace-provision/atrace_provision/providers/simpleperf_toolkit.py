"""AOSP simpleperf toolkit provisioner (app_profiler.py, gecko_profile_generator.py)."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from atrace_provision._adb import device_abi
from atrace_provision._download import CACHE_DIR
from atrace_provision._ndk import find_ndk
from atrace_provision.providers.base import ToolProvider
from atrace_provision.providers.simpleperf import SIMPLEPERF_NDK_PATHS

SIMPLEPERF_REPO_URL = "https://android.googlesource.com/platform/system/extras"


class SimpleperfToolkitProvider(ToolProvider):
    """Provision the AOSP simpleperf Python toolkit.

    Priority:
      1. Bundled ``atrace-mcp/simpleperf_toolkit/simpleperf``
      2. Git clone to ``~/.local/share/atrace/prebuilts/extras/simpleperf``
    """

    def __init__(self, bundled_root: Path | None = None):
        self._bundled_root = bundled_root

    @property
    def name(self) -> str:
        return "simpleperf-toolkit"

    def resolve_host(self) -> Path | None:
        return self.resolve_toolkit()

    def resolve_device(self, serial: str | None = None) -> str | None:
        return None  # host-only

    def resolve_toolkit(self, serial: str | None = None) -> Path | None:
        """Return path to the toolkit root, or None if unavailable."""
        bundled = self._find_bundled()
        if bundled:
            self._populate_bin_from_ndk(bundled, serial)
            abi = device_abi(serial)
            arch = _abi_to_arch(abi)
            if (bundled / "scripts" / "bin" / "android" / arch / "simpleperf").exists():
                return bundled

        return self._clone_to_cache(serial)

    # ── internals ────────────────────────────────────────────

    def _find_bundled(self) -> Path | None:
        if self._bundled_root and (self._bundled_root / "scripts" / "app_profiler.py").exists():
            return self._bundled_root
        return None

    @staticmethod
    def _populate_bin_from_ndk(toolkit_root: Path, serial: str | None = None) -> bool:
        abi = device_abi(serial)
        ndk = find_ndk()
        if not ndk:
            return False
        arch = _abi_to_arch(abi)
        dest_dir = toolkit_root / "scripts" / "bin" / "android" / arch
        dest_bin = dest_dir / "simpleperf"
        if dest_bin.exists():
            return True
        rel = SIMPLEPERF_NDK_PATHS.get(abi)
        if not rel:
            return False
        src = ndk / rel
        if not src.exists():
            return False
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dest_bin)
            dest_bin.chmod(dest_bin.stat().st_mode | stat.S_IEXEC)
            print(f"[provision] Populated simpleperf bin from NDK to {dest_bin}")
            return True
        except OSError:
            return False

    @staticmethod
    def _clone_to_cache(serial: str | None = None) -> Path | None:
        toolkit_root = CACHE_DIR / "extras" / "simpleperf"
        script = toolkit_root / "scripts" / "app_profiler.py"
        if script.exists():
            SimpleperfToolkitProvider._populate_bin_from_ndk(toolkit_root, serial)
            return toolkit_root

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        extras_dir = CACHE_DIR / "extras"
        if extras_dir.exists():
            try:
                shutil.rmtree(extras_dir)
            except OSError:
                pass

        try:
            print("[provision] Cloning AOSP simpleperf toolkit (extras)...")
            r = subprocess.run(
                [
                    "git", "clone", "--depth", "1",
                    "--filter=blob:none", "--sparse",
                    SIMPLEPERF_REPO_URL, str(extras_dir),
                ],
                capture_output=True, text=True, timeout=300,
            )
            if r.returncode == 0:
                subprocess.run(
                    ["git", "sparse-checkout", "set", "simpleperf"],
                    cwd=str(extras_dir), capture_output=True,
                )
            if (toolkit_root / "scripts" / "app_profiler.py").exists():
                SimpleperfToolkitProvider._populate_bin_from_ndk(toolkit_root, serial)
                return toolkit_root
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return None

    # ── runner helpers (kept here for colocation) ─────────────

    @staticmethod
    def run_app_profiler(
        toolkit_root: Path,
        package: str,
        duration_s: int,
        output_perf_path: Path,
        serial: str | None = None,
    ) -> bool:
        env = os.environ.copy()
        if serial:
            env["ANDROID_SERIAL"] = serial
        record_opts = f"-e cpu-clock:u -f 1000 -g --duration {duration_s}"
        cmd = [
            sys.executable,
            str(toolkit_root / "scripts" / "app_profiler.py"),
            "-p", package,
            "-r", record_opts,
            "-o", str(output_perf_path),
            "-nb",
        ]
        r = subprocess.run(
            cmd, cwd=str(toolkit_root), env=env,
            capture_output=True, text=True, timeout=duration_s + 120,
        )
        if r.returncode != 0:
            print(f"[provision] app_profiler.py failed: {r.stderr or r.stdout}")
            return False
        return output_perf_path.exists()

    @staticmethod
    def run_gecko_profile_generator(
        toolkit_root: Path,
        perf_data_path: Path,
        output_gecko_path: Path,
    ) -> bool:
        import gzip

        script = toolkit_root / "scripts" / "gecko_profile_generator.py"
        if not script.exists():
            return False
        cmd = [sys.executable, str(script), "-i", str(perf_data_path)]
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(toolkit_root),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False,
            )
            stdout, stderr = proc.communicate(timeout=60)
            if proc.returncode != 0:
                print(f"[provision] gecko_profile_generator.py failed: {stderr.decode()}")
                return False
            with gzip.open(output_gecko_path, "wb") as f:
                f.write(stdout)
            return output_gecko_path.exists()
        except Exception as e:
            print(f"[provision] gecko_profile_generator: {e}")
            return False


def _abi_to_arch(abi: str) -> str:
    mapping = {
        "arm64-v8a": "arm64",
        "armeabi-v7a": "arm",
        "x86_64": "x86_64",
        "x86": "x86",
    }
    return mapping.get(abi, abi.replace("-", "_"))
