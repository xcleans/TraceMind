"""Singleton ``ToolRegistry`` for capture + device flows (shared with MCP shim).

``platform/atrace-mcp/tool_provisioner.py`` re-exports this module so provisioning uses one
registry rooted at the monorepo (``platform/atrace-provision/.../bundled_bin/atrace-tool.jar``, simpleperf under ``bundled_simpleperf/``).
"""

from __future__ import annotations

import sys
from pathlib import Path

from atrace_provision import ToolRegistry
from atrace_provision._download import CACHE_DIR
from atrace_provision._ndk import find_ndk
from atrace_provision.providers.perfetto import PERFETTO_DEVICE_MANIFEST, PERFETTO_VERSION
from atrace_provision.providers.simpleperf import SIMPLEPERF_NDK_PATHS
from atrace_provision.providers.simpleperf_toolkit import SIMPLEPERF_REPO_URL
from atrace_provision.providers.traceconv import TRACECONV_MANIFEST

from .repo_paths import monorepo_root

_root = monorepo_root()
_monorepo_path = _root / "platform" / "_monorepo.py"
if _monorepo_path.is_file():
    _module_dir = _monorepo_path.parent
    if str(_module_dir) not in sys.path:
        sys.path.insert(0, str(_module_dir))
    import _monorepo  # noqa: E402

    _monorepo.bootstrap()

# simpleperf script tree ships inside ``atrace-provision`` (bundled_simpleperf);
# ToolRegistry resolves default via ``bundled_simpleperf_root()`` when None.
_registry = ToolRegistry(project_root=_root, bundled_toolkit=None)

REMOTE_TMP = "/data/local/tmp"


def ensure_simpleperf(serial: str | None = None) -> str:
    return _registry.ensure_simpleperf(serial)


def ensure_simpleperf_toolkit(serial: str | None = None) -> Path | None:
    return _registry.ensure_simpleperf_toolkit(serial)


def run_app_profiler(
    toolkit_root: Path,
    package: str,
    duration_s: int,
    output_perf_path: Path,
    serial: str | None = None,
) -> bool:
    return _registry.run_app_profiler(
        toolkit_root, package, duration_s, output_perf_path, serial
    )


def run_gecko_profile_generator(
    toolkit_root: Path,
    perf_data_path: Path,
    output_gecko_path: Path,
) -> bool:
    return _registry.run_gecko_profile_generator(
        toolkit_root, perf_data_path, output_gecko_path
    )


def ensure_perfetto(serial: str | None = None, force_push: bool = False) -> str:
    return _registry.ensure_perfetto(serial, force_push=force_push)


def get_traceconv_host() -> Path | None:
    return _registry.get_traceconv_host()


def convert_to_gecko_profile(
    perf_data_path: Path,
    output_path: Path,
    serial: str | None = None,
) -> Path | None:
    return _registry.convert_to_gecko_profile(perf_data_path, output_path, serial)


def device_info(serial: str | None = None) -> dict:
    return _registry.device_info(serial)


def ensure_atrace_tool() -> list[str] | None:
    return _registry.ensure_atrace_tool()


def atrace_tool_build_hint() -> str:
    return _registry.atrace_tool_build_hint()


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
