# ATrace MCP 效果样例

参考：[atrace-mcp/README.md](../atrace-mcp/README.md)

---

## 1. 冷启动抓取与分析

### `capture_trace`

| 参数 | 值 |
|------|-----|
| `package` | `com.qiyi.video` |
| `cold_start` | `true` |
| `duration_seconds` | `20` |
| `output_dir` | `/tmp/atrace_qiyi_coldstart` |

### 后续工具

`load_trace` → `trace_path` = 返回的 `merged_trace`  
`trace_overview` → `trace_path`  
`analyze_startup` → `trace_path`, `process` = `com.qiyi.video`

### 抓取返回（示例）

- `status`: `success`
- `method`: `atrace-tool (Perfetto system trace + ATrace app sampling merged)`
- `merged_trace`: `/tmp/atrace_qiyi_coldstart/com.qiyi.video_1775031624.perfetto`
- `size_kb`: ~65631
- `overview.duration_ms`: ~10073
- `overview.total_slices`: ~405923
- `overview.total_threads`: ~3290

### `analyze_startup` / 等价 SQL 主线程 Top（示例数值）

| 进程 | 切片 | 耗时 (ms) |
|------|------|-----------|
| `com.qiyi.video:plugin1` | `bindApplication` | ~2480 |
| `com.qiyi.video` | `bindApplication` | ~1133 |
| `com.qiyi.video:plugin1` | `makeApplication` | ~1071 |
| `com.qiyi.video:plugin1` | `OpenDexFilesFromOat` / `Open dex file` | ~979 |
| `com.qiyi.video` | `OpenDexFilesFromOat` / `Open dex file` | ~565 |
| `com.qiyi.video` | `makeApplication` | ~280 |
| `com.qiyi.video` | `Choreographer#doFrame` + `traversal` + `layout` + `RV OnLayout` | ~550–1173 |
| `com.qiyi.video` | `performCreate:com.qiyi.video.WelcomeActivity` | ~93 |
| `com.qiyi.video` | `performResume` / `activityResume` | ~118–139 |

### 大文件分析（MCP 超时备用）

```bash
cd atrace-mcp && uv run python -c "
from trace_analyzer import TraceAnalyzer
import json
p = '/path/to/file.perfetto'
a = TraceAnalyzer()
a.load(p, 'com.qiyi.video')
print(json.dumps(a.analyze_startup(p, 'com.qiyi.video'), indent=2, default=str))
a.close(p)
"
```

---

## 2. 锁竞争（`execute_sql`）

主线程 monitor / Lock，`dur >= 3ms`：

```sql
SELECT
  pr.name AS process,
  t.name AS thread,
  ROUND(s.dur/1e6, 3) AS dur_ms,
  s.name
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process pr ON t.upid = pr.upid
WHERE pr.name LIKE '%com.qiyi.video%'
  AND t.is_main_thread = 1
  AND s.dur >= 3000000
  AND (s.name LIKE 'monitor contention%' OR s.name LIKE 'Lock contention%')
ORDER BY s.dur DESC
LIMIT 30;
```

全进程锁相关 Top，`dur >= 1ms`：

```sql
SELECT pr.name AS process, t.name AS thread, t.is_main_thread AS main,
       s.name, ROUND(s.dur/1e6, 3) AS dur_ms
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
JOIN process pr ON t.upid = pr.upid
WHERE pr.name LIKE '%com.qiyi.video%'
  AND s.dur >= 1000000
  AND (
    s.name LIKE '%contention%'
    OR s.name LIKE '%pthread mutex%'
    OR s.name LIKE 'Contending for pthread mutex%'
  )
ORDER BY s.dur DESC
LIMIT 40;
```

### 样例输出（同 trace）

| 指标 | 值 |
|------|-----|
| `com.qiyi.video`：`Lock contention` 次数（≥0.5ms） | ~736，累计 ~6257 ms |
| `com.qiyi.video`：`pthread mutex` 次数（≥0.5ms） | ~895，累计 ~5957 ms，单次最大 ~430 ms |
| `com.qiyi.video`：`monitor contention` 次数（≥0.5ms） | ~247，累计 ~3522 ms |
| 主线程：`Runtime.nativeLoad` / owner `csj_l_4::init sync` | ~106 ms |
| 主线程：WebView `onServiceConnected` / `GoogleApiHandler` | ~76 ms |
| 主线程：`CardViewPreload` vs `LayoutInflater.inflate` | ~10–48 ms（多次） |

---

## 3. Perfetto UI

`https://ui.perfetto.dev` → Open trace file → 上述 `.perfetto`
