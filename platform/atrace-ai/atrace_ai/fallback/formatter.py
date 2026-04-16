"""ReportFormatter — converts evidence context dicts into Markdown reports.

Two report modes:
  - evidence_report: keyword-targeted analysis (for chat)
  - auto_report: comprehensive analysis (for auto-analyze)
"""

from __future__ import annotations

from typing import Any

_STATE_MAP = {"R": "Running", "S": "Sleeping", "D": "Disk IO",
              "T": "Stopped", "X": "Dead", "Z": "Zombie"}


class ReportFormatter:

    @staticmethod
    def evidence_report(question: str, ctx: dict[str, Any]) -> str:
        overview = ctx.get("overview", {})
        jank = ctx.get("jank", {})
        scroll = ctx.get("scroll", {})
        verdict = scroll.get("verdict", {}) if isinstance(scroll, dict) else {}
        top = ctx.get("top_slices", [])
        drills = ctx.get("drill_down", [])
        blocking = ctx.get("blocking_calls", [])
        thread_st = ctx.get("main_thread_states", [])
        fd = scroll.get("frame_duration", {}) if isinstance(scroll, dict) else {}

        lines: list[str] = ["## 基于 TraceAnalyzer 的深度分析\n"]

        dur = overview.get("duration_ms")
        if dur is not None:
            lines.append(
                f"- Trace 时长 `{dur:.1f}ms`, "
                f"切片 `{overview.get('total_slices', '?')}`, "
                f"线程 `{overview.get('total_threads', '?')}`"
            )

        if verdict:
            lines.append(
                f"- Scroll 评级 **{verdict.get('assessment', '?')}**, "
                f"p95=`{verdict.get('p95_frame_ms', '?')}ms`, "
                f"no_jank=`{verdict.get('no_jank_pct', '?')}%`"
            )

        if isinstance(jank, dict):
            janky = jank.get("janky_frames") or jank.get("jank_frames") or []
            if janky:
                lines.append(f"- Jank 帧: `{len(janky)}`")
        lines.append("")

        if fd:
            lines.append("### 帧耗时分位")
            lines.append("| 指标 | 值 |")
            lines.append("|------|-----|")
            for k in ("p50", "p90", "p95", "p99", "max"):
                lines.append(f"| {k.upper()} | {fd.get(k, '—')}ms |")
            lines.append("")

        if isinstance(top, list) and top:
            lines.append("### 主线程 Top Slices")
            for i, s in enumerate(top[:8]):
                if isinstance(s, dict):
                    sid = s.get("slice_id", "—")
                    d = s.get("dur_ms", 0)
                    lines.append(f"  {i + 1}. `{s.get('name', '?')}` — {d:.2f}ms  (id={sid})")
            lines.append("")

        _append_drill_evidence(lines, drills)
        _append_blocking(lines, blocking)
        _append_thread_states(lines, thread_st)

        lines.append(f"---\n你的问题: {question}\n\n可以继续追问具体函数/线程/slice_id 进一步下钻。")
        return "\n".join(lines)

    @staticmethod
    def auto_report(ctx: dict[str, Any]) -> str:
        return ReportFormatter._direct_auto_report(ctx)

    @staticmethod
    def _direct_auto_report(ctx: dict[str, Any]) -> str:
        overview = ctx.get("overview", {})
        jank = ctx.get("jank", {})
        scroll = ctx.get("scroll", {})
        verdict = scroll.get("verdict", {}) if isinstance(scroll, dict) else {}
        drills = ctx.get("drill_down", [])
        blocking = ctx.get("blocking_calls", [])
        thread_st = ctx.get("main_thread_states", [])
        fd = scroll.get("frame_duration", {}) if isinstance(scroll, dict) else {}

        lines: list[str] = ["## 自动分析报告（TraceAnalyzer 本地引擎）\n"]

        # A. Executive Summary
        lines.append("### A. Executive Summary")
        dur = overview.get("duration_ms")
        if dur is not None:
            lines.append(
                f"- Trace 时长 `{dur:.1f}ms`, "
                f"切片 `{overview.get('total_slices', '?')}`, "
                f"线程 `{overview.get('total_threads', '?')}`"
            )
        if verdict:
            lines.append(
                f"- Scroll 评级 **{verdict.get('assessment', '?')}**, "
                f"no_jank `{verdict.get('no_jank_pct', '?')}%`, "
                f"p95 `{verdict.get('p95_frame_ms', '?')}ms`"
            )
        if isinstance(jank, dict):
            janky = jank.get("janky_frames") or jank.get("jank_frames") or []
            lines.append(f"- Jank 帧数 `{len(janky)}`")
        if isinstance(blocking, list) and blocking:
            total_block = sum(float(b.get("total_ms", 0)) for b in blocking if isinstance(b, dict))
            lines.append(f"- 主线程阻塞总计 `{total_block:.1f}ms`")
        lines.append("")

        # B. Key metrics
        if fd:
            lines.append("### B. 关键指标")
            lines.append("| 指标 | 值 |")
            lines.append("|------|-----|")
            for k in ("p50", "p90", "p95", "p99", "max"):
                lines.append(f"| {k.upper()} | {fd.get(k, '—')}ms |")
            lines.append("")

        # C. Root cause
        lines.append("### C. 根因链路（slice_children 下钻）")
        if drills:
            for i, dr in enumerate(drills[:5]):
                lines.append(
                    f"\n**{i + 1}. `{dr['name']}`** — {dr['dur_ms']:.2f}ms "
                    f"(id={dr['slice_id']}, thread={dr.get('thread', '?')})"
                )
                chain = dr.get("call_chain", [])
                if chain:
                    path = " → ".join(f"`{c.get('name', '?')}`" for c in chain)
                    lines.append(f"  祖先链: {path}")
                kids = dr.get("children", [])
                if kids:
                    for kid in kids:
                        pct = (kid["dur_ms"] / dr["dur_ms"] * 100) if dr["dur_ms"] > 0 else 0
                        lines.append(f"  - `{kid['name']}` {kid['dur_ms']:.2f}ms ({pct:.0f}%)")
                        for gk in kid.get("children", []):
                            lines.append(f"    - `{gk['name']}` {gk['dur_ms']:.2f}ms")
                elif not chain:
                    lines.append("  (无子调用，叶子节点)")
        else:
            lines.append("  (无 top slices 可下钻)")
        lines.append("")

        _append_blocking(lines, blocking)
        _append_thread_states(lines, thread_st)

        # D. Priority
        lines.append("### D. 优化优先级")
        priorities: list[str] = []
        if drills:
            for dr in drills[:3]:
                kids_str = ""
                if dr.get("children"):
                    top_kid = dr["children"][0]
                    kids_str = f"，热点子调用 `{top_kid['name']}` ({top_kid['dur_ms']:.1f}ms)"
                priorities.append(
                    f"排查 `{dr['name']}` ({dr['dur_ms']:.1f}ms){kids_str}"
                )
        if isinstance(blocking, list):
            for b in blocking[:2]:
                if isinstance(b, dict):
                    priorities.append(
                        f"减少 `{b.get('name', '?')}` 主线程阻塞 ({b.get('total_ms', '?')}ms)"
                    )
        for i, p in enumerate(priorities):
            tag = "P0" if i == 0 else ("P1" if i < 3 else "P2")
            lines.append(f"- **{tag}**: {p}")
        if not priorities:
            lines.append("- 数据不足，建议在 SQL 面板进一步下钻。")
        lines.append("")

        # E. Next steps
        lines.append("### E. 下一步")
        lines.append("- 对以上 slice_id 继续追问下钻更深子调用")
        lines.append("- 如果 jank 明显，检查 `Buffer Stuffing` / `App Deadline Missed` 帧段")
        lines.append("- 对比优化前后 trace 量化收益")
        lines.append("- 连接 cursor CLI + MCP 可获得 AI 多步推理分析")

        return "\n".join(lines)


