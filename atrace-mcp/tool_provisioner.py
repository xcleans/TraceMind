"""tool_provisioner.py — Compatibility facade.

All provisioning logic has been extracted to the ``atrace-provision`` package.
This module re-exports the public API so existing callers (server.py,
device_controller.py) continue to work without modification.
"""

from __future__ import annotations

import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
_monorepo_path = _repo_root / "_monorepo.py"
if _monorepo_path.is_file():
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    import _monorepo; _monorepo.bootstrap()  # noqa: E702

from atrace_provision import ToolRegistry  # noqa: E402
from atrace_provision._download import CACHE_DIR  # noqa: E402
from atrace_provision.providers.perfetto import PERFETTO_VERSION, PERFETTO_DEVICE_MANIFEST  # noqa: E402
from atrace_provision.providers.simpleperf import SIMPLEPERF_NDK_PATHS  # noqa: E402
from atrace_provision.providers.traceconv import TRACECONV_MANIFEST  # noqa: E402
from atrace_provision.providers.simpleperf_toolkit import SIMPLEPERF_REPO_URL  # noqa: E402
from atrace_provision._ndk import find_ndk as _find_ndk  # noqa: E402

# Singleton registry — mimics the old module-level function API.
_bundled = Path(__file__).resolve().parent / "simpleperf_toolkit" / "simpleperf"
_project = Path(__file__).resolve().parent.parent
_registry = ToolRegistry(
    project_root=_project,
    bundled_toolkit=_bundled if _bundled.is_dir() else None,
)

REMOTE_TMP = "/data/local/tmp"


# ── Re-exported public functions (1:1 with old API) ─────────────

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
