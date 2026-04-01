"""
ATrace MCP Server — AI Prompt templates.

Provides structured prompts that guide LLM to perform
systematic Android performance analysis.
"""

from fastmcp import FastMCP


def register_prompts(mcp: FastMCP):

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 1. 通用分析入口
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @mcp.prompt
    def analyze_trace(trace_path: str, process_name: str = "", concern: str = "") -> str:
        """Systematic Android trace analysis workflow.

        Args:
            trace_path: Path to the Perfetto trace file
            process_name: Target app process name (e.g. com.example.app)
            concern: What the user is concerned about (e.g. "startup slow", "jank", "ANR")
        """
        return f"""Analyze the Android performance trace at: {trace_path}
Target process: {process_name or "(auto-detect from trace)"}
User concern: {concern or "(general performance review)"}

Follow this systematic workflow:

## Step 1: Load and Overview
- Call `load_trace` with the trace path and process name
- Review the overview: duration, slice count, process list
- Identify the target app process if not specified

## Step 2: Main Thread Health Check
Execute this SQL to get main thread top-level slices:
```sql
SELECT s.name, s.dur/1e6 AS ms, s.id, s.depth
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%{process_name}%'
  AND t.is_main_thread = 1 AND s.dur > 0
ORDER BY s.dur DESC LIMIT 15
```

## Step 3: Identify Problem Category
Based on the results, determine which category to investigate:
- **Startup**: If slow functions are in onCreate/bindApplication/inflate
- **Jank**: If Choreographer frames > 16.6ms
- **Blocking**: If Lock/Binder/GC/IO slices appear on main thread
- **Memory**: If GC pauses are frequent

## Step 4: Deep Dive
For each suspicious slice:
1. Call `slice_children` to see what it's doing internally
2. Call `call_chain` to understand the full call path
3. Use `execute_sql` to cross-reference with thread_state data

## Step 5: Report
Summarize findings with:
- Top 3-5 performance issues ranked by impact
- Root cause for each issue
- Specific optimization suggestions"""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 2. 冷启动分析
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @mcp.prompt
    def startup_analysis(trace_path: str, process_name: str) -> str:
        """Cold startup performance analysis.

        Args:
            trace_path: Path to the Perfetto trace file
            process_name: App process name
        """
        return f"""Analyze the cold startup of {process_name} in trace: {trace_path}

## Step 1: Load trace
Call `load_trace(trace_path="{trace_path}", process_name="{process_name}")`

## Step 2: Find startup phases
Execute SQL to find startup-related slices:
```sql
SELECT s.name, s.dur/1e6 AS ms, s.id, s.depth, s.ts
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%{process_name}%'
  AND t.is_main_thread = 1
  AND (s.name LIKE '%bindApplication%'
       OR s.name LIKE '%Application%onCreate%'
       OR s.name LIKE '%Activity%onCreate%'
       OR s.name LIKE '%Activity%onResume%'
       OR s.name LIKE '%inflate%'
       OR s.name LIKE '%doFrame%'
       OR s.name LIKE '%ContentProvider%'
       OR s.name LIKE '%activityStart%'
       OR s.name LIKE '%reportFullyDrawn%')
ORDER BY s.ts ASC
```

## Step 3: Identify blocking calls during startup
```sql
SELECT s.name, s.dur/1e6 AS ms, s.id
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%{process_name}%'
  AND t.is_main_thread = 1
  AND s.dur > 5000000
  AND (s.name LIKE '%Binder%' OR s.name LIKE '%Lock%'
       OR s.name LIKE '%GC%' OR s.name LIKE '%IO%'
       OR s.name LIKE '%dex%' OR s.name LIKE '%class%init%'
       OR s.name LIKE '%SharedPreferences%'
       OR s.name LIKE '%SQLite%' OR s.name LIKE '%openDatabase%'
       OR s.name LIKE '%loadLibrary%' OR s.name LIKE '%dlopen%')
ORDER BY s.dur DESC LIMIT 20
```

## Step 4: Drill down into the slowest phase
For the slowest phase found, call `slice_children` to see sub-operations.

## Step 5: Check thread scheduling during startup
```sql
SELECT ts.state,
       SUM(ts.dur)/1e6 AS total_ms,
       COUNT(*) AS count
FROM thread_state ts
JOIN thread t ON ts.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%{process_name}%'
  AND t.is_main_thread = 1 AND ts.dur > 0
GROUP BY ts.state ORDER BY total_ms DESC
```

## Step 6: Report
Output a startup timeline:
```
Process start → bindApplication (Xms)
  → Application.onCreate (Xms)
    → ContentProvider.onCreate (Xms) [if any]
  → Activity.onCreate (Xms)
    → inflate (Xms)
  → Activity.onResume (Xms)
  → First frame (Xms)
Total: Xms
```

Key findings:
- Which phase is the bottleneck?
- Any blocking calls (Binder/IO/Lock) on main thread?
- Is the main thread CPU-bound or IO-blocked?
- Optimization suggestions"""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 3. 卡顿分析
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @mcp.prompt
    def jank_analysis(trace_path: str, process_name: str) -> str:
        """Jank frame detection and root cause analysis.

        Args:
            trace_path: Path to the Perfetto trace file
            process_name: App process name
        """
        return f"""Detect and analyze jank frames for {process_name} in trace: {trace_path}

## Step 1: Load trace
Call `load_trace(trace_path="{trace_path}", process_name="{process_name}")`

## Step 2: Find jank frames (>16.6ms)
```sql
SELECT s.name, s.dur/1e6 AS ms, s.id AS slice_id, s.ts
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%{process_name}%'
  AND t.is_main_thread = 1
  AND s.name LIKE 'Choreographer#doFrame%'
  AND s.dur > 16600000
ORDER BY s.dur DESC LIMIT 20
```

## Step 3: For each jank frame, find the root cause
Call `slice_children` for the worst jank frames to see:
- Is it measure/layout/draw that's slow? (traversal)
- Is it animation callback? (animation)
- Is it input handling? (input)

## Step 4: Find main thread blocking during frames
```sql
SELECT s.name, s.dur/1e6 AS ms, s.id
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%{process_name}%'
  AND t.is_main_thread = 1
  AND s.dur > 3000000
  AND (s.name LIKE '%Binder%' OR s.name LIKE '%Lock%'
       OR s.name LIKE '%GC%' OR s.name LIKE '%contention%'
       OR s.name LIKE '%inflate%' OR s.name LIKE '%measure%')
ORDER BY s.dur DESC LIMIT 15
```

## Step 5: Check RenderThread
```sql
SELECT s.name, s.dur/1e6 AS ms, s.id
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%{process_name}%'
  AND t.name LIKE '%RenderThread%'
  AND s.dur > 8000000
ORDER BY s.dur DESC LIMIT 10
```

## Step 6: Report
For each jank frame:
```
Frame #N: XX.Xms (should be <16.6ms)
  Root cause: [GC pause / Binder call / complex layout / ...]
  Recommendation: [specific fix]
```

Summary:
- Total jank frames detected
- Most common jank cause
- Optimization priority list"""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 4. 线程阻塞分析
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @mcp.prompt
    def blocking_analysis(trace_path: str, process_name: str) -> str:
        """Main thread blocking / contention analysis.

        Args:
            trace_path: Path to the Perfetto trace file
            process_name: App process name
        """
        return f"""Analyze main thread blocking for {process_name} in trace: {trace_path}

## Step 1: Load trace
Call `load_trace(trace_path="{trace_path}", process_name="{process_name}")`

## Step 2: Find all blocking calls on main thread
```sql
SELECT s.name, s.dur/1e6 AS ms, s.id,
       CASE
         WHEN s.name LIKE '%Binder%' THEN 'Binder IPC'
         WHEN s.name LIKE '%Lock%' OR s.name LIKE '%contention%' OR s.name LIKE '%Monitor%' THEN 'Lock'
         WHEN s.name LIKE '%GC%' OR s.name LIKE '%concurrent%' THEN 'GC'
         WHEN s.name LIKE '%IO%' OR s.name LIKE '%read%' OR s.name LIKE '%write%' THEN 'IO'
         WHEN s.name LIKE '%dex%' OR s.name LIKE '%class%' THEN 'ClassLoading'
         WHEN s.name LIKE '%SharedPreferences%' THEN 'SharedPrefs'
         WHEN s.name LIKE '%SQLite%' OR s.name LIKE '%Database%' THEN 'Database'
         WHEN s.name LIKE '%sleep%' OR s.name LIKE '%wait%' OR s.name LIKE '%park%' THEN 'Wait'
         ELSE 'Other'
       END AS category
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%{process_name}%'
  AND t.is_main_thread = 1
  AND s.dur > 1000000
  AND (s.name LIKE '%Binder%' OR s.name LIKE '%Lock%'
       OR s.name LIKE '%GC%' OR s.name LIKE '%IO%'
       OR s.name LIKE '%contention%' OR s.name LIKE '%Monitor%'
       OR s.name LIKE '%dex%' OR s.name LIKE '%class%init%'
       OR s.name LIKE '%SharedPreferences%'
       OR s.name LIKE '%SQLite%' OR s.name LIKE '%Database%'
       OR s.name LIKE '%sleep%' OR s.name LIKE '%wait%'
       OR s.name LIKE '%park%' OR s.name LIKE '%dlopen%')
ORDER BY s.dur DESC LIMIT 30
```

## Step 3: Aggregate by category
```sql
SELECT
  CASE
    WHEN s.name LIKE '%Binder%' THEN 'Binder IPC'
    WHEN s.name LIKE '%Lock%' OR s.name LIKE '%contention%' THEN 'Lock Contention'
    WHEN s.name LIKE '%GC%' THEN 'GC'
    WHEN s.name LIKE '%IO%' OR s.name LIKE '%read%' OR s.name LIKE '%write%' THEN 'IO'
    ELSE 'Other'
  END AS category,
  COUNT(*) AS count,
  SUM(s.dur)/1e6 AS total_ms,
  MAX(s.dur)/1e6 AS max_ms,
  AVG(s.dur)/1e6 AS avg_ms
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name LIKE '%{process_name}%'
  AND t.is_main_thread = 1 AND s.dur > 1000000
  AND (s.name LIKE '%Binder%' OR s.name LIKE '%Lock%'
       OR s.name LIKE '%GC%' OR s.name LIKE '%IO%'
       OR s.name LIKE '%contention%')
GROUP BY category ORDER BY total_ms DESC
```

## Step 4: For the worst blockers, trace the call chain
Call `call_chain` on the slice IDs with highest duration.

## Step 5: Check main thread state distribution
Call `thread_states` for the main thread to see Running vs Sleeping vs Blocked.

## Step 6: Report
```
Main Thread Blocking Summary:
  Total blocking time: XXms out of XXms trace duration (XX%)

  By category:
    Binder IPC:       XXms (N calls, max XXms)
    Lock Contention:  XXms (N calls, max XXms)
    GC:               XXms (N calls, max XXms)
    IO:               XXms (N calls, max XXms)

  Top 5 individual blockers:
    1. [name] - XXms - [recommendation]
    2. ...
```"""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 5. 快速健康检查
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @mcp.prompt
    def quick_health_check(trace_path: str) -> str:
        """Quick overall health check of a trace.

        Args:
            trace_path: Path to the Perfetto trace file
        """
        return f"""Perform a quick health check on trace: {trace_path}

## Step 1: Load and overview
Call `load_trace(trace_path="{trace_path}")`
Note the duration, process count, slice count.

## Step 2: Find the user-facing app
```sql
SELECT p.name, p.pid,
       COUNT(s.id) AS slice_count,
       SUM(CASE WHEN t.is_main_thread = 1 THEN 1 ELSE 0 END) AS main_slices
FROM process p
JOIN thread t ON t.upid = p.upid
JOIN thread_track tt ON tt.utid = t.utid
JOIN slice s ON s.track_id = tt.id
WHERE p.name LIKE 'com.%'
  AND p.name NOT LIKE 'com.android.%'
  AND p.name NOT LIKE 'com.google.%'
  AND p.name NOT LIKE 'com.qualcomm.%'
  AND p.name NOT LIKE 'com.qti.%'
  AND p.name NOT LIKE 'com.miui.%'
  AND p.name NOT LIKE 'com.xiaomi.%'
GROUP BY p.name ORDER BY slice_count DESC LIMIT 5
```

## Step 3: Run all checks in parallel
For each app found, gather:

a) **Jank check**: Any Choreographer frames > 16.6ms?
b) **Blocking check**: Any Binder/Lock/GC > 5ms on main thread?
c) **Main thread health**: thread_state distribution

## Step 4: One-page summary
```
Health Report for [trace_path]
Duration: X.Xs | Processes: N | Slices: N

App: [name]
  ✅/⚠️/❌ Frame performance: N jank frames (worst: Xms)
  ✅/⚠️/❌ Main thread blocking: Xms total (Binder/Lock/GC/IO)
  ✅/⚠️/❌ Thread scheduling: X% Running, X% Sleeping, X% Blocked

Recommendations (if any):
  1. ...
  2. ...
```

Use ✅ for good, ⚠️ for warning, ❌ for critical."""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 6. 运行时控制 — 智能抓取
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @mcp.prompt
    def smart_capture(package: str, scenario: str = "general", duration: int = 10) -> str:
        """AI-driven smart trace capture with runtime tuning.

        Args:
            package: App package name (e.g. com.example.app)
            scenario: Scenario type: "startup", "scroll", "general", or custom description
            duration: Trace duration in seconds
        """
        return f"""Perform an intelligent trace capture for {package}.
Scenario: {scenario}
Duration: {duration}s

## Step 1: Pre-flight check
1. Call `list_devices` to verify device connectivity
2. Call `query_app_status` to check if ATrace SDK is active
3. Call `list_plugins` to see which hooks are available

## Step 2: Configure for scenario
Based on scenario type "{scenario}", configure plugins and sampling:

**For startup:**
- Enable all plugins: binder, gc, lock, loadlib, io, msgqueue
- Set high-detail sampling: `set_sampling_interval(main=500000, other=2000000)`
- Will use cold_start

**For scroll/jank:**
- Enable: binder, gc, lock, msgqueue
- Disable heavy plugins: alloc, jni (reduce overhead)
- Default sampling: `set_sampling_interval(main=1000000, other=5000000)`
- Will use scroll scenario

**For general:**
- Enable: binder, gc, lock, io, msgqueue
- Default sampling intervals

## Step 3: Capture (tool names and parameters must match the ATrace MCP server)
**Important:** `capture_trace` **blocks** for the whole `duration_seconds`. For scroll/jank on a **page already open**, use **`inject_scroll=True`** so swipes run **inside** the capture window. Do **not** chain `replay_scenario(scroll)` after `capture_trace` in the same session expecting overlap — that fails because the first call does not return until capture ends.

1. Optional mark: `add_trace_mark(message="capture_start_{scenario}")`
2. By scenario:
   - **startup**: `capture_trace(package="{package}", duration_seconds={duration}, cold_start=True, inject_scroll=False)` (add `activity` if needed)
   - **scroll** (list/feed, app already on target screen): `capture_trace(package="{package}", duration_seconds={duration}, cold_start=False, inject_scroll=True, scroll_repeat=8, scroll_dy=600, scroll_start_x=540, scroll_start_y=1200)` — tune coordinates to the device resolution
   - **general**: `capture_trace(package="{package}", duration_seconds={duration}, cold_start=False, inject_scroll=False)` (user may scroll manually while waiting)

## Step 4: Analyze
1. Call `trace_overview` to get high-level picture
2. Run quick health check
3. Based on findings, decide if recapture with different settings is needed

## Step 5: Report
Provide capture results and initial findings."""

    @mcp.prompt
    def iterative_diagnosis(
        trace_path: str, process_name: str, symptom: str
    ) -> str:
        """Iterative diagnosis workflow: observe → hypothesize → control → verify.

        Args:
            trace_path: Initial trace file path
            process_name: App process name
            symptom: Observed symptom (e.g. "scroll jank", "slow startup", "ANR")
        """
        return f"""Iterative diagnosis for symptom: "{symptom}"
Process: {process_name}
Initial trace: {trace_path}

## Methodology: Observe → Hypothesize → Control → Verify

### Round 1: Observe
1. Load trace: `load_trace("{trace_path}", "{process_name}")`
2. Run appropriate analysis:
   - For jank: `analyze_jank`
   - For startup: `analyze_startup`
   - General: query top slow slices on main thread
3. Check thread states for scheduling issues
4. Check for blocking calls (Binder/Lock/GC/IO)

### Round 2: Hypothesize
Based on observations, form a hypothesis. Examples:
- "Jank is caused by Binder calls on main thread"
- "Startup is slow due to class loading"
- "Lock contention between main and worker threads"

### Round 3: Control (re-capture with targeted config)
Adjust runtime controls to gather more evidence:

**If Binder is suspected:**
```
toggle_plugin("binder", True)
set_sampling_interval(main=500000)  # higher detail
```

**If Lock contention suspected:**
```
toggle_plugin("lock", True)
```

**If IO is suspected:**
```
toggle_plugin("io", True)
```

Then recapture with marks:
```
add_trace_mark("diag_round2_start")
capture_trace(package=..., duration_seconds=10, cold_start=False)
```

### Round 4: Verify
1. Load new trace
2. Check if hypothesis is confirmed
3. If confirmed → report root cause + fix
4. If not → form new hypothesis, go to Round 2

### Output
```
Diagnosis Report for: {symptom}

Round 1 findings: [initial observations]
Hypothesis: [what you think is wrong]
Round 2 config changes: [what plugins/sampling you adjusted]
Round 2 findings: [new evidence]
Root cause: [confirmed cause with trace evidence]
Recommendation: [specific, actionable fix]
```"""

    @mcp.prompt
    def plugin_tuning(package: str) -> str:
        """Guide AI to find optimal plugin configuration for an app.

        Args:
            package: App package name
        """
        return f"""Find the optimal ATrace plugin configuration for {package}.

## Goal
Determine which plugins provide valuable data vs. which add too much overhead,
and find the best sampling interval for this app.

## Step 1: Baseline
1. Check current status: `query_app_status`
2. List current plugins: `list_plugins`
3. Get current sampling config: `get_sampling_config`
4. Capture baseline trace with all default settings: `capture_trace(package="{package}", duration_seconds=5, cold_start=False)`
5. Note: frame times, thread states, buffer usage

## Step 2: Test each plugin individually
For each plugin (binder, gc, lock, jni, loadlib, alloc, msgqueue, io):
1. Disable all other plugins
2. Enable only the test plugin: `toggle_plugin(id, True)`
3. Capture short trace (3s)
4. Measure: does this plugin produce useful data for this app?
5. Note overhead indicators (buffer fill rate, frame drops)

## Step 3: Optimize sampling interval
Test different intervals:
- High detail (500µs main, 2ms other)
- Default (1ms main, 5ms other)
- Low overhead (5ms main, 10ms other)
For each, capture and compare buffer usage and frame impact.

## Step 4: Recommend
```
Optimal Configuration for {package}:
  Plugins: [list of recommended plugins]
  Sampling: main=Xns, other=Xns
  Rationale: [why this config is optimal]
  
  Plugins to avoid: [list with reasons]
  Estimated overhead: ~X%
```"""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 7. 当前页滑动性能 — 采集 + 分析（Cursor / MCP 引导）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @mcp.prompt
    def scroll_performance_workflow(
        package: str,
        duration_seconds: int = 15,
        trace_path: str = "",
        scroll_repeat: int = 8,
        scroll_dy: int = 600,
        scroll_start_x: int = 540,
        scroll_start_y: int = 1200,
        scroll_start_delay_seconds: float = 1.5,
        serial: str = "",
    ) -> str:
        """End-to-end: capture scroll/jank trace (current page open) then analyze with MCP tools.

        Use in Cursor via MCP Prompts, or paste the returned text into the chat so the model
        follows the tool sequence. See atrace-mcp/README.md section on scroll performance.

        Args:
            package: App package name (e.g. com.example.app)
            duration_seconds: Trace length; should cover delay + all swipes + margin (e.g. 12–20)
            trace_path: If non-empty, skip capture and only analyze this merged .perfetto file
            scroll_repeat / scroll_dy / scroll_start_x / scroll_start_y / scroll_start_delay_seconds:
                Passed to `capture_trace` when inject_scroll=True
            serial: ADB serial if multiple devices (empty = default device)
        """
        serial_line = f'Serial: use `serial="{serial}"` on device tools if multiple devices.\n' if serial else ""
        capture_block = f"""## Phase A — Capture (skip if trace already exists)

**Precondition:** User has navigated to the **target scrollable screen** on the device; app is in foreground. **Do not** use `cold_start=True` (that kills the app).

1. `list_devices` — confirm ADB device.
2. `query_app_status` — confirm ATrace HTTP is reachable (port 9090).
3. Optional: `list_plugins` / `toggle_plugin` / `set_sampling_interval` — for scroll, prefer binder+gc+lock+msgqueue; avoid heavy alloc/jni if overhead is high (see project README).
4. Optional: `add_trace_mark` with a short label (e.g. "scroll_perf_start") to align time range in the trace.
5. **Main capture** — call **`capture_trace`** exactly once with:
   - `package="{package}"`
   - `duration_seconds={duration_seconds}`
   - `cold_start=False`
   - `inject_scroll=True`
   - `scroll_start_delay_seconds={scroll_start_delay_seconds}`
   - `scroll_repeat={scroll_repeat}`
   - `scroll_dy={scroll_dy}`
   - `scroll_start_x={scroll_start_x}`
   - `scroll_start_y={scroll_start_y}`
   {serial_line.strip()}

   Read the JSON response: **`merged_trace`** is the merged Perfetto path. Confirm **`inject_scroll_meta`** is present when inject_scroll was used.

**Do not** call `replay_scenario(scenario="scroll")` after `capture_trace` expecting the same recording window — `capture_trace` blocks until done. Use **`inject_scroll=True`** for automated swipes inside the window, or `inject_scroll=False` and ask the user to scroll manually during the wait."""

        if trace_path.strip():
            capture_block = f"""## Phase A — Capture

**Skipped:** User supplied existing trace. Path: `{trace_path.strip()}`"""

        load_path_hint = (
            trace_path.strip()
            if trace_path.strip()
            else "the `merged_trace` string from the `capture_trace` JSON response"
        )

        return f"""You are using the **ATrace MCP** server. Follow this workflow exactly; call tools by their registered names.

**Target app package:** `{package}`
{serial_line}
{capture_block}

## Phase B — Load and analyze

1. If not already loaded from capture response, call `load_trace(trace_path=..., process_name="{package}")` with path = `{load_path_hint}`.

2. `trace_overview` — note duration and slice counts.

3. `analyze_jank` — summarize janky frames and severity for `{package}`.

4. Deep dive (pick as needed):
   - `query_slices` — slow slices on main thread during the scroll interval
   - `execute_sql` — PerfettoSQL on `slice`, `thread_state`, `actual_frame_timeline_slice` (if present)
   - `slice_children` / `call_chain` — for the worst frames or slices

5. Optional: `trace_viewer_hint` — tell the user how to open the `.perfetto` in ui.perfetto.dev.

## Phase C — Report

Output:
- Capture settings used (`inject_scroll`, duration, scroll params or "manual scroll")
- Top jank / frame issues with evidence (slice names, durations)
- Likely root causes (layout, binder, GC, etc.)
- Concrete next steps (code areas to optimize, or recapture with different `scroll_start_x/y`)

**Reference:** Project README — section «场景：当前页滑动性能采集»."""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 8. 自由探索 Prompt
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @mcp.prompt
    def explore_issue(trace_path: str, process_name: str, question: str) -> str:
        """Open-ended performance investigation guided by a specific question.

        Args:
            trace_path: Path to the Perfetto trace file
            process_name: App process name
            question: The specific performance question to investigate
        """
        return f"""Investigate: "{question}"
Trace: {trace_path}
Process: {process_name}

## Approach
You are a performance detective. Use the following tools iteratively:

1. **Start broad**: Use `query_slices` or `execute_sql` to find relevant data
2. **Form hypothesis**: Based on initial data, hypothesize the root cause
3. **Verify**: Use `slice_children`, `call_chain`, or more targeted SQL to confirm
4. **If stuck**: Try different angles:
   - Check thread_states for scheduling issues
   - Look at other threads that might be interacting
   - Search for specific patterns (Binder, Lock, GC, IO)
5. **Iterate**: If first hypothesis is wrong, form a new one

## Available SQL Tables
- `slice`: Function calls (name, dur, ts, track_id, depth, parent_id)
- `thread`: Thread info (utid, tid, name, upid, is_main_thread)
- `process`: Process info (upid, pid, name)
- `thread_track`: Maps tracks to threads
- `thread_state`: Thread scheduling (state: Running/S/D/R, dur, ts)
- `counter`: Time-series metrics (CPU freq, memory)
- `sched`: Kernel scheduling events

## Common Joins
```sql
-- Slice with full context
slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid

-- Thread state with context
thread_state ts
JOIN thread t ON ts.utid = t.utid
```

## Output
Present your findings as:
1. **Investigation steps** (what you looked at and why)
2. **Root cause** (with evidence from the trace data)
3. **Recommendation** (specific, actionable fix)"""