def _append_drill_evidence(lines: list[str], drills: list[dict[str, Any]]) -> None:
    if not drills:
        return
    lines.append("### 下钻证据 (slice_children + call_chain)")
    for dr in drills:
        lines.append(f"\n**`{dr['name']}`** ({dr['dur_ms']:.2f}ms, id={dr['slice_id']})")
        chain = dr.get("call_chain", [])
        if chain:
            path = " → ".join(f"`{c.get('name', '?')}`" for c in chain)
            lines.append(f"  调用链: {path}")
        kids = dr.get("children", [])
        if kids:
            lines.append("  子调用:")
            for kid in kids:
                lines.append(f"    - `{kid['name']}` {kid['dur_ms']:.2f}ms")
                for gk in kid.get("children", []):
                    lines.append(f"      - `{gk['name']}` {gk['dur_ms']:.2f}ms")
    lines.append("")


def _append_blocking(lines: list[str], blocking: list | Any) -> None:
    if not isinstance(blocking, list) or not blocking:
        return
    lines.append("### 主线程阻塞调用 (SQL)")
    for b in blocking[:10]:
        if isinstance(b, dict):
            lines.append(
                f"  - `{b.get('name', '?')}` × {b.get('cnt', '?')} = {b.get('total_ms', '?')}ms"
            )
    lines.append("")


def _append_thread_states(lines: list[str], thread_st: list | Any) -> None:
    if not isinstance(thread_st, list) or not thread_st:
        return
    lines.append("### 主线程状态分布")
    for ts in thread_st:
        if isinstance(ts, dict):
            st = ts.get("state", "?")
            label = _STATE_MAP.get(st, st)
            lines.append(
                f"  - {label}(`{st}`): {ts.get('total_ms', 0):.2f}ms × {ts.get('count', 0)}"
            )
    lines.append("")
