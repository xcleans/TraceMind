# ArtMethod WatchList 使用说明

本文说明如何通过 **`addWatchedRule(scope, value)`** 在运行时配置监控规则。底层实现为 `ArtMethodInstrumentation`：替换 `ArtMethod.entry_point_from_quick_compiled_code_`，在方法进入/退出时做 Section Begin/End 标记（具体行为以当前 native 实现为准）。

---

## 1. 能力边界（必读）

- **Hook 机制**：直接替换目标 `ArtMethod` 的入口指针。所有对该方法的调用（直调 / 反射 / JNI）均经过 trampoline。
- 匹配依据为 ART **`ArtMethod::PrettyMethod(true)`** 的字符串（含签名），不是 JVM 内部名以外的随意格式。

---

## 2. PrettyMethod 长什么样

典型形态：

```text
void com.example.sdk.Client.connect(java.lang.String, int)
```

结构可理解为：`返回类型` + 空格 + **`全限定类名(FQCN)`** + **`.`** + **`方法名`** + **`(`** + 参数列表 + `)`。

下文「包级 / 类级 / 方法级」规则均基于对该字符串的解析或子串匹配。

---

## 3. `addWatchedRule(scope, value)` — 包 / 类 / 方法 / 子串

语义由 **`scope`** 决定，**`value`** 为对应级别的描述字符串（可使用 `.` 或 `/` 作为包分隔，实现中会规范为 `.`）。

| scope（别名） | value 含义 | 匹配说明 |
|---------------|------------|----------|
| **`package`**（`pkg`） | 包前缀，如 `com.third.sdk` | 解析出 FQCN 后，要求 **FQCN 以 `规范化包前缀` 开头。规范化：将 `/` 转为 `.`，且若末尾没有 `.` 会自动补 `.`，避免 `com.foo` 匹配到 `com.foobar`。 |
| **`class`**（`cls`） | 全限定类名，如 `com.third.sdk.Client` | FQCN **等于**该类，或为 **`该类名 + '$'`** 开头的内部类（如 `com.foo.Outer$Inner`）。 |
| **`method`**（`mth`） | **`Fqcn.方法名`**，如 `com.third.sdk.Client.connect` | PrettyMethod 中出现 **`value + "("`** 即视为命中（**同一方法名所有重载**都会命中）。 |
| **`substring`**（`legacy` / `sub`） | 任意子串 | 在整个 PrettyMethod 上做子串包含判断。 |

**Kotlin 示例：**

```kotlin
// 包：该包下各类的方法
ATrace.addWatchedRule("package", "com.third.sdk")

// 类：该类及 JVM 内部类
ATrace.addWatchedRule("class", "com.third.sdk.Client")

// 方法：所有 connect 重载
ATrace.addWatchedRule("method", "com.third.sdk.Client.connect")

// 子串匹配
ATrace.addWatchedRule("substring", "com.third.sdk.Client")
```

**内部类**：源码里的 `Outer.Inner` 在 JVM 中多为 **`com.pkg.Outer$Inner`**，`class` / `method` 的 value 请按 **带 `$` 的 FQCN** 书写，与 PrettyMethod 一致。

---

## 4. 引擎 API 小结（`TraceEngine` / `TraceEngineCore`）

| API | 说明 |
|-----|------|
| `addWatchedRule(scope, value)` | 包 / 类 / 方法 / 子串 |
| `removeWatchedRule(entry)` | 删除一条；**参数须与列表中的存储串完全一致**（见下节） |
| `clearWatchedRules()` | 清空 |
| `watchedRuleCount()` | 条数 |
| `getWatchedRules()` | 当前所有规则的 **内部存储字符串** 快照 |

---

## 5. 内部存储格式（与删除、HTTP `list` 一致）

便于调试与 **精确删除**，native 侧会使用带前缀的存储形式（子串规则无前缀）：

| 类型 | 存储示例 |
|------|----------|
| 子串 | `com.third.sdk.` |
| 包 | `pkg:com.third.sdk.` |
| 类 | `cls:com.third.sdk.Client` |
| 方法 | `mth:com.third.sdk.Client.connect` |

