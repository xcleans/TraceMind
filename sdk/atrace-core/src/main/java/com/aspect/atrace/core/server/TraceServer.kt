/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.core.server

import android.content.Context
import android.util.Log
import com.aspect.atrace.ATrace
import com.aspect.atrace.core.TraceEngineCore
import fi.iki.elonen.NanoHTTPD
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileInputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * ATrace HTTP 服务器
 *
 * 提供 HTTP 接口供 PC 端工具 / AI Agent 控制追踪
 *
 * 支持的接口:
 * - GET /?action=start                           开始追踪
 * - GET /?action=stop                            停止追踪
 * - GET /?action=pause                           暂停采样（保留 Hook）
 * - GET /?action=resume                          恢复采样
 * - GET /?action=status                          查询状态
 * - GET /?action=query&name=debug                获取调试信息
 * - GET /?action=query&name=error                获取最近错误
 * - GET /?action=query&name=threads              获取线程列表
 * - GET /?action=plugins                         列出已启用的插件
 * - GET /?action=plugins&id=binder&enable=true   切换插件启用/禁用
 * - GET /?action=sampling                        查询当前采样间隔
 * - GET /?action=sampling&main=500000&other=2000000  设置采样间隔（纳秒）
 * - GET /?action=mark&name=label                 插入自定义标记
 * - GET /?action=capture&force=true              手动堆栈快照
 * - GET /?action=download&name=                  下载文件
 * - GET /?action=clean                           清理追踪数据
 * - GET /?action=config&key=                     获取配置
 * - GET /?action=watch&op=list                 查询 WatchList（items 含 scope/value/raw）
 * - GET /?action=watch&op=add&pattern=        增加子串规则（legacy）
 * - GET /?action=watch&op=add&patterns=a;b;c   批量子串（分号分隔）
 * - GET /?action=watch&op=add&scope=package&value=com.third.   包级（自动补 .）
 * - GET /?action=watch&op=add&scope=class&value=com.third.sdk.Foo   类级（含内部类）
 * - GET /?action=watch&op=add&scope=method&value=com.third.sdk.Foo.bar  方法级（匹配任意重载）
 * - GET /?action=watch&op=add&entries=package:com.a.|class:com.b.C   批量语义规则（| 分隔，段内 scope:value）
 * - GET /?action=watch&op=remove&entry=pkg:com.a.  按存储串移除
 * - GET /?action=hook&op=add&class=com/example/Foo&method=bar&sig=(I)V&static=false   精确 hook 指定方法
 * - GET /?action=hook&op=remove&class=com/example/Foo&method=bar&sig=(I)V&static=false  恢复方法原始入口
 * - GET /?action=watch&op=remove&scope=package&value=com.a.  按语义移除（与 add 等价键）
 * - GET /?action=watch&op=clear                清空 WatchList
 */
