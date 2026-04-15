"""tool_provisioner.py — Re-export provisioning API from ``atrace_capture``.

The singleton ``ToolRegistry`` lives in ``atrace_capture.provision_bridge`` so
``atrace-mcp``, ``atrace-service``, and ``DeviceController`` share one discovery
root (monorepo ``atrace-mcp/bin/atrace-tool.jar``, bundled simpleperf).
"""

from __future__ import annotations

from atrace_capture.provision_bridge import (  # noqa: F401
    CACHE_DIR,
    PERFETTO_DEVICE_MANIFEST,
    PERFETTO_VERSION,
    REMOTE_TMP,
    SIMPLEPERF_NDK_PATHS,
    SIMPLEPERF_REPO_URL,
    TRACECONV_MANIFEST,
    atrace_tool_build_hint,
    convert_to_gecko_profile,
    device_info,
    ensure_atrace_tool,
    ensure_perfetto,
    ensure_simpleperf,
    ensure_simpleperf_toolkit,
    find_ndk,
    get_traceconv_host,
    run_app_profiler,
    run_gecko_profile_generator,
)

__all__ = [
    "CACHE_DIR",
    "PERFETTO_VERSION",
    "PERFETTO_DEVICE_MANIFEST",
    "SIMPLEPERF_NDK_PATHS",
    "TRACECONV_MANIFEST",
    "SIMPLEPERF_REPO_URL",
    "REMOTE_TMP",
    "find_ndk",
    "ensure_simpleperf",
    "ensure_simpleperf_toolkit",
    "run_app_profiler",
    "run_gecko_profile_generator",
    "ensure_perfetto",
    "get_traceconv_host",
    "convert_to_gecko_profile",
    "device_info",
    "ensure_atrace_tool",
    "atrace_tool_build_hint",
]