`removeWatchedRule` 应传入 **与 `getWatchedRules()` 或 HTTP `list` 返回的 `raw` 字段完全一致** 的字符串；或通过 HTTP 使用 **`scope` + `value`** 删除（服务端会换算为同一存储键）。

---

## 6. HTTP（`action=watch`）简要

前提：应用已初始化 ATrace 且 HTTP Server 已开启（与现有 Trace 控制台一致）。

| 操作 | 说明 |
|------|------|
| `op=list` | 返回 `rules`（原始存储串）、`items`（解析后的 `scope` / `value` / `raw`）、`count` |
| `op=add` + `pattern` / `patterns`（`;` 分隔） | 仅 **子串** 批量或单条 |
| `op=add` + `scope` + `value`（或 `pattern` 作 value） | **单条语义规则** |
| `op=add` + `entries` | 批量语义，格式 **`scope:value`**，多条用 **`|`** 分隔，例如：`package:com.a.|class:com.b.C|method:com.b.C.m` |
| `op=remove` + `entry=pkg:com.a.` | 按存储串删除 |
| `op=remove` + `scope` + `value` | 按语义删除（与 add 同一套规范化规则） |
| `op=clear` | 清空 |

URL 中的 `&`、`:`、`|` 等请按需 **URL 编码**。

### 6.1 通过 ContentProvider 获取端口（Release / 无法读 `atrace-port` 目录）

集成 `atrace-core` 后，清单会合并 **`AtracePortProvider`**，authority 为 **`<applicationId>.atrace`**（与 App `applicationId` 一致，一般为包名）。

- **URI**：`content://<applicationId>.atrace/atrace/port`
- **返回**：单列 **`port`**（整数）；HTTP 服务未启动时为 **`-1`**
- **`android:exported="true"`**：便于 `adb shell content query`；外发 App 请自行评估是否改为 `false` 并仅用同进程 / 签名方式访问。

**ADB 示例：**

```bash
adb shell content query --uri content://com.example.app.atrace/atrace/port
```

典型输出含 `port=12345`，工具侧可解析该字段后再执行 `adb forward tcp:<本机端口> tcp:<设备端口>`。

**Kotlin（进程内）：**

```kotlin
context.contentResolver.query(
    AtracePortProvider.buildPortUri("${BuildConfig.APPLICATION_ID}.atrace"),
    arrayOf("port"), null, null, null
)?.use { c ->
    if (c.moveToFirst()) println(c.getInt(0))
}
```

Python：`DeviceController.get_http_port_from_content_provider(package_name)`。

---

## 7. 与 MCP / `device_controller` 的对应关系

- `add_watch_rule(scope, value)` → HTTP `scope` + `value`
- `add_watch_entries(entries)` → HTTP `entries`
- `add_watch_patterns(patterns, scope=None)`：未传 `scope` 时为子串批量；传 `scope` 时对每个 pattern 按该语义添加
- `list_watch_patterns` → `op=list`
- `remove_watch_entry` / `remove_watch_pattern` → `op=remove`
- `clear_watch_patterns` → `op=clear`

详见仓库内 `atrace-mcp/README.md` 工具表。

---

## 8. 常见问题

1. **配置了包名为什么没有命中？**  
   先确认目标方法是否已被 hook（通过 `scanLoadedClasses` 或 `enableAutoHook`）。
2. **`com.foo.*` 为什么不按包匹配？**  
   `*` 无通配语义；包级请用 **`addWatchedRule("package", "com.foo")`** 或子串 **`addWatchedRule("substring", "com.foo.")`**。
3. **方法和类规则混淆**  
   `method` 的 value **必须**包含 **至少一个 `.`**（FQCN 与方法名之间的点），例如 `com.pkg.Class.methodName`。

---

## 9. 相关代码位置

- Native：`atrace-core/src/main/cpp/hook/ArtMethodInstrumentation.{h,cpp}`
- JNI：`atrace-core/src/main/cpp/jni/engine_jni.cpp`（`nativeAddWatchedRule` 等）
- Kotlin 引擎：`atrace-core/.../TraceEngineCore.kt`
- 公开入口：`atrace-api/.../ATrace.kt`
- HTTP：`atrace-core/.../server/TraceServer.kt`（`action=watch`）
