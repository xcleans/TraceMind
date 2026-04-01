package com.aspect.atrace.tool.http

import com.aspect.atrace.tool.adb.Adb
import com.aspect.atrace.tool.core.Arguments
import com.aspect.atrace.tool.core.Log
import com.aspect.atrace.tool.core.TraceError
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * HTTP 客户端 - 与 App 端 TraceServer 通信
 */
object HttpClient {

    private var forwarded = false

    /** `adb shell content query` 输出中的 port= 列 */
    private val CONTENT_PORT_REGEX = Regex("""port=(-?\d+)""")

    /**
     * 建立 ADB 端口转发：本机 `localhost:args.port` → 设备上 App 实际监听端口。
     * PC 无法直接连设备环回地址，故用 `adb forward` 把隧道接到 App 的 TCP 端口。
     *
     * @throws TraceError 当无法获取端口时
     */
    fun setupForward() {
        if (forwarded) return

        val args = Arguments.get()
        val appServerPort = getAppServerPort(args.appName)

        if (appServerPort <= 0) {
            throw TraceError(
                "cannot establish connection to app trace server",
                "make sure the app is running, HTTP server enabled (atrace-core), and " +
                    "`-a` matches applicationId for content://${args.appName}.atrace/atrace/port " +
                    "or external files atrace-port is readable"
            )
        }
        Adb.forward(args.port, appServerPort)
        forwarded = true
    }

    /**
     * 尝试建立 ADB 端口转发，失败时返回 false 而不抛出异常。
     *
     * 用于"优雅降级"场景：App 未集成 atrace-core 或 HTTP 服务未启动时，
     * 调用方可选择仅采集系统 trace（无 app 采样数据）。
     *
     * @return true = 转发成功；false = App 服务不可达，将降级为纯系统 trace
     */
    fun trySetupForward(): Boolean {
        if (forwarded) return true

        val args = Arguments.get()
        val appServerPort = getAppServerPort(args.appName)

        if (appServerPort <= 0) {
            Log.w(
                "App trace server not found for '${args.appName}'. " +
                    "Falling back to system-only trace (no app sampling data)."
            )
            Log.w(
                "To enable app sampling: integrate atrace-core and ensure the HTTP server " +
                    "is started before capture."
            )
            return false
        }

        return try {
            Adb.forward(args.port, appServerPort)
            forwarded = true
            true
        } catch (e: Exception) {
            Log.w("ADB forward failed: ${e.message}. Falling back to system-only trace.")
            false
        }
    }

    /**
     * 移除端口转发
     */
    fun removeForward() {
        if (!forwarded) return

        try {
            val args = Arguments.get()
            Adb.removeForward(args.port)
        } catch (e: Exception) {
            Log.d("Remove forward failed: ${e.message}")
        }
        forwarded = false
    }

    /**
     * 解析设备端 TraceServer 端口。
     *
     * 1. **ContentProvider**（推荐，Release 可读）：`content://<applicationId>.atrace/atrace/port`
     *    与 `-a` 传入的应一致（一般为 `applicationId`）。
     * 2. **外部文件目录**（旧方式）：`/Android/data/<package>/files/atrace-port/` 下文件名即端口。
     */
    private fun getAppServerPort(packageName: String): Int {
        when (val cp = queryPortFromContentProvider(packageName)) {
            null -> { /* query 失败或无输出，尝试读目录 */ }
            -1 -> return -1 // Provider 已响应：服务未启动
            in 1..65535 -> return cp
            else -> { /* 0 等非法值，继续尝试文件 */ }
        }
        return getAppServerPortFromAtracePortDir(packageName)
    }

