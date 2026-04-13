"""Playbook — AI-driven scene briefing for trace analysis.

A Playbook is NOT a fixed pipeline. It describes:
  - What scenario the AI is analyzing
  - Which Perfetto config to use for capture
  - Which MCP tools are available and their purpose
  - Required initial steps (load → basic analysis)
  - Analysis strategy hints (what to focus on, useful SQL, drill-down directions)
  - Expected report structure

The AI receives this as context and decides how to explore, drill deeper,
and generate the report on its own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class CaptureSpec(BaseModel):
    """How to capture a trace for this scenario."""
    config: str = ""
    duration_s: int = 10
    cold_start: bool = False
    inject_scroll: bool = False
    scroll_params: dict[str, Any] = {}
    description: str = ""


class ToolSpec(BaseModel):
    """One MCP tool the AI can use."""
    name: str
    purpose: str = ""


class StrategySection(BaseModel):
    """Analysis strategy hints for the AI."""
    focus_areas: list[str] = []
    sql_patterns: dict[str, str] = {}
    drill_down_hints: list[str] = []
    key_metrics: list[str] = []
    common_root_causes: list[str] = []


class ReportSection(BaseModel):
    """One section the AI should include in its report."""
    title: str
    description: str = ""


class Playbook(BaseModel):
    """Scene briefing that guides AI-driven trace analysis.

    Unlike TaskDefinition (fixed pipeline), a Playbook provides context
    and strategy — the AI decides how to explore and what to report.
    """
    name: str
    description: str = ""
    scenario: str = ""

    capture: CaptureSpec = CaptureSpec()

    tools_required: list[ToolSpec] = Field(default_factory=list)
    tools_recommended: list[ToolSpec] = Field(default_factory=list)
    tools_optional: list[ToolSpec] = Field(default_factory=list)

    initial_steps: list[str] = Field(default_factory=list)

    strategy: StrategySection = StrategySection()

    report_sections: list[ReportSection] = Field(default_factory=list)

    thresholds: dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def from_yaml(path: str | Path) -> Playbook:
        import yaml
        data = yaml.safe_load(Path(path).read_text())
        return Playbook(**data)


_BUILTIN_DIR = Path(__file__).parent / "playbooks"


class PlaybookRegistry:
    """Discover and load playbooks from built-in + user-defined directories.

    Built-in playbooks (in the package) are read-only.
    User-defined playbooks (in ``custom_dir``) can be created, updated, deleted.
    When names collide, user-defined takes precedence.
    """

    def __init__(
        self,
        custom_dir: Path | None = None,
        extra_dirs: list[Path] | None = None,
    ) -> None:
        self._custom_dir = custom_dir
        self._dirs = [_BUILTIN_DIR]
        if custom_dir:
            custom_dir.mkdir(parents=True, exist_ok=True)
            self._dirs.insert(0, custom_dir)
        if extra_dirs:
            self._dirs.extend(extra_dirs)

    @property
    def custom_dir(self) -> Path | None:
        return self._custom_dir

    def list(self) -> list[str]:
        names: set[str] = set()
        for d in self._dirs:
            if d.is_dir():
                names.update(f.stem for f in d.glob("*.yaml"))
        return sorted(names)

    def load(self, name: str) -> Playbook:
        for d in self._dirs:
            path = d / f"{name}.yaml"
            if path.is_file():
                return Playbook.from_yaml(path)
        raise FileNotFoundError(f"Playbook not found: {name}")

    def load_all(self) -> dict[str, Playbook]:
        return {name: self.load(name) for name in self.list()}

    def is_builtin(self, name: str) -> bool:
        return (_BUILTIN_DIR / f"{name}.yaml").is_file()

    def is_custom(self, name: str) -> bool:
        if self._custom_dir is None:
            return False
        return (self._custom_dir / f"{name}.yaml").is_file()

    def save(self, name: str, yaml_content: str) -> Path:
        """Save a user-defined playbook. Validates by parsing first."""
        import yaml as _yaml
        data = _yaml.safe_load(yaml_content)
        Playbook(**data)
        if self._custom_dir is None:
            raise RuntimeError("No custom_dir configured — cannot save playbooks")
        path = self._custom_dir / f"{name}.yaml"
        path.write_text(yaml_content, encoding="utf-8")
        return path

    def delete(self, name: str) -> bool:
        """Delete a user-defined playbook. Returns False if not found or built-in."""
        if self._custom_dir is None:
            return False
        path = self._custom_dir / f"{name}.yaml"
        if path.is_file():
            path.unlink()
            return True
        return False

    def raw_yaml(self, name: str) -> str:
        """Return raw YAML text for a playbook (for editing)."""
        for d in self._dirs:
            path = d / f"{name}.yaml"
            if path.is_file():
                return path.read_text(encoding="utf-8")
        raise FileNotFoundError(f"Playbook not found: {name}")