class TraceServer private constructor(
    private val context: Context,
    private val traceDir: File
) : NanoHTTPD(0) {

    companion object {
        private const val TAG = "ATrace:Server"
        private const val MIME_BINARY = "application/octet-stream"
        private const val MIME_JSON = "application/json"

        private var instance: TraceServer? = null

        /**
         * 启动服务器
         */
        @JvmStatic
        fun start(context: Context, traceDir: File): TraceServer? {
            return try {
                // 停止已有实例
                instance?.stop()

                val server = TraceServer(context, traceDir)
                server.start(SOCKET_READ_TIMEOUT, false)

                val port = server.listeningPort
                writePortFile(context, port)

                Log.i(TAG, "Server started on port $port")
                instance = server
                server
            } catch (e: Exception) {
                Log.e(TAG, "Failed to start server", e)
                null
            }
        }

        /**
         * 获取当前实例
         */
        @JvmStatic
        fun getInstance(): TraceServer? = instance

        /**
         * 停止服务器
         */
        @JvmStatic
        fun shutdown() {
            instance?.stop()
            instance = null
            Log.i(TAG, "Server stopped")
        }

        /**
         * 写入端口文件，供 PC 端发现
         */
        private fun writePortFile(context: Context, port: Int) {
            try {
                val portDir = File(context.getExternalFilesDir(null), "atrace-port")
                if (!portDir.exists()) portDir.mkdirs()

                // 清理旧文件
                portDir.listFiles()?.forEach { it.delete() }

                // 创建新端口文件
                File(portDir, port.toString()).createNewFile()
            } catch (e: Exception) {
                Log.w(TAG, "Failed to write port file", e)
            }
        }
    }

    // 追踪状态
    private val dumpFinished = AtomicBoolean(false)
    private val dumpLatch = CountDownLatch(1)
    private var lastError: String? = null
    private var traceInfo: JSONObject? = null
    private var exportedFile: File? = null

    override fun serve(session: IHTTPSession): Response {
        return try {
            val params = session.parms
            val action = params["action"]

            Log.d(TAG, "Request: action=$action, params=$params")

            when (action) {
                "start" -> handleStart()
                "stop" -> handleStop()
                "pause" -> handlePause()
                "resume" -> handleResume()
                "status" -> handleStatus()
                "query" -> handleQuery(params["name"])
                "plugins" -> handlePlugins(params["id"], params["enable"])
                "sampling" -> handleSampling(params["main"], params["other"])
                "mark" -> handleMark(params["name"])
                "capture" -> handleCapture(params["force"])
                "download" -> handleDownload(params["name"])
                "clean" -> handleClean()
                "config" -> handleConfig(params["key"])
                "info" -> handleInfo()
                "watch" -> handleWatch(
                    op = params["op"],
                    pattern = params["pattern"],
                    patterns = params["patterns"],
                    scope = params["scope"],
                    value = params["value"],
                    entry = params["entry"],
                    entries = params["entries"],
                )
                "hook" -> handleHook(
                    op = params["op"],
                    className = params["class"],
                    methodName = params["method"],
                    signature = params["sig"],
                    isStatic = params["static"]
                )
                else -> errorResponse("Unknown action: $action")
            }
        } catch (e: Exception) {
            Log.e(TAG, "Request error", e)
            errorResponse(e.message ?: "Unknown error")
        }
    }

    /**
     * 开始追踪
     */
    private fun handleStart(): Response {
        dumpFinished.set(false)
        lastError = null
        traceInfo = null
        exportedFile = null

        val engine = ATrace.getEngine()
        if (engine == null) {
            return errorResponse("Engine not initialized")
        }

        if (engine.isTracing()) {
            return errorResponse("Already tracing")
        }

        engine.start()
        Log.i(TAG, "Tracing started")

        return jsonResponse(JSONObject().apply {
            put("status", "ok")
            put("message", "Tracing started")
        })
    }

    /**
     * 停止追踪
     */
    private fun handleStop(): Response {
        val engine = ATrace.getEngine()
        if (engine == null) {
            return errorResponse("Engine not initialized")
        }

        if (!engine.isTracing()) {
            return errorResponse("Not tracing")
        }

        engine.stop()

        // 导出追踪数据
        try {
            exportedFile = engine.export(traceDir.absolutePath)
            dumpFinished.set(true)
            dumpLatch.countDown()

            traceInfo = JSONObject().apply {
                put("file", exportedFile?.name)
                put("size", exportedFile?.length() ?: 0)
            }

            Log.i(TAG, "Tracing stopped, exported to ${exportedFile?.absolutePath}")
        } catch (e: Exception) {
            lastError = e.message
            Log.e(TAG, "Export failed", e)
        }

        return jsonResponse(JSONObject().apply {
            put("status", "ok")
            put("message", "Tracing stopped")
            put("file", exportedFile?.name)
        })
    }

    /**
     * 暂停采样（不卸载 Hook）
     */
    private fun handlePause(): Response {
        val engine = ATrace.getEngine()
            ?: return errorResponse("Engine not initialized")

        if (engine is TraceEngineCore) {
            engine.pause()
            return jsonResponse(JSONObject().apply {
                put("status", "ok")
                put("message", "Sampling paused")
            })
        }
        return errorResponse("Pause not supported")
    }

    /**
     * 恢复采样
     */
    private fun handleResume(): Response {
        val engine = ATrace.getEngine()
            ?: return errorResponse("Engine not initialized")

        if (engine is TraceEngineCore) {
            engine.resume()
            return jsonResponse(JSONObject().apply {
                put("status", "ok")
                put("message", "Sampling resumed")
            })
        }
        return errorResponse("Resume not supported")
    }

    /**
     * 插件管理
     *
     * - 无参数: 列出所有已加载的插件
     * - id + enable: 切换指定插件的启用/禁用状态
     */
    private fun handlePlugins(id: String?, enable: String?): Response {
        val engine = ATrace.getEngine()
            ?: return errorResponse("Engine not initialized")

        if (engine !is TraceEngineCore) {
            return errorResponse("Plugin management not supported")
        }

        // 切换指定插件
        if (id != null && enable != null) {
            val enabled = enable.toBoolean()
            val success = engine.togglePlugin(id, enabled)
            return if (success) {
                jsonResponse(JSONObject().apply {
                    put("status", "ok")
                    put("plugin", id)
                    put("enabled", enabled)
                })
            } else {
                errorResponse("Plugin not found: $id")
            }
        }

        // 列出所有插件
        val plugins = engine.getPlugins()
        val arr = JSONArray()
        for (p in plugins) {
            arr.put(JSONObject().apply {
                put("id", p["id"])
                put("name", p["name"])
                put("priority", p["priority"])
                @Suppress("UNCHECKED_CAST")
                val cfg = p["config"] as? Map<String, Any> ?: emptyMap()
                if (cfg.isNotEmpty()) {
                    put("config", JSONObject(cfg))
                }
            })
        }
        return jsonResponse(JSONObject().apply {
            put("status", "ok")
            put("plugins", arr)
        })
    }

    /**
     * 采样间隔管理
     *
     * - 无参数: 返回当前间隔
     * - main / other: 设置新间隔（纳秒）
     */
    private fun handleSampling(main: String?, other: String?): Response {
        val engine = ATrace.getEngine()
            ?: return errorResponse("Engine not initialized")

        if (engine !is TraceEngineCore) {
            return errorResponse("Sampling config not supported")
        }

        val mainNs = main?.toLongOrNull() ?: 0L
        val otherNs = other?.toLongOrNull() ?: 0L

        // 如果有参数，则更新
        if (mainNs > 0 || otherNs > 0) {
            engine.setSamplingInterval(mainNs, otherNs)
            return jsonResponse(JSONObject().apply {
                put("status", "ok")
                put("message", "Sampling interval updated")
                put("mainIntervalNs", if (mainNs > 0) mainNs else "unchanged")
                put("otherIntervalNs", if (otherNs > 0) otherNs else "unchanged")
            })
        }

        // 无参数，返回当前配置
        val debug = engine.getDebugInfo()
        val config = debug.optJSONObject("config")
        return jsonResponse(JSONObject().apply {
            put("status", "ok")
            put("mainIntervalNs", config?.optLong("mainThreadInterval"))
            put("otherIntervalNs", config?.optLong("otherThreadInterval"))
        })
    }

    /**
     * 插入自定义标记
     */
    private fun handleMark(name: String?): Response {
        if (name.isNullOrBlank()) {
            return errorResponse("Missing 'name' parameter")
        }

        val engine = ATrace.getEngine()
            ?: return errorResponse("Engine not initialized")

        engine.mark(
            name,
            args = emptyArray()
        )

        return jsonResponse(JSONObject().apply {
            put("status", "ok")
            put("message", "Mark recorded: $name")
        })
    }

    /**
     * 手动堆栈快照
     */
    private fun handleCapture(force: String?): Response {
        val engine = ATrace.getEngine()
            ?: return errorResponse("Engine not initialized")

        if (!engine.isTracing()) {
            return errorResponse("Not tracing")
        }

        engine.capture(force?.toBoolean() ?: false)

        return jsonResponse(JSONObject().apply {
            put("status", "ok")
            put("message", "Stack captured")
        })
    }

    /**
     * 查询状态
     */
    private fun handleStatus(): Response {
        val engine = ATrace.getEngine()
        val isPaused = (engine as? TraceEngineCore)?.isPaused() ?: false

        return jsonResponse(JSONObject().apply {
            put("initialized", engine != null)
            put("tracing", engine?.isTracing() == true)
            put("paused", isPaused)
            put("dumpFinished", dumpFinished.get())
            put("error", lastError)
            traceInfo?.let { put("trace", it) }
        })
    }

    /**
     * 查询信息
     *
     * name=debug → 缓冲区使用/配置/引擎状态/设备信息
     * name=error → 最近错误
     */
    private fun handleQuery(name: String?): Response {
        return when (name) {
            "debug" -> {
                val engine = ATrace.getEngine()
                if (engine is TraceEngineCore) {
                    jsonResponse(engine.getDebugInfo())
                } else {
                    jsonResponse(JSONObject().apply {
                        put("sampling", JSONObject().apply {
                            put("start", 0)
                            put("end", 0)
                            put("capacity", 0)
                        })
                        put("state", JSONObject().apply {
                            put("tracing", engine?.isTracing() == true)
                            put("initialized", engine != null)
                        })
                    })
                }
            }
            "threads" -> {
                val engine = ATrace.getEngine()
                if (engine is TraceEngineCore) {
                    val threads = engine.getThreadList()
                    val arr = JSONArray()
                    for (t in threads) {
                        arr.put(JSONObject().apply {
                            put("tid", t["tid"])
                            put("name", t["name"])
                            put("isMainThread", t["isMainThread"])
                        })
                    }
                    jsonResponse(JSONObject().apply {
                        put("status", "ok")
                        put("count", threads.size)
                        put("threads", arr)
                    })
                } else {
                    errorResponse("Thread query not supported")
                }
            }
            "error" -> {
                jsonResponse(JSONObject().apply {
                    put("error", lastError ?: "none")
                })
            }
            else -> errorResponse("Unknown query name: $name")
        }
    }

    /**
     * 下载文件
     *
     * 支持逻辑名称映射:
     * - "sampling"         → trace_*.perfetto (采样数据)
     * - "sampling-mapping" → mapping_*.bin    (符号映射)
     * - 其他               → 按原始文件名查找
     */
    private fun handleDownload(name: String?): Response {
        if (name.isNullOrEmpty()) {
            return errorResponse("Missing file name")
        }

        // 等待导出完成
        if (!dumpFinished.get()) {
            val success = dumpLatch.await(30, TimeUnit.SECONDS)
            if (!success) {
                return errorResponse("Wait for trace data timeout")
            }
        }

        val file = resolveDownloadFile(name)
        if (file == null || !file.exists()) {
            val available = traceDir.listFiles()?.map { it.name } ?: emptyList()
            Log.w(TAG, "File not found: $name, available: $available")
            return errorResponse("File not found: $name")
        }

        Log.i(TAG, "Downloading: ${file.absolutePath}, size=${file.length()}")

        return newChunkedResponse(
            Response.Status.OK,
            MIME_BINARY,
            FileInputStream(file)
        ).apply {
            addHeader("Content-Disposition", "attachment; filename=\"${file.name}\"")
            addHeader("Content-Length", file.length().toString())
        }
    }

    private fun resolveDownloadFile(name: String): File? {
        return when (name) {
            "sampling" -> {
                // Native Export 生成: trace_<ts>.perfetto
                traceDir.listFiles { _, n -> n.startsWith("trace_") && n.endsWith(".perfetto") && !n.endsWith(".mapping") }
                    ?.maxByOrNull { it.lastModified() }
            }
            "sampling-mapping" -> {
                // Native Export 生成: trace_<ts>.perfetto.mapping
                traceDir.listFiles { _, n -> n.endsWith(".perfetto.mapping") }
                    ?.maxByOrNull { it.lastModified() }
            }
            else -> {
                val exact = File(traceDir, name)
                if (exact.exists()) exact else null
            }
        }
    }

    /**
     * 清理追踪数据
     */
    private fun handleClean(): Response {
        var count = 0
        traceDir.listFiles()?.forEach { file ->
            if (file.delete()) count++
        }

        dumpFinished.set(false)
        lastError = null
        traceInfo = null
        exportedFile = null

        Log.i(TAG, "Cleaned $count files")

        return jsonResponse(JSONObject().apply {
            put("status", "ok")
            put("cleaned", count)
        })
    }

    /**
     * 精确方法 Hook：替换 entry_point_from_quick_compiled_code_。
     *
     * - GET /?action=hook&op=add&class=com/example/Foo&method=bar&sig=(I)V&static=false
     * - GET /?action=hook&op=remove&class=com/example/Foo&method=bar&sig=(I)V&static=false
     */
    private fun handleHook(
        op: String?,
        className: String?,
        methodName: String?,
        signature: String?,
        isStatic: String?
    ): NanoHTTPD.Response {
        val engine = ATrace.getEngine() ?: return errorResponse("Engine not initialized")
        return when (op) {
            "add" -> {
                if (className.isNullOrEmpty() || methodName.isNullOrEmpty() || signature.isNullOrEmpty()) {
                    return errorResponse("Missing class/method/sig parameters")
                }
                val static = isStatic?.toBoolean() ?: false
                val ok = engine.hookMethod(className, methodName, signature, static)
                jsonResponse(JSONObject().apply {
                    put("status", if (ok) "ok" else "failed")
                    put("class", className)
                    put("method", methodName)
                    put("signature", signature)
                    put("static", static)
                })
            }
            "remove" -> {
                if (className.isNullOrEmpty() || methodName.isNullOrEmpty() || signature.isNullOrEmpty()) {
                    return errorResponse("Missing class/method/sig parameters")
                }
                val static = isStatic?.toBoolean() ?: false
                engine.unhookMethod(className, methodName, signature, static)
                jsonResponse(JSONObject().apply {
                    put("status", "ok")
                    put("class", className)
                    put("method", methodName)
                    put("signature", signature)
                })
            }
            else -> errorResponse("Unknown hook op: $op (expected add/remove)")
        }
    }

    /**
     * ArtMethod WatchList：支持包 / 类 / 方法 / 子串 四级语义（native 内与 PrettyMethod 对齐）。
     */
    private fun handleWatch(
        op: String?,
        pattern: String?,
        patterns: String?,
        scope: String?,
        value: String?,
        entry: String?,
        entries: String?,
    ): Response {
        val engine = ATrace.getEngine() ?: return errorResponse("Engine not initialized")

        return when (op?.lowercase().orEmpty()) {
            "", "list" -> {
                val list = if (engine is TraceEngineCore) {
                    engine.getWatchedRules()
                } else {
                    emptyList()
                }
                val items = JSONArray()
                for (raw in list) {
                    items.put(watchEntryToJson(raw))
                }
                jsonResponse(JSONObject().apply {
                    put("status", "ok")
                    put("count", engine.watchedRuleCount())
                    put("rules", JSONArray(list))
                    put("items", items)
                })
            }
            "add" -> {
                val added = mutableListOf<String>()

                val batch = entries?.trim()?.takeIf { it.isNotEmpty() }
                if (batch != null) {
                    for (part in batch.split('|')) {
                        val seg = part.trim()
                        if (seg.isEmpty()) continue
                        val colon = seg.indexOf(':')
                        if (colon <= 0 || colon >= seg.length - 1) {
                            return errorResponse("Invalid entries segment (need scope:value): $seg")
                        }
                        val sc = seg.substring(0, colon).trim()
                        val va = seg.substring(colon + 1).trim()
                        if (va.isEmpty()) {
                            return errorResponse("Empty value in entries segment: $seg")
                        }
                        engine.addWatchedRule(sc, va)
                        added.add("$sc:$va")
                    }
                    if (added.isEmpty()) {
                        return errorResponse("entries is empty")
                    }
                } else {
                    val sc = scope?.trim()?.takeIf { it.isNotEmpty() }
                    val va = (value ?: pattern)?.trim()?.takeIf { it.isNotEmpty() }
                    if (sc != null && va != null) {
                        engine.addWatchedRule(sc, va)
                        added.add("$sc:$va")
                    } else {
                        val toAdd = mutableListOf<String>()
                        pattern?.trim()?.takeIf { it.isNotEmpty() }?.let { toAdd.add(it) }
                        patterns?.split(';')
                            ?.map { it.trim() }
                            ?.filter { it.isNotEmpty() }
                            ?.let { toAdd.addAll(it) }
                        if (toAdd.isEmpty()) {
                            return errorResponse(
                                "Missing: pattern/patterns, or scope+value, or entries=scope:value|..."
                            )
                        }
                        toAdd.forEach { engine.addWatchedRule("substring", it) }
                        added.addAll(toAdd)
                    }
                }

                jsonResponse(JSONObject().apply {
                    put("status", "ok")
                    put("message", "Watch rules added")
                    put("added", JSONArray(added))
                    put("count", engine.watchedRuleCount())
                })
            }
            "remove" -> {
                val exact = entry?.trim()?.takeIf { it.isNotEmpty() }
                val key = exact ?: canonicalWatchStorageKey(
                    scope = scope,
                    value = (value ?: pattern)?.trim(),
                )
                if (key.isNullOrEmpty()) {
                    return errorResponse("Missing entry=... or scope+value / pattern")
                }
                engine.removeWatchedRule(key)
                jsonResponse(JSONObject().apply {
                    put("status", "ok")
                    put("message", "Watch rule removed")
                    put("entry", key)
                    put("count", engine.watchedRuleCount())
                })
            }
            "clear" -> {
                engine.clearWatchedRules()
                jsonResponse(JSONObject().apply {
                    put("status", "ok")
                    put("message", "Watch list cleared")
                    put("count", 0)
                })
            }
            else -> errorResponse("Unknown watch op: $op (use list|add|remove|clear)")
        }
    }

    private fun watchEntryToJson(raw: String): JSONObject = JSONObject().apply {
        put("raw", raw)
        when {
            raw.startsWith("pkg:") -> {
                put("scope", "package")
                put("value", raw.removePrefix("pkg:"))
            }
            raw.startsWith("cls:") -> {
                put("scope", "class")
                put("value", raw.removePrefix("cls:"))
            }
            raw.startsWith("mth:") -> {
                put("scope", "method")
                put("value", raw.removePrefix("mth:"))
            }
            else -> {
                put("scope", "substring")
                put("value", raw)
            }
        }
    }

    /** 与 native 存储键一致，用于 remove */
    private fun canonicalWatchStorageKey(scope: String?, value: String?): String? {
        val v = value?.trim() ?: return null
        if (v.isEmpty()) return null
        val sc = scope?.lowercase()?.trim().orEmpty()
        if (sc.isEmpty() || sc == "substring" || sc == "legacy" || sc == "sub") {
            return v
        }
        return when (sc) {
            "package", "pkg" -> {
                var pkg = v.replace('/', '.')
                if (pkg.isNotEmpty() && !pkg.endsWith('.')) pkg += "."
                "pkg:$pkg"
            }
            "class", "cls" -> "cls:${v.replace('/', '.')}"
            "method", "mth" -> "mth:${v.replace('/', '.')}"
            else -> null
        }
    }

    /**
     * 获取配置
     */
    private fun handleConfig(key: String?): Response {
        val engine = ATrace.getEngine() ?: return errorResponse("Engine not initialized")

        return jsonResponse(JSONObject().apply {
            put("status", "ok")
            // 可以根据 key 返回特定配置
            put("package", context.packageName)
            put("tracing", engine.isTracing())
        })
    }

    /**
     * 获取追踪信息
     */
    private fun handleInfo(): Response {
        return jsonResponse(JSONObject().apply {
            put("version", "1.0.0")
            put("package", context.packageName)
            put("traceDir", traceDir.absolutePath)
            put("files", traceDir.listFiles()?.map { it.name } ?: emptyList<String>())
        })
    }

    /**
     * JSON 响应
     */
    private fun jsonResponse(json: JSONObject): Response {
        return newFixedLengthResponse(
            Response.Status.OK,
            MIME_JSON,
            json.toString()
        )
    }

    /**
     * 错误响应
     */
    private fun errorResponse(message: String): Response {
        return jsonResponse(JSONObject().apply {
            put("status", "error")
            put("message", message)
        })
    }

    /**
     * 通知追踪导出完成
     */
    fun onTraceDumpFinished(code: Int, file: File?) {
        if (code != 0) {
            lastError = "Export failed with code $code"
        }

        exportedFile = file
        traceInfo = JSONObject().apply {
            put("file", file?.name)
            put("size", file?.length() ?: 0)
            put("code", code)
        }

        dumpFinished.set(true)
        dumpLatch.countDown()
    }
}