    /**
     * @return 正整数端口；`-1` 表示 Provider 明确返回未启动；`null` 表示 query 不可用或解析失败
     */
    private fun queryPortFromContentProvider(packageName: String): Int? {
        val uri = "content://$packageName.atrace/atrace/port"
        val result = Adb.callWithResult(
            "shell", "content", "query", "--uri", uri,
        )
        if (result.exitCode != 0) {
            Log.d(
                "ContentProvider port query failed (exit ${result.exitCode}): " +
                    "${result.stderr.ifBlank { result.stdout }}",
            )
            return null
        }
        val match = CONTENT_PORT_REGEX.find(result.stdout)
        val port = match?.groupValues?.get(1)?.toIntOrNull()
        if (port == null) {
            Log.d("ContentProvider: no port in output: ${result.stdout.trim()}")
            return null
        }
        if (port > 0) {
            Log.d("Found app server port via ContentProvider: $port")
        }
        return port
    }

    private fun getAppServerPortFromAtracePortDir(packageName: String): Int {
        val dirPath = "/storage/emulated/0/Android/data/$packageName/files/atrace-port"
        try {
            val files = Adb.listFiles(dirPath)
            for (file in files) {
                val port = file.trim().toIntOrNull()
                if (port != null && port > 0) {
                    Log.d("Found app server port from atrace-port dir: $port")
                    return port
                }
            }
        } catch (e: Exception) {
            Log.d("Get app server port from dir failed: ${e.message}")
        }
        return -1
    }

    /**
     * 发送 GET 请求
     */
    fun get(path: String): String {
        val args = Arguments.get()
        @Suppress("DEPRECATION")
        val url = URL("http://localhost:${args.port}$path")

        Log.d("HTTP GET: $url")

        val connection = url.openConnection() as HttpURLConnection
        connection.connectTimeout = 10000
        connection.readTimeout = 30000

        try {
            val response = connection.inputStream.bufferedReader().readText()
            Log.d("HTTP Response: $response")
            return response
        } catch (e: Exception) {
            throw TraceError(
                "HTTP request failed: ${e.message}",
                "check if app is running and TraceServer is enabled"
            )
        } finally {
            connection.disconnect()
        }
    }

    /**
     * 安全发送 GET 请求
     */
    fun getSafe(path: String): String? {
        return try {
            get(path)
        } catch (e: Exception) {
            Log.d("HTTP request failed: ${e.message}")
            null
        }
    }

    /**
     * 下载文件
     */
    fun download(fileName: String, destination: File) {
        val args = Arguments.get()
        @Suppress("DEPRECATION")
        val url = URL("http://localhost:${args.port}?action=download&name=$fileName")

        Log.d("HTTP Download: $url -> ${destination.absolutePath}")

        val connection = url.openConnection() as HttpURLConnection
        connection.connectTimeout = 10000
        connection.readTimeout = 60000

        try {
            val contentType = connection.contentType ?: ""

            if (contentType.contains("application/json")) {
                val body = connection.inputStream.bufferedReader().readText()
                throw TraceError(
                    "download '$fileName' failed, server returned: $body",
                    "make sure the app has been rebuilt with the latest atrace-core"
                )
            }

            connection.inputStream.use { input ->
                destination.outputStream().use { output ->
                    input.copyTo(output)
                }
            }

            val size = destination.length()
            Log.d("Downloaded: ${destination.name} ($size bytes)")

            if (size == 0L) {
                throw TraceError(
                    "downloaded file '$fileName' is empty",
                    "the app may not have produced trace data"
                )
            }
        } catch (e: TraceError) {
            throw e
        } catch (e: Exception) {
            val errorInfo = try {
                get("?action=query&name=error")
            } catch (e2: Exception) {
                "unknown"
            }

            throw TraceError(
                "download file $fileName failed: $errorInfo",
                "check if app is running and has trace data"
            )
        } finally {
            connection.disconnect()
        }
    }

    /**
     * 安全下载文件
     */
    fun downloadSafe(fileName: String, destination: File) {
        try {
            download(fileName, destination)
        } catch (e: Exception) {
            Log.w("Download $fileName failed: ${e.message}")
        }
    }

    // ==================== 便捷方法 ====================

    fun startTrace() = get("?action=start")

