"""
tool_provisioner.py — Auto-provision simpleperf and perfetto binaries on device.

When the target device is missing simpleperf or perfetto, this module:
  1. Checks the device (adb shell which / adb shell ls)
  2. Looks for the binary in local NDK installation ($ANDROID_NDK_HOME)
  3. Downloads a prebuilt from official GCS / AOSP mirrors if NDK not found
  4. Pushes the binary to /data/local/tmp/ and chmod +x

Reference: tools/cpu_profile and tools/heap_profile from
  https://github.com/google/perfetto (download_or_get_cached pattern)
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

# ── Cache directory (mirrors Perfetto's ~/.local/share/perfetto/prebuilts) ───
CACHE_DIR = Path.home() / ".local" / "share" / "atrace" / "prebuilts"

# ── Perfetto prebuilt version ─────────────────────────────────────────────────
PERFETTO_VERSION = "v47.0"

# Manifest format mirrors tools/cpu_profile / heap_profile amalgamator.
# Each entry: {android_abi, file_name, url, sha256 (optional)}
PERFETTO_DEVICE_MANIFEST: dict[str, dict] = {
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

# traceconv — host-side binary for converting perf.data → gecko profile (Firefox Profiler)
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

# simpleperf prebuilt: available inside Android NDK at known relative paths.
# Not available on a public CDN without NDK download; we locate from NDK.
SIMPLEPERF_NDK_PATHS: dict[str, str] = {
    "arm64-v8a": "prebuilt/android-arm64/simpleperf/simpleperf",
    "armeabi-v7a": "prebuilt/android-arm/simpleperf/simpleperf",
    "x86_64": "prebuilt/android-x86_64/simpleperf/simpleperf",
    "x86": "prebuilt/android-x86/simpleperf/simpleperf",
}

# AOSP simpleperf toolkit (app_profiler.py, gecko_profile_generator.py) — clone full repo.
# Ref: https://profiler.firefox.com/docs/#/./guide-android-profiling
#      https://android.googlesource.com/platform/system/extras/+/master/simpleperf/doc/scripts_reference.md
SIMPLEPERF_REPO_URL = "https://android.googlesource.com/platform/system/extras"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Internal helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _download(url: str, dest: Path, show_progress: bool = True) -> Path:
    """Download url → dest, print progress. Returns dest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    try:
        print(f"  Downloading {url}")
        with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as f:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if show_progress and total:
                    pct = downloaded * 100 // total
                    print(f"\r  Progress: {pct}%", end="", flush=True)
        if show_progress:
            print()
        tmp.rename(dest)
        return dest
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Download failed: {url}: {e}") from e


