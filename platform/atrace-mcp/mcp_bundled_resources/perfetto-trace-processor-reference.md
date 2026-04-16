# Perfetto Trace Processor SQL Reference for AI-Driven Trace Analysis

## Table of Contents
1. [Available SQL Tables](#1-available-sql-tables)
2. [Python API Integration](#2-python-api-integration)
3. [Common SQL Queries for Android Performance](#3-common-sql-queries-for-android-performance)
4. [perfetto-mcp Architecture](#4-perfetto-mcp-architecture)
5. [JVM Integration Options](#5-jvm-integration-options)

---

## 1. Available SQL Tables

### Core Event Tables

| Table | Description |
|-------|-------------|
| `slice` | Userspace slices — what threads were doing (atrace, track_event). Columns: `id`, `ts`, `dur`, `track_id`, `category`, `name`, `depth`, `parent_id`, `arg_set_id`, `thread_ts`, `thread_dur` |
| `sched` | Kernel scheduling slices (sched_switch). Columns: `id`, `ts`, `dur`, `utid`, `end_state`, `priority`, `ucpu` |
| `thread_state` | Thread scheduling state over time. Columns: `id`, `ts`, `dur`, `utid`, `state`, `io_wait`, `blocked_function`, `waker_utid`, `waker_id`, `irq_context`, `ucpu` |
| `ftrace_event` | Raw ftrace events (debugging only). Columns: `id`, `ts`, `name`, `utid`, `arg_set_id`, `common_flags`, `ucpu` |
| `counter` | Counter values over time (CPU freq, memory RSS, custom counters). Columns: `id`, `ts`, `track_id`, `value`, `arg_set_id` |
| `flow` | Flow events linking slices. Columns: `id`, `slice_out`, `slice_in`, `arg_set_id` |

### Metadata Tables

| Table | Description |
|-------|-------------|
| `process` | Process information. Key columns: `upid` (unique PID), `pid`, `name`, `start_ts`, `end_ts`, `parent_upid`, `uid`, `cmdline`, `arg_set_id` |
| `thread` | Thread information. Key columns: `utid` (unique TID), `tid`, `name`, `start_ts`, `end_ts`, `upid`, `is_main_thread`, `is_idle` |
| `cpu` | CPU information. Columns: `id`, `machine_id` |
| `cpu_freq` | CPU frequency data. Columns: `ucpu`, joinable with `cpu.id` |
| `machine` | Machine/device metadata: `raw_id`, `sysname`, `release`, `arch`, `num_cpus`, `android_build_fingerprint`, `android_sdk_version`, `system_ram_bytes` |

### Track Tables

| Table | Description |
|-------|-------------|
| `__intrinsic_track` | Base track table. All tracks (thread tracks, process tracks, counter tracks) join here |
| `thread_track` | Tracks associated with a thread. Columns: `id`, `utid` |
| `process_track` | Tracks associated with a process. Columns: `id`, `upid` |
| `cpu_counter_track` | Counter tracks for CPU-specific counters |
| `counter_track` | General counter tracks |

### Callstack Profiling Tables

| Table | Description |
|-------|-------------|
| `stack_profile_mapping` | Binary/library mappings. Columns: `id`, `build_id`, `start`, `end`, `name` |
| `stack_profile_frame` | Stack frames. Columns: `id`, `name`, `mapping`, `rel_pc`, `deobfuscated_name` |
| `stack_profile_callsite` | Callsites (linked list of frames). Columns: `id`, `depth`, `parent_id`, `frame_id` |
| `heap_profile_allocation` | Heap allocations from heapprofd. Columns: `id`, `ts`, `upid`, `heap_name`, `callsite_id`, `count`, `size` |
| `perf_sample` | CPU profile samples from traced_perf. Columns: `id`, `ts`, `utid`, `cpu`, `cpu_mode`, `callsite_id` |
| `cpu_profile_stack_sample` | CPU profiling stack samples |
| `profiler_smaps` | Memory mapping stats from heap profiler |

### Android-Specific Tables

| Table | Description |
|-------|-------------|
| `android_dumpstate` | Dumpsys entries from dumpstate |
| `android_game_intervention_list` | Game mode interventions |
| `package_list` | Installed packages. Joinable from `process.uid` |

### Frame Timeline Tables (via stdlib)

| Table | Description |
|-------|-------------|
| `actual_frame_timeline_slice` | Actual frame rendering timelines (Android 12+). Columns include `jank_type`, `jank_severity_type`, `present_type`, `layer_name` |
| `expected_frame_timeline_slice` | Expected frame deadlines |

### Args Table

| Table | Description |
|-------|-------------|
| `args` | Key-value argument sets. Columns: `id`, `arg_set_id`, `flat_key`, `key`, `value_type`, `int_value`, `string_value`, `real_value` |

### Winscope Tables (SurfaceFlinger/WindowManager)

| Table | Description |
|-------|-------------|
| `surfaceflinger_layers_snapshot` | SF layer snapshots |
| `surfaceflinger_layer` | Individual SF layers |
| `surfaceflinger_transactions` | SF transactions |
| `window_manager_shell_transitions` | Shell transitions |
| `windowmanager` | WM snapshots |
| `protolog` | ProtoLog entries |

---

## 2. Python API Integration

### Installation

```bash
pip install perfetto
```

### Basic Usage

```python
from perfetto.trace_processor import TraceProcessor

# Open a trace file (spawns trace_processor binary automatically)
tp = TraceProcessor(trace='trace.perfetto-trace')

# Run SQL queries
qr_it = tp.query('SELECT ts, dur, name FROM slice')
for row in qr_it:
    print(row.ts, row.dur, row.name)

# Convert to Pandas DataFrame
qr_df = qr_it.as_pandas_dataframe()

# Close when done
tp.close()
```

### Advanced Configuration

```python
from perfetto.trace_processor import TraceProcessor, TraceProcessorConfig, SqlPackage

config = TraceProcessorConfig(
    bin_path='/path/to/trace_processor',  # Custom binary path
    verbose=True,                          # Debug output
    add_sql_packages=[                     # Load PerfettoSQL stdlib modules
        '/path/to/my/sql/modules',
        SqlPackage('/path/to/other', package='custom.pkg')
    ]
)
tp = TraceProcessor(trace='trace.perfetto-trace', config=config)
```

### Connection Options

```python
# From file path
tp = TraceProcessor(trace='trace.perfetto-trace')

# From bytes generator
tp = TraceProcessor(trace=byte_generator)

# From file-like object
tp = TraceProcessor(trace=io.BytesIO(data))

# Connect to running instance (HTTP+RPC mode)
tp = TraceProcessor(addr='localhost:9001')

# Connect and load new trace into running instance
tp = TraceProcessor(trace='trace.perfetto-trace', addr='localhost:9001')
```

### Batch Processing (Multiple Traces)

```python
from perfetto.batch_trace_processor.api import BatchTraceProcessor

files = ['traces/trace1.pftrace', 'traces/trace2.pftrace']
with BatchTraceProcessor(files) as btp:
    results = btp.query('SELECT count(1) FROM slice')
```

### Built-in Metrics

```python
# Pre-baked Android metrics
metrics = tp.metric(['android_cpu'])
print(metrics)

# Trace summary (newer replacement)
spec = """
metric_spec {
    id: "memory_per_process"
    dimensions: "process_name"
    value: "avg_rss_and_swap"
    query: {
        table: {
            table_name: "memory_rss_and_swap_per_process"
            module_name: "linux.memory.process"
        }
        group_by: {
            column_names: "process_name"
            aggregates: {
                column_name: "rss_and_swap"
                op: DURATION_WEIGHTED_MEAN
                result_column_name: "avg_rss_and_swap"
            }
        }
    }
}
"""
summary = tp.trace_summary(specs=[spec])
```

---

## 3. Common SQL Queries for Android Performance

### 3.1 Finding Slow Functions

**Top slow slices by duration:**
```sql
SELECT
    name,
    COUNT(dur) AS count_slice,
    AVG(dur) / 1e6 AS avg_dur_ms,
    CAST(MAX(dur) AS DOUBLE) / 1e6 AS max_dur_ms,
    CAST(MIN(dur) AS DOUBLE) / 1e6 AS min_dur_ms,
    PERCENTILE(dur, 50) / 1e6 AS P50_dur_ms,
    PERCENTILE(dur, 90) / 1e6 AS P90_dur_ms,
    PERCENTILE(dur, 99) / 1e6 AS P99_dur_ms
FROM slice
WHERE name REGEXP '.*interesting_slice.*'
GROUP BY name
ORDER BY P90_dur_ms DESC
LIMIT 20;
```

**Slow functions on the main thread of a specific process:**
```sql
SELECT
    s.id, s.ts, s.dur,
    s.name AS slice_name,
    p.name AS process,
    t.name AS thread,
    CAST(s.dur AS DOUBLE) / 1e6 AS dur_ms
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name = 'com.example.myapp'
    AND t.is_main_thread
    AND s.dur > 16000000  -- >16ms
ORDER BY s.dur DESC
LIMIT 50;
```

**Main thread hotspot slices (top-level only):**
```sql
SELECT
    s.id, s.ts, s.dur,
    s.name AS slice_name,
    CAST(s.dur AS DOUBLE) / 1e6 AS dur_ms,
    s.depth
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name = 'com.example.myapp'
    AND t.is_main_thread
    AND s.depth = 0  -- top-level slices only
    AND s.dur > 8000000  -- >8ms
ORDER BY s.dur DESC;
```

### 3.2 Detecting Jank Frames

**Using the Android Frame Timeline stdlib (Android 12+):**
```sql
INCLUDE PERFETTO MODULE android.frames.timeline;
INCLUDE PERFETTO MODULE android.frames.per_frame_metrics;

SELECT
    af.frame_id,
    CAST(af.ts / 1e6 AS INT) AS timestamp_ms,
    CAST(af.dur / 1e6 AS REAL) AS duration_ms,
    CAST(afo.overrun / 1e6 AS REAL) AS overrun_ms,
    atl.jank_type,
    atl.jank_severity_type,
    CASE
        WHEN android_is_sf_jank_type(atl.jank_type) THEN 'SurfaceFlinger'
        WHEN android_is_app_jank_type(atl.jank_type) THEN 'Application'
        ELSE 'Unknown'
    END AS jank_source,
    CAST(afs.cpu_time / 1e6 AS REAL) AS cpu_time_ms,
    CAST(afs.ui_time / 1e6 AS REAL) AS ui_time_ms,
    atl.layer_name,
    CASE
        WHEN afs.was_huge_jank THEN 'HUGE_JANK'
        WHEN afs.was_big_jank THEN 'BIG_JANK'
        WHEN afs.was_jank THEN 'JANK'
        ELSE 'SMOOTH'
    END AS jank_classification
FROM android_frames af
LEFT JOIN android_frames_overrun afo USING(frame_id)
LEFT JOIN actual_frame_timeline_slice atl
    ON af.ts = atl.ts AND af.process_name = atl.process_name
LEFT JOIN android_frame_stats afs USING(frame_id)
WHERE af.process_name = 'com.example.myapp'
    AND af.dur > 16670000  -- >16.67ms (missed 60fps deadline)
ORDER BY af.dur DESC;
```

**Fallback for older traces (raw frame timeline):**
```sql
SELECT
    a.surface_frame_token AS frame_id,
    CAST(a.ts / 1e6 AS INT) AS timestamp_ms,
    CAST(a.dur / 1e6 AS REAL) AS duration_ms,
    a.jank_type,
    a.jank_severity_type,
    a.present_type,
    a.layer_name
FROM actual_frame_timeline_slice a
JOIN process p ON a.upid = p.upid
WHERE p.name = 'com.example.myapp'
    AND a.dur > 16670000
ORDER BY a.dur DESC;
```

### 3.3 Analyzing Thread Scheduling

**Thread state distribution for a process:**
```sql
SELECT
    t.name AS thread_name,
    ts.state,
    COUNT(*) AS state_count,
    SUM(ts.dur) / 1e6 AS total_dur_ms,
    AVG(ts.dur) / 1e6 AS avg_dur_ms
FROM thread_state ts
JOIN thread t USING (utid)
JOIN process p USING (upid)
WHERE p.name = 'com.example.myapp'
GROUP BY t.name, ts.state
ORDER BY total_dur_ms DESC;
```

**Uninterruptible sleep analysis (D-state):**
```sql
SELECT
    blocked_function,
    COUNT(thread_state.id) AS count,
    SUM(dur) / 1e6 AS total_dur_ms,
    AVG(dur) / 1e6 AS avg_dur_ms
FROM thread_state
JOIN thread USING (utid)
JOIN process USING (upid)
WHERE process.name = 'com.example.myapp'
    AND state = 'D'  -- uninterruptible sleep
GROUP BY blocked_function
ORDER BY total_dur_ms DESC;
```

**CPU scheduling distribution per core:**
```sql
SELECT
    COUNT(*) AS event_count,
    cpu,
    SUM(dur) / 1e6 AS total_runtime_ms
FROM sched
JOIN thread USING (utid)
JOIN process USING (upid)
WHERE process.name = 'com.example.myapp'
GROUP BY cpu
ORDER BY total_runtime_ms DESC;
```

**CPU utilization per process (using stdlib):**
```sql
INCLUDE PERFETTO MODULE linux.cpu.utilization.process;

SELECT
    name AS process_name,
    SUM(megacycles) AS sum_megacycles,
    time_to_ms(SUM(runtime)) AS runtime_msec,
    MIN(min_freq) AS min_freq,
    MAX(max_freq) AS max_freq
FROM cpu_cycles_per_process
JOIN process USING (upid)
WHERE name = 'com.example.myapp'
GROUP BY process_name;
```

**Wakeup chain analysis (who wakes whom):**
```sql
SELECT
    t1.name AS blocked_thread,
    t2.name AS waker_thread,
    p2.name AS waker_process,
    COUNT(*) AS wakeup_count,
    SUM(ts1.dur) / 1e6 AS total_blocked_ms
FROM thread_state ts1
JOIN thread t1 ON ts1.utid = t1.utid
JOIN process p1 ON t1.upid = p1.upid
LEFT JOIN thread t2 ON ts1.waker_utid = t2.utid
LEFT JOIN process p2 ON t2.upid = p2.upid
WHERE p1.name = 'com.example.myapp'
    AND ts1.state IN ('S', 'D')
    AND ts1.waker_utid IS NOT NULL
GROUP BY t1.name, t2.name, p2.name
ORDER BY total_blocked_ms DESC
LIMIT 30;
```

### 3.4 Memory Allocation Tracking

**Heap profile top allocators:**
```sql
SELECT
    spf.name AS function_name,
    SUM(hpa.size) AS total_allocated_bytes,
    SUM(hpa.count) AS total_alloc_count,
    spm.name AS library
FROM heap_profile_allocation hpa
JOIN stack_profile_callsite spc ON hpa.callsite_id = spc.id
JOIN stack_profile_frame spf ON spc.frame_id = spf.id
JOIN stack_profile_mapping spm ON spf.mapping = spm.id
JOIN process p ON hpa.upid = p.upid
WHERE p.name = 'com.example.myapp'
    AND hpa.size > 0  -- only allocations, not frees
GROUP BY spf.name, spm.name
ORDER BY total_allocated_bytes DESC
LIMIT 30;
```

**Memory RSS tracking over time (using stdlib):**
```sql
INCLUDE PERFETTO MODULE android.memory.process;

SELECT
    process_name,
    MAX(anon_rss_and_swap) / 1024.0 AS peak_anon_rss_swap_mb,
    MAX(anon_rss) / 1024.0 AS peak_anon_rss_mb,
    MAX(file_rss) / 1024.0 AS peak_file_rss_mb,
    MAX(swap) / 1024.0 AS peak_swap_mb
FROM memory_oom_score_with_rss_and_swap_per_process
WHERE process_name GLOB 'com.example.myapp*'
GROUP BY process_name;
```

**Memory counters from counter table:**
```sql
SELECT
    c.ts,
    c.value,
    t.name AS counter_name
FROM counter c
JOIN counter_track t ON c.track_id = t.id
WHERE t.name LIKE '%mem%' OR t.name LIKE '%rss%'
ORDER BY c.ts;
```

### 3.5 Binder Transaction Analysis

**Using the android.binder stdlib module:**
```sql
INCLUDE PERFETTO MODULE android.binder;

SELECT
    client_process,
    server_process,
    aidl_name,
    CAST(client_dur / 1e6 AS REAL) AS client_latency_ms,
    CAST(server_dur / 1e6 AS REAL) AS server_latency_ms,
    CAST((client_dur - server_dur) / 1e6 AS REAL) AS overhead_ms,
    is_main_thread,
    is_sync
FROM android_binder_txns
WHERE (client_process = 'com.example.myapp'
    OR server_process = 'com.example.myapp')
    AND client_dur > 10000000  -- >10ms
ORDER BY client_dur DESC;
```

**Binder transactions aggregated by AIDL interface:**
```sql
INCLUDE PERFETTO MODULE android.binder;

SELECT
    aidl_name,
    COUNT(*) AS txn_count,
    CAST(AVG(client_dur) / 1e6 AS REAL) AS avg_client_ms,
    CAST(MAX(client_dur) / 1e6 AS REAL) AS max_client_ms,
    CAST(AVG(server_dur) / 1e6 AS REAL) AS avg_server_ms,
    SUM(CASE WHEN is_main_thread THEN 1 ELSE 0 END) AS main_thread_count
FROM android_binder_txns
WHERE client_process = 'com.example.myapp'
GROUP BY aidl_name
ORDER BY avg_client_ms DESC;
```

**Binder thread state breakdown:**
```sql
INCLUDE PERFETTO MODULE android.binder;

SELECT
    binder_txn_id,
    thread_state_type,
    thread_state,
    SUM(thread_state_dur) / 1e6 AS state_duration_ms
FROM android_sync_binder_thread_state_by_txn
WHERE binder_txn_id IN (
    SELECT binder_txn_id FROM android_binder_txns
    WHERE client_process = 'com.example.myapp'
        AND client_dur > 10000000
)
GROUP BY binder_txn_id, thread_state_type, thread_state
ORDER BY state_duration_ms DESC;
```

**Raw binder slices (without stdlib):**
```sql
SELECT
    s.name AS binder_call,
    p.name AS process,
    t.name AS thread,
    CAST(s.dur / 1e6 AS REAL) AS dur_ms,
    s.ts
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE s.name GLOB 'binder*'
    AND p.name = 'com.example.myapp'
ORDER BY s.dur DESC
LIMIT 50;
```

### 3.6 Monitor Contention (Lock Contention)

```sql
INCLUDE PERFETTO MODULE android.monitor_contention;

SELECT
    process_name,
    blocking_thread_name,
    blocked_thread_name,
    short_blocking_method,
    short_blocked_method,
    CAST(dur / 1e6 AS REAL) AS contention_ms,
    is_blocked_thread_main,
    binder_reply_id
FROM android_monitor_contention
WHERE process_name = 'com.example.myapp'
ORDER BY dur DESC
LIMIT 30;
```

### 3.7 App Startup Analysis

```sql
INCLUDE PERFETTO MODULE android.startup.startups;

SELECT
    startup_id,
    package,
    startup_type,
    CAST(dur / 1e6 AS REAL) AS startup_ms
FROM android_startups
ORDER BY dur DESC;
```

### 3.8 Useful PerfettoSQL Stdlib Modules

Use with `INCLUDE PERFETTO MODULE <module_name>;`

| Module | Key Tables/Views | Purpose |
|--------|-----------------|---------|
| `android.binder` | `android_binder_txns`, `android_sync_binder_thread_state_by_txn` | Binder IPC analysis |
| `android.frames.timeline` | `android_frames`, `android_frames_overrun` | Frame rendering analysis |
| `android.frames.per_frame_metrics` | `android_frame_stats` | Per-frame CPU/UI time |
| `android.memory.process` | `memory_oom_score_with_rss_and_swap_per_process` | Process memory tracking |
| `android.monitor_contention` | `android_monitor_contention` | Lock contention detection |
| `android.startup.startups` | `android_startups`, `android_startup_processes` | App startup events |
| `android.process_metadata` | `android_process_metadata` | Process metadata + package info |
| `android.job_scheduler_states` | `android_job_scheduler_states` | Background job analysis |
| `android.network_packets` | `android_network_packets` | Network traffic per package |
| `linux.cpu.utilization.process` | `cpu_cycles_per_process` | CPU cycles per process |
| `linux.cpu.utilization.slice` | `cpu_cycles_per_thread_slice` | CPU cycles per slice |
| `slices.with_context` | `thread_slice`, `process_slice` | Slices pre-joined with thread/process context |

---

## 4. perfetto-mcp Architecture

### Overview

[perfetto-mcp](https://github.com/antarikshc/perfetto-mcp) is an MCP server that translates natural-language prompts into structured Perfetto trace analyses. It uses the `perfetto` Python package internally.

### Architecture

```
┌─────────────────────────────────────┐
│          MCP Client                 │
│   (Claude, Cursor, VS Code, etc.)  │
└──────────────┬──────────────────────┘
               │ MCP Protocol (stdio)
┌──────────────▼──────────────────────┐
│          server.py                  │
│   MCP Server (registers tools)     │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│     ConnectionManager               │
│  - Persistent TraceProcessor conn   │
│  - Auto-reconnection                │
│  - Thread-safe (threading.Lock)     │
│  - Health checks (SELECT 1)         │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│     perfetto.trace_processor        │
│     TraceProcessor Python API       │
│  (spawns trace_processor binary)    │
└─────────────────────────────────────┘
```

### Tool Structure

All tools inherit from `BaseTool`:

```python
class BaseTool:
    def __init__(self, connection_manager: ConnectionManager): ...

    def execute_with_connection(self, trace_path, operation):
        """Execute op with managed connection + auto-reconnection."""
        tp = self.connection_manager.get_connection(trace_path)
        return operation(tp)

    def run_formatted(self, trace_path, process_name, op) -> str:
        """Run operation, wrap result in JSON envelope."""
        # Returns: {"processName", "tracePath", "success", "error", "result"}
```

### Available Tools

| Tool File | MCP Tool Name | What It Does |
|-----------|--------------|--------------|
| `find_slices.py` | `find_slices` | Survey slice names, find hot paths |
| `sql_query.py` | `execute_sql_query` | Run arbitrary PerfettoSQL |
| `anr_detection.py` | `detect_anrs` | Find ANR events with severity |
| `anr_root_cause.py` | `anr_root_cause_analyzer` | Deep-dive ANR root causes |
| `cpu_utilization.py` | `cpu_utilization_profiler` | Thread-level CPU usage |
| `main_thread_hotspots.py` | `main_thread_hotspot_slices` | Longest main-thread operations |
| `jank_frames.py` | `detect_jank_frames` | Frames missing deadlines |
| `frame_performance_summary.py` | `frame_performance_summary` | Overall frame health metrics |
| `thread_contention_analyzer.py` | `thread_contention_analyzer` | Lock contention bottlenecks |
| `binder_transaction_profiler.py` | `binder_transaction_profiler` | Binder IPC latency analysis |
| `memory_leak_detector.py` | `memory_leak_detector` | Memory growth pattern detection |
| `heap_dominator_tree_analyzer.py` | `heap_dominator_tree_analyzer` | Memory-hogging class analysis |

### Key Design Patterns from perfetto-mcp

1. **Connection pooling**: `ConnectionManager` keeps a single `TraceProcessor` connection alive across multiple tool calls for the same trace file. Switches connections when trace path changes.

2. **Fallback queries**: Tools like `JankFramesTool` try a primary query using stdlib modules first, then fall back to raw table queries if modules are unavailable:
   ```python
   try:
       qr_it = tp.query(primary_sql_with_stdlib)
       frames = collect(qr_it)
   except Exception:
       qr_it = tp.query(fallback_sql_raw_tables)
       frames = collect(qr_it)
   ```

3. **Structured error codes**: Custom `ToolError` exception with codes like `FRAME_DATA_UNAVAILABLE`, `BINDER_DATA_UNAVAILABLE`, `INVALID_PARAMETERS`, `FILE_NOT_FOUND`, `CONNECTION_FAILED`.

4. **JSON envelope**: Every tool returns a consistent envelope:
   ```json
   {
     "processName": "com.example.app",
     "tracePath": "/path/to/trace",
     "success": true,
     "error": null,
     "result": { ... }
   }
   ```

5. **Parameterized tools**: Each tool accepts filters like `time_range`, `min_latency_ms`, `jank_threshold_ms`, `severity_filter`, `group_by` for flexible analysis.

---

## 5. JVM Integration Options

### Can trace_processor be embedded in a JVM process?

**Short answer: No native JVM embedding. Use subprocess or HTTP+RPC.**

The Perfetto trace processor is a **C++ library** with these official bindings:
- **C++**: Direct static library linking (`trace_processor.h`)
- **Python**: Via the `perfetto` pip package (spawns native binary as subprocess)
- **WebAssembly**: For browser-based tools (powers the Perfetto UI)
- **Shell binary**: `trace_processor_shell` standalone executable

There are **no official Java/Kotlin/JVM bindings**.

### Integration Approaches for JVM

#### Option A: Subprocess (Recommended for Android tooling)

Run `trace_processor_shell` as a subprocess and communicate via stdin/stdout:

```kotlin
// Kotlin example
val process = ProcessBuilder(
    "trace_processor_shell",
    "--query-file", queryFile.absolutePath,
    traceFile.absolutePath
).start()
val output = process.inputStream.bufferedReader().readText()
```

#### Option B: HTTP+RPC Mode

Run trace_processor in HTTP daemon mode and communicate via HTTP:

```bash
# Start trace_processor as HTTP server
trace_processor_shell -D --http-port 9001 trace.perfetto-trace
```

```kotlin
// Kotlin: Query via HTTP
val url = URL("http://localhost:9001/query")
val connection = url.openConnection() as HttpURLConnection
connection.requestMethod = "POST"
connection.doOutput = true
// Send protobuf-encoded query (see trace_processor.proto)
```

The RPC protocol is defined in `protos/perfetto/trace_processor/trace_processor.proto`.

#### Option C: Python Bridge from JVM

Use the Python API through a Python subprocess:

```kotlin
val process = ProcessBuilder(
    "python3", "-c", """
import json
from perfetto.trace_processor import TraceProcessor
tp = TraceProcessor(trace='$tracePath')
rows = []
for row in tp.query("$sqlQuery"):
    rows.append(dict(row.__dict__))
print(json.dumps(rows))
tp.close()
""".trimIndent()
).start()
val jsonOutput = process.inputStream.bufferedReader().readText()
```

#### Option D: JNI Bindings (Custom, Complex)

Theoretically possible to create JNI bindings to the C++ `TraceProcessor` class, but:
- Requires building Perfetto from source for your target platform
- Must manage native memory lifecycle carefully
- No official support or examples

### Recommendation for ATrace Project

For an Android performance analysis tool, the best approach is:

1. **Python subprocess** (simplest): Shell out to a Python script that uses the `perfetto` package
2. **HTTP+RPC** (most flexible): Run `trace_processor_shell -D` and query via HTTP — works well for a service architecture
3. **Direct subprocess** (most lightweight): Run `trace_processor_shell --query-file` for one-shot queries

The Python API via subprocess is what perfetto-mcp uses and is the most battle-tested approach.

---

## Appendix: Quick Reference Cheat Sheet

### Essential Table Relationships

```
process.upid ←── thread.upid
thread.utid  ←── thread_track.utid
thread_track.id ←── slice.track_id
thread.utid  ←── thread_state.utid
thread.utid  ←── sched.utid
process.upid ←── heap_profile_allocation.upid
slice.arg_set_id ←── args.arg_set_id
```

### Timestamp Conversions

```sql
-- Perfetto stores timestamps in nanoseconds
ts / 1e6          -- to milliseconds
ts / 1e9          -- to seconds
time_to_ms(ts)    -- stdlib helper function
```

### Common Join Pattern (Slice → Thread → Process)

```sql
SELECT s.*, t.name AS thread_name, p.name AS process_name
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process p ON t.upid = p.upid
WHERE p.name = 'target_process';
```

### Using the Stdlib Shortcut (slices.with_context)

```sql
INCLUDE PERFETTO MODULE slices.with_context;

-- thread_slice already has thread_name, process_name pre-joined
SELECT * FROM thread_slice
WHERE process_name = 'com.example.myapp'
    AND thread_name = 'main'
ORDER BY dur DESC;
```