    fun stopTrace() = get("?action=stop")

    fun cleanTrace() = getSafe("?action=clean")

    fun getStatus(): String? = getSafe("?action=status")

    fun getError(): String? = getSafe("?action=query&name=error")

    /**
     * 获取调试信息 (JSON)
     *
     * 返回结构:
     * ```json
     * {
     *   "sampling": { "currentTicket": N, "capacity": N, "start": N, "end": N },
     *   "state":    { "tracing": bool, "startToken": N, "endToken": N, "pid": N, "plugins": "..." },
     *   "config":   { "bufferCapacity": N, "mainThreadInterval": N, ... },
     *   "device":   { "sdk": N, "arch": "...", "model": "..." }
     * }
     * ```
     */
    fun getDebugInfo(): JSONObject? {
        return try {
            val json = get("?action=query&name=debug")
            JSONObject(json)
        } catch (e: Exception) {
            Log.d("getDebugInfo failed: ${e.message}")
            null
        }
    }

    /**
     * 获取缓冲区使用率信息
     *
     * @return BufferUsage 或 null
     */
    fun getBufferUsage(): BufferUsage? {
        val debug = getDebugInfo() ?: return null
        val sampling = debug.optJSONObject("sampling") ?: return null

        val start = sampling.optLong("start", 0)
        val capacity = sampling.optLong("capacity", 0)
        val end = sampling.optLong("end", sampling.optLong("currentTicket", 0))

        if (capacity <= 0) return null

        return BufferUsage(
            start = start,
            end = end,
            capacity = capacity,
            used = end - start
        )
    }

    /**
     * 打印完整调试信息
     */
    fun printDebugInfo() {
        val debug = getDebugInfo() ?: run {
            Log.d("No debug info available")
            return
        }

        // 缓冲区使用
        debug.optJSONObject("sampling")?.let { sampling ->
            val start = sampling.optLong("start", 0)
            val capacity = sampling.optLong("capacity", 0)
            val end = sampling.optLong("end", sampling.optLong("currentTicket", 0))
            val used = end - start

            if (capacity > 0) {
                val percent = used * 100 / capacity
                if (used <= capacity) {
                    Log.blue("Buffer usage: $used/$capacity ($percent%)")
                } else {
                    Log.red("Buffer overflow! Used: $used, Capacity: $capacity")
                    Log.red("Increase buffer size with: -maxAppTraceBufferSize $used")
                }
            }
        }

        // 引擎状态
        debug.optJSONObject("state")?.let { state ->
            Log.d("Engine: tracing=${state.optBoolean("tracing")}, " +
                    "pid=${state.optInt("pid")}, plugins=[${state.optString("plugins")}]")
        }

        // 配置
        debug.optJSONObject("config")?.let { config ->
            Log.d("Config: buffer=${config.optInt("bufferCapacity")}, " +
                    "mainInterval=${config.optLong("mainThreadInterval") / 1000}us, " +
                    "otherInterval=${config.optLong("otherThreadInterval") / 1000}us, " +
                    "maxDepth=${config.optInt("maxStackDepth")}, " +
                    "clock=${config.optString("clockType")}")
        }

        // 设备
        debug.optJSONObject("device")?.let { device ->
            Log.d("Device: sdk=${device.optInt("sdk")}, " +
                    "arch=${device.optString("arch")}, " +
                    "model=${device.optString("model")}")
        }
    }

    /**
     * 检查应用是否就绪
     */
    fun checkAppReady(): Boolean {
        val status = getStatus() ?: return false
        return try {
            val json = JSONObject(status)
            json.optBoolean("initialized", false)
        } catch (e: Exception) {
            false
        }
    }

    data class BufferUsage(
        val start: Long,
        val end: Long,
        val capacity: Long,
        val used: Long
    ) {
        val percent: Long get() = if (capacity > 0) used * 100 / capacity else 0
        val isOverflow: Boolean get() = used > capacity
    }
}