def _download_cached(name: str, url: str) -> Path:
    """Download to cache dir; skip if already present."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = CACHE_DIR / name
    if dest.exists():
        return dest
    return _download(url, dest)


def _adb(*args: str, serial: str | None = None, check: bool = False) -> subprocess.CompletedProcess:
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _device_abi(serial: str | None = None) -> str:
    r = _adb("shell", "getprop", "ro.product.cpu.abi", serial=serial)
    abi = r.stdout.strip()
    return abi if abi else "arm64-v8a"


def _tool_on_device(tool_name: str, serial: str | None = None) -> bool:
    """Return True if `tool_name` is on PATH on the device."""
    r = _adb("shell", "which", tool_name, serial=serial)
    return r.returncode == 0 and tool_name in r.stdout


def _push_executable(local_path: Path, remote_path: str, serial: str | None = None) -> bool:
    r = _adb("push", str(local_path), remote_path, serial=serial)
    if r.returncode != 0:
        return False
    _adb("shell", "chmod", "+x", remote_path, serial=serial)
    return True


def _find_ndk() -> Path | None:
    for env_var in ("ANDROID_NDK_HOME", "NDK_HOME", "ANDROID_NDK_ROOT"):
        val = os.environ.get(env_var)
        if val and Path(val).is_dir():
            return Path(val)
    # Common install locations
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or ""
    ndk_dir = Path(sdk) / "ndk" if sdk else Path.home() / "Library" / "Android" / "sdk" / "ndk"
    if ndk_dir.is_dir():
        versions = sorted(ndk_dir.iterdir(), reverse=True)
        for v in versions:
            if v.is_dir():
                return v
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Public API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

REMOTE_TMP = "/data/local/tmp"


def ensure_simpleperf(serial: str | None = None) -> str:
    """Ensure simpleperf is available on the device.

    Returns the remote path to use (either the system simpleperf or the
    pushed binary at /data/local/tmp/simpleperf).

    Strategy:
      1. Device already has simpleperf on PATH → use it directly.
      2. NDK found on host → push prebuilt from NDK.
      3. Fallback error with actionable message.
    """
    if _tool_on_device("simpleperf", serial):
        print("[provision] simpleperf found on device (system)")
        return "simpleperf"

    remote = f"{REMOTE_TMP}/simpleperf"

    # Check if already pushed
    r = _adb("shell", "ls", remote, serial=serial)
    if r.returncode == 0:
        print(f"[provision] simpleperf already at {remote}")
        return remote

    abi = _device_abi(serial)
    ndk = _find_ndk()
    if ndk:
        rel = SIMPLEPERF_NDK_PATHS.get(abi)
        if rel:
            ndk_bin = ndk / rel
            if ndk_bin.exists():
                print(f"[provision] Pushing simpleperf from NDK ({ndk_bin})")
                if _push_executable(ndk_bin, remote, serial):
                    return remote

    # Also check NDK simpleperf scripts dir
    if ndk:
        scripts_bin = ndk / "simpleperf" / "bin" / "android" / abi.replace("-", "_") / "simpleperf"
        if scripts_bin.exists():
            print(f"[provision] Pushing simpleperf from NDK scripts ({scripts_bin})")
            if _push_executable(scripts_bin, remote, serial):
                return remote

    raise RuntimeError(
        f"simpleperf not found on device (ABI={abi}) and NDK not available.\n"
        f"Options:\n"
        f"  1. Install Android NDK and set $ANDROID_NDK_HOME\n"
        f"  2. Use a device with API 28+ (simpleperf is pre-installed)\n"
        f"  3. Run: adb push <NDK>/prebuilt/android-{abi.replace('v8a', 'arm64').replace('v7a', 'arm')}"
        f"/simpleperf/simpleperf {remote}"
    )


def _bundled_simpleperf_toolkit() -> Path | None:
    """Return path to bundled simpleperf toolkit if present (atrace-mcp/simpleperf_toolkit/simpleperf)."""
    root = Path(__file__).resolve().parent / "simpleperf_toolkit" / "simpleperf"
    if (root / "scripts" / "app_profiler.py").exists():
        return root
    return None


def _populate_toolkit_bin_from_ndk(toolkit_root: Path, serial: str | None = None) -> bool:
    """Copy simpleperf binaries from NDK to toolkit scripts/bin/android/<arch>/.

    app_profiler.py expects scripts/bin/android/<arch>/simpleperf. Returns True if populated.
    """
    abi = _device_abi(serial)
    ndk = _find_ndk()
    if not ndk:
        return False
    # Map ro.product.cpu.abi to simpleperf arch dir name
    arch_map = {"arm64-v8a": "arm64", "armeabi-v7a": "arm", "x86_64": "x86_64", "x86": "x86"}
    arch = arch_map.get(abi, abi.replace("-", "_"))
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
    import shutil
    try:
        shutil.copy2(src, dest_bin)
        dest_bin.chmod(dest_bin.stat().st_mode | stat.S_IEXEC)
        print(f"[provision] Populated simpleperf bin from NDK to {dest_bin}")
        return True
    except OSError:
        return False


def ensure_simpleperf_toolkit(serial: str | None = None) -> Path | None:
    """Ensure AOSP simpleperf toolkit is available (app_profiler.py, gecko_profile_generator.py).

    Priority:
      1. Bundled atrace-mcp/simpleperf_toolkit/simpleperf (pre-installed, no git)
      2. CACHE_DIR/extras/simpleperf (git clone fallback)
    Binaries (scripts/bin/android/<arch>/simpleperf) are populated from NDK when missing.
    Returns Path to toolkit root, or None if unavailable.
    """
    # 1. Bundled (pre-installed with atrace-mcp)
    bundled = _bundled_simpleperf_toolkit()
    if bundled:
        _populate_toolkit_bin_from_ndk(bundled, serial)
        abi = _device_abi(serial)
        arch_map = {"arm64-v8a": "arm64", "armeabi-v7a": "arm", "x86_64": "x86_64", "x86": "x86"}
        arch = arch_map.get(abi, abi.replace("-", "_"))
        if (bundled / "scripts" / "bin" / "android" / arch / "simpleperf").exists():
            return bundled
        # No NDK or bin missing - fall through to clone or device fallback

    # 2. Clone to cache
    toolkit_root = CACHE_DIR / "extras" / "simpleperf"
    script = toolkit_root / "scripts" / "app_profiler.py"
    if script.exists():
        _populate_toolkit_bin_from_ndk(toolkit_root, serial)
        return toolkit_root

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    extras_dir = CACHE_DIR / "extras"
    if extras_dir.exists():
        import shutil
        try:
            shutil.rmtree(extras_dir)
        except OSError:
            pass

    try:
        print("[provision] Cloning AOSP simpleperf toolkit (extras)...")
        r = subprocess.run(
            ["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", SIMPLEPERF_REPO_URL, str(extras_dir)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if r.returncode == 0:
            subprocess.run(["git", "sparse-checkout", "set", "simpleperf"], cwd=str(extras_dir), capture_output=True)
        if (toolkit_root / "scripts" / "app_profiler.py").exists():
            _populate_toolkit_bin_from_ndk(toolkit_root, serial)
            return toolkit_root
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def run_app_profiler(
    toolkit_root: Path,
    package: str,
    duration_s: int,
    output_perf_path: Path,
    serial: str | None = None,
) -> bool:
    """Run app_profiler.py to record CPU profile (push simpleperf, record, pull perf.data).

    Uses AOSP app_profiler.py; output_perf_path is the host path for perf.data.
    Returns True if perf.data was written to output_perf_path.
    """
    env = os.environ.copy()
    if serial:
        env["ANDROID_SERIAL"] = serial
    # -r: record options; use cpu-clock (works on emulators) and call graph
    record_opts = f"-e cpu-clock:u -f 1000 -g --duration {duration_s}"
    cmd = [
        sys.executable,
        str(toolkit_root / "scripts" / "app_profiler.py"),
        "-p", package,
        "-r", record_opts,
        "-o", str(output_perf_path),
        "-nb",  # skip collecting binaries to speed up
    ]
    r = subprocess.run(cmd, cwd=str(toolkit_root), env=env, capture_output=True, text=True, timeout=duration_s + 120)
    if r.returncode != 0:
        print(f"[provision] app_profiler.py failed: {r.stderr or r.stdout}")
        return False
    return output_perf_path.exists()


def run_gecko_profile_generator(
    toolkit_root: Path,
    perf_data_path: Path,
    output_gecko_path: Path,
) -> bool:
    """Run gecko_profile_generator.py to convert perf.data to Firefox Profiler format."""
    script = toolkit_root / "scripts" / "gecko_profile_generator.py"
    if not script.exists():
        return False
    import gzip
    cmd = [sys.executable, str(script), "-i", str(perf_data_path)]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(toolkit_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
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


def ensure_perfetto(serial: str | None = None, force_push: bool = False) -> str:
    """Ensure perfetto is available on the device.

    Returns the remote path to use (system or /data/local/tmp/perfetto).

    Strategy:
      1. If force_push: always push to REMOTE_TMP (for heapprofd: system binary
         often cannot read config in /data/local/tmp due to SELinux).
      2. Device already has perfetto on PATH → use it.
      3. Download prebuilt from commondatastorage.googleapis.com and push.
    """
    remote = f"{REMOTE_TMP}/perfetto"

    if not force_push and _tool_on_device("perfetto", serial):
        print("[provision] perfetto found on device (system)")
        return "perfetto"

    # Check if already pushed
    r = _adb("shell", "ls", remote, serial=serial)
    if r.returncode == 0:
        print(f"[provision] perfetto already at {remote}")
        return remote

    abi = _device_abi(serial)
    entry = PERFETTO_DEVICE_MANIFEST.get(abi)
    if not entry:
        # Fallback to arm64
        entry = PERFETTO_DEVICE_MANIFEST["arm64-v8a"]
        print(f"[provision] Unknown ABI {abi}, falling back to arm64-v8a")

    cache_name = f"perfetto_{PERFETTO_VERSION}_{abi}"
    print(f"[provision] Downloading perfetto prebuilt for {abi} ({PERFETTO_VERSION})...")
    local = _download_cached(cache_name, entry["url"])
    local.chmod(local.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    print(f"[provision] Pushing perfetto to device {remote}")
    if not _push_executable(local, remote, serial):
        raise RuntimeError("Failed to push perfetto binary to device")

    return remote


def get_traceconv_host() -> Path | None:
    """Download and return path to host-side traceconv binary.

    Used for converting perf.data → gecko profile (Firefox Profiler format)
    and for symbolization. Downloads from GCS prebuilts (same source as
    tools/cpu_profile and tools/heap_profile).

    Returns None if no prebuilt is available for this host platform.
    """
    plat = sys.platform        # "darwin", "linux", "win32"
    machine = platform.machine().lower()  # "x86_64", "arm64", "aarch64"

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
            local = _download_cached(cache_name, entry["url"])
            local.chmod(local.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
            print(f"[provision] traceconv at {local}")
            return local
        except Exception as e:
            print(f"[provision] traceconv download failed: {e}")
            return None

    print(f"[provision] No traceconv prebuilt for {plat}/{machine}")
    return None


def convert_to_gecko_profile(perf_data_path: Path, output_path: Path,
                              serial: str | None = None) -> Path | None:
    """Convert simpleperf perf.data → Firefox Profiler (gecko) JSON.

    Uses traceconv (downloaded via get_traceconv_host) to produce
    a gzip-compressed gecko profile loadable in profiler.firefox.com.

    Steps (mirrors Firefox Profiler guide):
      1. Push perf.data to device, run `simpleperf report-sample --protobuf` → perf.trace
      2. Pull perf.trace to host
      3. Run traceconv to produce gecko JSON

    Returns path to the .json.gz file, or None on failure.
    """
    traceconv = get_traceconv_host()
    if not traceconv:
        return None

    remote_data = f"{REMOTE_TMP}/_conv_perf.data"
    remote_trace = f"{REMOTE_TMP}/_conv_perf.trace"
    simpleperf = ensure_simpleperf(serial)

    # Push perf.data
    _adb("push", str(perf_data_path), remote_data, serial=serial)

    # Convert on device: perf.data → perf.trace (protobuf)
    r = _adb(
        "shell", simpleperf,
        "report-sample", "--show-callchain", "--protobuf",
        "-i", remote_data, "-o", remote_trace,
        serial=serial,
    )
    if r.returncode != 0:
        print(f"[provision] report-sample failed: {r.stderr}")
        return None

    local_trace = output_path.with_suffix(".perf.trace")
    _adb("pull", remote_trace, str(local_trace), serial=serial)
    _adb("shell", "rm", "-f", remote_data, remote_trace, serial=serial)

    if not local_trace.exists():
        return None

    # perf.trace must have content; empty/small often yields "Invalid pprof: empty string table"
    if local_trace.stat().st_size < 64:
        print(f"[provision] perf.trace too small ({local_trace.stat().st_size} bytes), skip traceconv")
        return None

    # Convert perf.trace → gecko JSON using traceconv
    gecko_path = output_path.with_suffix(".json.gz")
    r2 = subprocess.run(
        [str(traceconv), "profile", "--output", str(gecko_path), str(local_trace)],
        capture_output=True, text=True,
    )
    if r2.returncode != 0 or not gecko_path.exists():
        stderr = (r2.stderr or "").strip()
        if "empty string table" in stderr or "Invalid pprof" in stderr:
            print(f"[provision] traceconv failed (no samples/symbols?): {stderr[:200]}")
        else:
            print(f"[provision] traceconv failed: {stderr[:200]}")
        # Do not write gzip(perf.trace) as .json.gz — that is not gecko JSON and can trigger
        # "Invalid pprof: empty string table" when opened in profiler.firefox.com
        return None

    print(f"[provision] Gecko profile: {gecko_path}")
    return gecko_path


def device_info(serial: str | None = None) -> dict:
    """Return a dict with basic device capability info for provisioning decisions."""
    def prop(key: str) -> str:
        r = _adb("shell", "getprop", key, serial=serial)
        return r.stdout.strip()

    abi = prop("ro.product.cpu.abi")
    sdk = prop("ro.build.version.sdk")
    sdk_int = int(sdk) if sdk.isdigit() else 0

    return {
        "abi": abi,
        "sdk": sdk_int,
        "android_version": prop("ro.build.version.release"),
        "has_simpleperf": _tool_on_device("simpleperf", serial),
        "has_perfetto": _tool_on_device("perfetto", serial),
        "simpleperf_needs_push": not _tool_on_device("simpleperf", serial),
        "perfetto_needs_download": not _tool_on_device("perfetto", serial),
        "heapprofd_supported": sdk_int >= 28,
        "ndk_found": str(_find_ndk()) if _find_ndk() else None,
        "cache_dir": str(CACHE_DIR),
    }


# ── atrace-tool JVM binary ─────────────────────────────────────────────────────

def ensure_atrace_tool() -> list[str] | None:
    """Locate the atrace-tool binary or fat-JAR.

    Search order (first match wins):
      1. $ATRACE_TOOL environment variable  — explicit override
      2. <mcp_dir>/bin/atrace-tool.jar      — bundled distribution artifact
         produced by:  ./gradlew deployMcp  (or  ./gradlew :atrace-tool:deployToMcp)
      3. <project_root>/atrace-tool/build/install/atrace-tool/bin/atrace-tool
         produced by:  ./gradlew :atrace-tool:installDist
      4. <project_root>/atrace-tool/build/libs/atrace-tool*.jar
         produced by:  ./gradlew :atrace-tool:jar

    Returns:
      Command token list, e.g. ["/path/to/atrace-tool"] or
      ["java", "-jar", "/path/to/atrace-tool.jar"].
      None if not found anywhere.
    """
    mcp_dir = Path(__file__).resolve().parent
    project_root = mcp_dir.parent

    # 1. Explicit env override
    from_env = os.environ.get("ATRACE_TOOL", "").strip()
    if from_env and Path(from_env).exists():
        return _jar_cmd(Path(from_env))

    # 2. Bundled in atrace-mcp/bin/atrace-tool.jar  (deployMcp artifact — preferred)
    bundled_jar = mcp_dir / "bin" / "atrace-tool.jar"
    if bundled_jar.is_file():
        java = shutil.which("java")
        if java:
            return [java, "-jar", str(bundled_jar)]

    # 3. installDist script (shell wrapper generated by Gradle application plugin)
    install_script = (
        project_root / "atrace-tool" / "build" / "install"
        / "atrace-tool" / "bin" / "atrace-tool"
    )
    if install_script.is_file():
        install_script.chmod(install_script.stat().st_mode | stat.S_IEXEC)
        return [str(install_script)]

    # 4. Fat JAR built locally (build/libs/)
    libs_dir = project_root / "atrace-tool" / "build" / "libs"
    if libs_dir.is_dir():
        jars = sorted(
            libs_dir.glob("atrace-tool*.jar"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if jars:
            java = shutil.which("java")
            if java:
                return [java, "-jar", str(jars[0])]

    return None


def _jar_cmd(jar_path: Path) -> list[str] | None:
    """Return [java, -jar, path] if java is available, else None."""
    java = shutil.which("java")
    if java:
        return [java, "-jar", str(jar_path)]
    return None


def atrace_tool_build_hint() -> str:
    """Return human-readable instructions for building and bundling atrace-tool."""
    project_root = Path(__file__).resolve().parent.parent
    return (
        "atrace-tool not built. Run from the project root:\n"
        "\n"
        "  ./gradlew deployMcp\n"
        "\n"
        "This builds the fat-JAR and copies it to atrace-mcp/bin/atrace-tool.jar.\n"
        "After that, the MCP server is self-contained and can be distributed\n"
        "by copying the atrace-mcp/ directory (including bin/).\n"
        "\n"
        f"Project root: {project_root}"
    )
