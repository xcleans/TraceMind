"""Prompt templates for AI trace analysis.

Two generation modes:
  1. from_playbook() — converts a Playbook YAML scene briefing into a rich
     prompt with full context, tools, strategy, and report guidance.
  2. chat() / auto() — lightweight static templates (backward compatible).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from atrace_orchestrator.playbook import Playbook


def _mcp_contract(trace_path: str, process: str | None = None) -> str:
    proc_arg = f', process_name="{process}"' if process else ""
    proc_rule = ""
    if process:
        proc_rule = (
            f'- **process 参数必须使用完整包名 "{process}"**，'
            f'不要缩写、不要截断、不要只传部分字符。\n'
            f'  · load_trace 的 process_name 参数 = "{process}"\n'
            f'  · analyze_startup / analyze_jank / analyze_scroll_performance 的 process 参数 = "{process}"\n'
            f'  · query_slices 的 process 参数 = "{process}"\n'
            f'  · thread_states 等其他工具如需 process 也使用 "{process}"\n'
        )
    return (
        "参数契约（必须严格遵守，违反会导致分析失败）：\n"
        f'- 第一个工具调用必须是 load_trace(trace_path="{trace_path}"{proc_arg})。\n'
        f'- 后续每一个 MCP 工具调用都必须显式带 trace_path="{trace_path}"。\n'
        f'{proc_rule}'
        "- 参数名必须与 MCP schema 完全一致：\n"
        "  · load_trace 用 process_name（不是 process）\n"
        "  · analyze_startup / analyze_jank / analyze_scroll_performance 用 process（不是 process_name）\n"
        "- 若任一工具返回 \"missing trace_path\" / \"required argument\"，\n"
        "  立刻重试并补齐完整参数，不要继续空参调用。\n"
    )


class PromptBuilder:
    """Construct analysis prompts — static templates or Playbook-driven."""

    # ── Playbook-driven prompt ────────────────────────────────

    @staticmethod
    def from_playbook(
        playbook: Playbook,
        trace_path: str,
        process: str | None = None,
        extra_context: str | None = None,
    ) -> str:
        """Convert a Playbook scene briefing into a full AI prompt.

        The generated prompt gives the AI:
          - Scene context and goal
          - MCP parameter contract
          - Available tools and their purpose
          - Required initial steps
          - Analysis strategy hints (focus areas, SQL, drill-down)
          - Expected report structure and thresholds
          - Freedom to explore beyond the hints
        """
        parts: list[str] = []
        proc = process or "(未指定)"

        # Header
        parts.append(f"# 场景：{playbook.description.strip()}\n")
        parts.append(f"**Trace 文件**: {trace_path}")
        parts.append(f"**目标进程**: {proc}")
        parts.append(f"**场景类型**: {playbook.scenario}\n")

        # MCP contract
        parts.append(_mcp_contract(trace_path, process))

        # Capture context
        if playbook.capture.description:
            parts.append("## 采集配置说明\n")
            parts.append(playbook.capture.description.strip())
            parts.append("")

        # Available tools
        parts.append("## 可用工具\n")

        if playbook.tools_required:
            parts.append("### 必须使用")
            for t in playbook.tools_required:
                parts.append(f"- **{t.name}**: {t.purpose.strip()}")
            parts.append("")

        if playbook.tools_recommended:
            parts.append("### 建议使用（根据分析需要选择）")
            for t in playbook.tools_recommended:
                parts.append(f"- **{t.name}**: {t.purpose.strip()}")
            parts.append("")

        if playbook.tools_optional:
            parts.append("### 可选")
            for t in playbook.tools_optional:
                parts.append(f"- **{t.name}**: {t.purpose.strip()}")
            parts.append("")

        # Initial steps
        if playbook.initial_steps:
            parts.append("## 初始步骤（必须先完成）\n")
            for i, step in enumerate(playbook.initial_steps, 1):
                parts.append(f"{i}. {step}")
            parts.append("")

        # Strategy
        strat = playbook.strategy
        if strat.focus_areas or strat.sql_patterns or strat.drill_down_hints:
            parts.append("## 分析策略提示\n")
            parts.append("以下是分析方向的参考，你可以且应该根据实际数据灵活调整，"
                         "不必拘泥于这些提示。发现新问题时请深入探索。\n")

        if strat.focus_areas:
            parts.append("### 重点关注方向")
            for area in strat.focus_areas:
                parts.append(f"- {area}")
            parts.append("")

        if strat.key_metrics:
            parts.append("### 关键指标")
            for m in strat.key_metrics:
                parts.append(f"- {m}")
            parts.append("")

        if strat.sql_patterns:
            parts.append("### 参考 SQL 模式")
            parts.append("你可以使用 execute_sql 执行以下 SQL（{process} 替换为实际进程名），"
                         "也可以自行编写更精确的查询：\n")
            for name, sql in strat.sql_patterns.items():
                parts.append(f"**{name}**:")
                parts.append(f"```sql\n{sql.strip()}\n```")
            parts.append("")

        if strat.drill_down_hints:
            parts.append("### 下钻方向")
            for hint in strat.drill_down_hints:
                parts.append(f"- {hint}")
            parts.append("")

        if strat.common_root_causes:
            parts.append("### 常见根因（参考）")
            for cause in strat.common_root_causes:
                parts.append(f"- {cause}")
            parts.append("")

        # Thresholds
        if playbook.thresholds:
            parts.append("## 阈值参考\n")
            for k, v in playbook.thresholds.items():
                parts.append(f"- {k}: {v}")
            parts.append("")

        # Report structure
        if playbook.report_sections:
            parts.append("## 报告结构要求\n")
            parts.append("请按以下结构输出分析报告：\n")
            for sec in playbook.report_sections:
                desc = f" — {sec.description}" if sec.description else ""
                parts.append(f"### {sec.title}{desc}")
            parts.append("")

        # Ground rules
        parts.append("## 核心原则\n")
        parts.append("- 所有结论必须绑定到具体指标和 trace 证据（slice_id / SQL 结果），"
                      "不要只给经验判断。")
        parts.append("- 如果初始步骤的数据不足以解释问题，你应该主动使用 execute_sql、"
                      "slice_children、call_chain 等工具深入探索。")
        parts.append("- 不要局限于上面的提示。如果你发现了提示中未提到的问题，"
                      "也请深入分析并加入报告。")
        parts.append("- 若某一工具调用失败，说明失败原因并继续执行可完成的步骤。")
        parts.append("- 回答语言使用中文。")

        if extra_context:
            parts.append(f"\n## 补充上下文\n\n{extra_context}")

        return "\n".join(parts)

    # ── Legacy static templates ───────────────────────────────

    @staticmethod
    def chat(
        trace_path: str,
        question: str,
        process: str | None = None,
    ) -> str:
        proc_hint = process or "(未指定)"
        return (
            f"Trace 文件: {trace_path}\n"
            f"应用进程: {proc_hint}\n\n"
            + _mcp_contract(trace_path, process)
            + f"\n用户问题：{question}\n\n"
            "要求：\n"
            "- 使用 MCP 工具（execute_sql / analyze_startup / analyze_jank / "
            "analyze_scroll_performance / slice_children 等）获取证据后再回答。\n"
            "- 不要只给经验判断，必须绑定到具体指标和 slice 名称。\n"
            "- 如果需要下钻，直接调用 slice_children。\n"
            "- 回答语言与用户问题一致。"
        )

    @staticmethod
    def auto(
        trace_path: str,
        process: str | None = None,
        layer_hint: str | None = None,
        playbook_name: str | None = None,
    ) -> str:
        """Generate auto-analysis prompt.

        If playbook_name is given and atrace-orchestrator is available,
        loads the Playbook YAML and generates a rich context prompt.
        Otherwise falls back to the static template.
        """
        if playbook_name:
            pb = _try_load_playbook(playbook_name)
            if pb is not None:
                return PromptBuilder.from_playbook(pb, trace_path, process)

        proc = process or ""
        layer_arg = f', layer_name_hint="{layer_hint}"' if layer_hint else ""
        load_call = (
            f'load_trace(trace_path="{trace_path}", process_name="{proc}")'
            if proc else
            f'load_trace(trace_path="{trace_path}")'
        )
        return (
            "请执行\"自动AI性能分析\"，并给出可执行结论。\n\n"
            f"输入信息：\n"
            f"- trace 文件: {trace_path}\n"
            f"- 分析目标进程: {proc or '(未指定)'}\n\n"
            + _mcp_contract(trace_path, process)
            + "\n要求：\n"
            "- 必须按步骤调用工具获取证据，不要只给经验判断。\n"
            "- 若某一步失败，说明失败原因并继续执行可完成的步骤。\n"
            "- 所有结论都要绑定到具体指标。\n\n"
            "执行步骤：\n"
            f"1. 调用 {load_call} 加载 trace。\n"
            f'2. 调用 analyze_startup(trace_path="{trace_path}", '
            f'process="{proc}")。\n'
            f'3. 调用 analyze_jank(trace_path="{trace_path}", '
            f'process="{proc}")。\n'
            f'4. 调用 analyze_scroll_performance(trace_path="{trace_path}", '
            f'process="{proc}"{layer_arg})。\n'
            "5. 额外执行 2 条 SQL（execute_sql）补充证据：\n"
            f"   - 主线程 Top slices（按 dur 降序，过滤 {proc}）\n"
            "   - 主要阻塞（binder/gc/lock/io）按总耗时汇总\n"
            "6. 输出\"自动分析报告\"，结构固定为：\n"
            "    A. Executive Summary（3~5 条）\n"
            "    B. 关键指标表（startup / jank / scroll）\n"
            "    C. 根因链路（现象 → 指标 → 可疑函数/线程 → 证据）\n"
            "    D. 优化优先级（P0/P1/P2，每项含收益预估与验证方法）\n"
            "    E. 下一轮采集建议（如果证据不足）"
        )


def _try_load_playbook(name: str) -> Any:
    """Attempt to load a Playbook from atrace-orchestrator.

    Returns Playbook or None if the package is unavailable.
    """
    try:
        from atrace_orchestrator.playbook import PlaybookRegistry
        registry = PlaybookRegistry()
        return registry.load(name)
    except (ImportError, FileNotFoundError):
        return None
