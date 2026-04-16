"""Configuration registry — load presets and custom configs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from atrace_capture.config.schema import CaptureConfig

_PRESETS_DIR = Path(__file__).parent / "presets"
_PERFETTO_DIR = Path(__file__).parent / "perfetto"


class ConfigRegistry:
    """Discover and load capture configuration presets."""

    def __init__(self, extra_dirs: list[Path] | None = None):
        self._dirs = [_PRESETS_DIR]
        if extra_dirs:
            self._dirs.extend(extra_dirs)

    def list_presets(self) -> list[str]:
        names: list[str] = []
        for d in self._dirs:
            if d.is_dir():
                names.extend(f.stem for f in d.glob("*.yaml"))
        return sorted(set(names))

    def load_preset(self, name: str) -> CaptureConfig:
        """Load a preset YAML config by name."""
        import yaml
        for d in self._dirs:
            path = d / f"{name}.yaml"
            if path.is_file():
                data = yaml.safe_load(path.read_text())
                return CaptureConfig(**data)
        raise FileNotFoundError(f"Preset not found: {name} (searched {self._dirs})")

    def get_perfetto_template(self, name: str) -> str | None:
        """Return the content of a Perfetto .txtpb template by name."""
        path = _PERFETTO_DIR / f"{name}.txtpb"
        if path.is_file():
            return path.read_text()
        return None

    def list_perfetto_templates(self) -> list[str]:
        if _PERFETTO_DIR.is_dir():
            return sorted(f.stem for f in _PERFETTO_DIR.glob("*.txtpb"))
        return []
