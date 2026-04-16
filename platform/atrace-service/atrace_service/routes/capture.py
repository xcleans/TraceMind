"""Device capture endpoints (list devices, capture merged perfetto trace)."""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from atrace_service.engine import TraceAnalyzer, get_analyzer
from atrace_service.models import CaptureTraceRequest, ErrorResponse

log = logging.getLogger("atrace.service.capture")

def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "platform" / "_monorepo.py").is_file():
            return parent
        if (parent / "_monorepo.py").is_file():
            return parent.parent if parent.name == "platform" else parent
    return here.parents[5]


_repo_root = _find_repo_root()
_monorepo_path = _repo_root / "platform" / "_monorepo.py"
if _monorepo_path.is_file():
    _module_dir = _monorepo_path.parent
    if str(_module_dir) not in sys.path:
        sys.path.insert(0, str(_module_dir))
    import _monorepo; _monorepo.bootstrap()  # noqa: E702

from atrace_capture.device_controller import DeviceController  # noqa: E402
from atrace_capture.provision_bridge import (  # noqa: E402
    atrace_tool_build_hint,
    ensure_atrace_tool,
)
from atrace_device import AdbBridge, get_device_info_dict  # noqa: E402



def _resolve_perfetto_config(raw: str | None) -> str | None:
    """Resolve perfetto config name/path to absolute path."""
    if not raw:
        return None
    try:
        return _monorepo.resolve_perfetto_config(raw)  # type: ignore[name-defined]
    except NameError:
        return raw

router = APIRouter(prefix="/capture", tags=["capture"])


def _spawn_scroll_during_capture(
    *,
    serial: str | None,
    delay_seconds: float,
    scroll_repeat: int,
    scroll_dy: int,
    scroll_duration_ms: int,
    scroll_start_x: int,
    scroll_start_y: int,
    scroll_end_x: int | None,
    scroll_end_y: int | None,
    scroll_pause_ms: int,
) -> None:
    """Fire-and-forget thread to inject repeated swipes while capturing."""

    def _worker() -> None:
        time.sleep(max(0.0, delay_seconds))
        adb = AdbBridge(serial=serial)
        n = max(1, scroll_repeat)
        for i in range(n):
            adb.scroll_screen(
                duration_ms=max(1, scroll_duration_ms),
                dy=scroll_dy,
                start_x=scroll_start_x,
                start_y=scroll_start_y,
                end_x=scroll_end_x,
                end_y=scroll_end_y,
            )
            if i < n - 1:
                time.sleep(max(0, scroll_pause_ms) / 1000.0)

    threading.Thread(
        target=_worker,
        daemon=True,
        name="atrace-service-capture-inject-scroll",
    ).start()


@router.get(
    "/devices",
    summary="List connected Android devices via adb",
)
def list_devices() -> dict[str, list[dict[str, Any]]]:
    log.info("GET /capture/devices")
    try:
        adb = AdbBridge()
        serials = adb.list_device_serials()
        items: list[dict[str, Any]] = []
        for serial in serials:
            dev_adb = AdbBridge(serial=serial)
            try:
                info = get_device_info_dict(dev_adb, timeout=5)
            except Exception as e:
                log.warning("get_device_info failed serial=%s: %s", serial, e)
                info = {"error": str(e)}
            info["serial"] = serial
            items.append(info)
        log.info("GET /capture/devices → %d device(s)", len(items))
        return {"devices": items}
    except Exception as exc:
        log.error("GET /capture/devices failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/trace",
    responses={400: {"model": ErrorResponse}},
    summary="Capture merged Perfetto trace and auto-load into current analyzer",
    description=(
        "Captures system + app merged trace via atrace-tool, then auto-loads the generated "
        ".perfetto file into the TraceAnalyzer session map so `/trace/*` and `/analyze/*` "
        "can be called immediately."
    ),
)
def capture_trace(
    body: CaptureTraceRequest,
    analyzer: TraceAnalyzer = Depends(get_analyzer),
) -> dict[str, Any]:
    log.info(
        "POST /capture/trace pkg=%s dur=%ds serial=%s cold=%s scroll=%s",
        body.package, body.duration_seconds, body.serial, body.cold_start, body.inject_scroll,
    )
    if body.inject_scroll and (body.scroll_end_x is None) ^ (body.scroll_end_y is None):
        raise HTTPException(
            status_code=400,
            detail="inject_scroll requires scroll_end_x and scroll_end_y set together, or both omitted",
        )

    try:
        ts = int(time.time())
        out = Path(body.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        output_file = str(out / f"{body.package}_{ts}.perfetto")

        atrace_tool_cmd = ensure_atrace_tool()
        if not atrace_tool_cmd:
            raise HTTPException(status_code=400, detail=atrace_tool_build_hint())

        if body.inject_scroll:
            _spawn_scroll_during_capture(
                serial=body.serial,
                delay_seconds=body.scroll_start_delay_seconds,
                scroll_repeat=body.scroll_repeat,
                scroll_dy=body.scroll_dy,
                scroll_duration_ms=body.scroll_duration_ms,
                scroll_start_x=body.scroll_start_x,
                scroll_start_y=body.scroll_start_y,
                scroll_end_x=body.scroll_end_x,
                scroll_end_y=body.scroll_end_y,
                scroll_pause_ms=body.scroll_pause_ms,
            )

        resolved_config = _resolve_perfetto_config(body.perfetto_config)
        if body.perfetto_config and not resolved_config:
            log.warning("perfetto_config=%r not found, falling back to default", body.perfetto_config)
        elif resolved_config:
            log.info("perfetto_config resolved: %s → %s", body.perfetto_config, resolved_config)

        controller = DeviceController(serial=body.serial, port=body.port, package=body.package)
        result = controller.run_atrace_tool(
            atrace_tool_cmd=atrace_tool_cmd,
            package=body.package,
            duration_s=body.duration_seconds,
            output_file=output_file,
            cold_start=body.cold_start,
            activity=body.activity,
            port=body.port,
            perfetto_config=resolved_config,
            proguard_mapping=body.proguard_mapping,
            buffer_size=body.buffer_size,
        )
        if result.get("status") != "success":
            log.warning("POST /capture/trace failed: %s", result.get("message", result))
            return {
                "status": "error",
                "capture_result": result,
                "build_hint": atrace_tool_build_hint(),
            }

        merged_trace = result.get("merged_trace")
        if not merged_trace:
            raise HTTPException(
                status_code=400,
                detail=f"capture succeeded but merged_trace is missing: {result}",
            )

        overview: dict[str, Any]
        try:
            loaded_path = analyzer.load(merged_trace, process_name=body.package)
            overview = analyzer.overview(loaded_path)
        except Exception as load_exc:  # keep capture success even if local TP fails
            overview = {"error": str(load_exc)}

        log.info(
            "POST /capture/trace → success trace=%s pkg=%s",
            merged_trace, body.package,
        )
        return {
            "status": "success",
            "trace_path": merged_trace,
            "package": body.package,
            "capture_result": result,
            "overview": overview,
        }
    except HTTPException:
        raise
    except Exception as exc:
        log.error("POST /capture/trace failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=400, detail=f"capture failed: {exc}") from exc
