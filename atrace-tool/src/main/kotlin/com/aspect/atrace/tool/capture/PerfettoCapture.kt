package com.aspect.atrace.tool.capture

import com.aspect.atrace.tool.core.Arguments
import com.aspect.atrace.tool.core.Log
import com.aspect.atrace.tool.core.TraceError
import com.aspect.atrace.tool.core.Workspace
import com.aspect.atrace.tool.trace.SamplingDecoder
import java.io.File

/**
 * Perfetto 系统 Trace 捕获 (Android 9+)
 *
 * 支持两种模式:
 *   1. -c config.txtpb  使用完整 Perfetto 配置文件
 *   2. 不指定 -c 时自动生成包含丰富数据源的默认配置
 */
class PerfettoCapture : SystemCapture {

    private var process: Process? = null
    private var started = false

    override fun start(args: Array<String>) {
        val bin = Workspace.perfettoBinary()
        extractPerfettoScript(bin)

        val arguments = Arguments.get()
        val configFile = resolveConfigFile(arguments)

        val cmd = buildCommand(bin, configFile, arguments)

        Log.d("Perfetto command: ${cmd.joinToString(" ")}")

        process = ProcessBuilder(cmd)
            .redirectErrorStream(false)
            .start()

        started = true
    }

    /**
     * 始终使用 -c 配置文件模式，获取最完整的 Perfetto 数据。
     *
     * record_android_trace 的 -c 模式会将配置文件通过 stdin 传递给设备上的
     * perfetto 命令 (`perfetto --txt -c -`)，time/buffer/app 等参数均在配置文件内定义。
     */
    private fun buildCommand(bin: File, configFile: File, arguments: Arguments): List<String> {
        return buildList {
            add(bin.absolutePath)
            add("-o")
            add(Workspace.systemTrace().absolutePath)
            add("-n")
            add("-c")
            add(configFile.absolutePath)
        }
    }

    private fun resolveConfigFile(arguments: Arguments): File {
        val userConfig = arguments.perfettoConfig
        if (userConfig != null) {
            val f = File(userConfig)
            if (!f.exists()) {
                throw TraceError("Config file not found: $userConfig", "check your -c config path")
            }
            return f
        }

        val categories = arguments.systraceArgs
            .filter { !it.startsWith("-") }
            .toList()

        return generateDefaultConfig(arguments, categories)
    }

    /**
     *
     */
    private fun generateDefaultConfig(arguments: Arguments, extraCategories: List<String>): File {
        val configFile = File(Workspace.perfettoBinary().parentFile, "perfetto_config.txtpb")

        val durationMs = (arguments.timeInSeconds ?: 10) * 1000
        val bufferSizeKb = parseSizeToKb(arguments.bufferSize)

        val defaultCategories = listOf(
            "am", "wm", "gfx", "view", "sched", "freq", "idle",
            "dalvik", "binder_driver", "binder_lock",
            "bionic", "disk", "input", "memory", "memreclaim",
            "hal", "res", "pm", "power", "sm", "ss",
            "camera", "audio", "video", "webview",
            "database", "network"
        )
        val allCategories = (defaultCategories + extraCategories).distinct()

        val ftraceEvents = listOf(
            "sched/sched_switch",
            "sched/sched_wakeup",
            "sched/sched_wakeup_new",
            "sched/sched_waking",
            "sched/sched_blocked_reason",
            "sched/sched_process_exit",
            "sched/sched_process_free",
            "task/task_newtask",
            "task/task_rename",
            "power/cpu_frequency",
            "power/cpu_idle",
            "power/suspend_resume",
            "raw_syscalls/sys_enter",
            "raw_syscalls/sys_exit",
            "ftrace/print"
        )

        val config = buildString {
            appendLine("buffers {")
            appendLine("  size_kb: $bufferSizeKb")
            appendLine("  fill_policy: DISCARD")
            appendLine("}")
            appendLine("buffers {")
            appendLine("  size_kb: 4096")
            appendLine("  fill_policy: DISCARD")
            appendLine("}")

            appendLine("data_sources {")
            appendLine("  config {")
            appendLine("    name: \"linux.ftrace\"")
            appendLine("    ftrace_config {")
            for (event in ftraceEvents) {
                appendLine("      ftrace_events: \"$event\"")
            }
            for (cat in allCategories) {
                appendLine("      atrace_categories: \"$cat\"")
            }
            appendLine("      atrace_apps: \"${arguments.appName}\"")
            appendLine("      atrace_apps: \"*\"")
            appendLine("      symbolize_ksyms: true")
            appendLine("      disable_generic_events: true")
            appendLine("    }")
            appendLine("  }")
            appendLine("}")

            appendLine("data_sources {")
            appendLine("  config {")
            appendLine("    name: \"linux.process_stats\"")
            appendLine("    target_buffer: 1")
            appendLine("    process_stats_config {")
            appendLine("      scan_all_processes_on_start: true")
            appendLine("    }")
            appendLine("  }")
            appendLine("}")

            appendLine("data_sources {")
            appendLine("  config {")
            appendLine("    name: \"linux.sys_stats\"")
            appendLine("    sys_stats_config {")
            appendLine("      stat_period_ms: 1000")
            appendLine("      stat_counters: STAT_CPU_TIMES")
            appendLine("      stat_counters: STAT_FORK_COUNT")
            appendLine("      cpufreq_period_ms: 1000")
            appendLine("    }")
            appendLine("  }")
            appendLine("}")

            appendLine("data_sources {")
            appendLine("  config {")
            appendLine("    name: \"android.log\"")
            appendLine("    android_log_config {")
            appendLine("      log_ids: LID_CRASH")
            appendLine("      log_ids: LID_DEFAULT")
            appendLine("      log_ids: LID_EVENTS")
            appendLine("      log_ids: LID_SYSTEM")
            appendLine("    }")
            appendLine("  }")
            appendLine("}")

            appendLine("data_sources {")
            appendLine("  config {")
            appendLine("    name: \"android.surfaceflinger.frametimeline\"")
            appendLine("  }")
            appendLine("}")

            appendLine("duration_ms: $durationMs")
        }

        configFile.writeText(config)
        Log.d("Generated Perfetto config: ${configFile.absolutePath}")
        return configFile
    }

    private fun parseSizeToKb(sizeStr: String): Int {
        val lower = sizeStr.lowercase()
        return when {
            lower.endsWith("gb") -> lower.removeSuffix("gb").toInt() * 1024 * 1024
            lower.endsWith("mb") -> lower.removeSuffix("mb").toInt() * 1024
            lower.endsWith("kb") -> lower.removeSuffix("kb").toInt()
            else -> sizeStr.toIntOrNull()?.let { it * 1024 } ?: 65536
        }
    }

    private fun extractPerfettoScript(destination: File) {
        val resourceName = when {
            isMacOS() -> "record_android_trace"
            isWindows() -> "record_android_trace_win"
            else -> "record_android_trace"
        }

        javaClass.getResourceAsStream("/$resourceName")?.use { input ->
            destination.outputStream().use { output ->
                input.copyTo(output)
            }
        } ?: run {
            val systemScript = findInPath("record_android_trace")
            if (systemScript != null) {
                systemScript.copyTo(destination, overwrite = true)
            } else {
                throw TraceError(
                    "record_android_trace not found",
                    "ensure record_android_trace is in resources or PATH"
                )
            }
        }

        destination.setExecutable(true)
    }

    private fun findInPath(name: String): File? {
        val pathEnv = System.getenv("PATH") ?: return null
        val separator = if (isWindows()) ";" else ":"

        for (path in pathEnv.split(separator)) {
            val file = File(path, name)
            if (file.exists() && file.canExecute()) {
                return file
            }
        }
        return null
    }

    override fun stop() {
        if (!started) return
        started = false

        process?.let { p ->
            if (!p.isAlive) return@let

            try {
                Log.d("Sending SIGINT to record_android_trace (pid=${p.pid()})...")
                if (!isWindows()) {
                    Runtime.getRuntime().exec(arrayOf("kill", "-SIGINT", "${p.pid()}"))
                } else {
                    p.destroy()
                }
            } catch (e: Exception) {
                Log.e("Stop perfetto failed: ${e.message}")
            }
        }
    }

    override fun waitForExit() {
        val p = process ?: return
        val code = p.waitFor()
        Log.d("record_android_trace exited with code $code")

        if (!Workspace.systemTrace().exists() || Workspace.systemTrace().length() == 0L) {
            Log.e("Warning: system trace missing or empty after record_android_trace exited")
        } else {
            Log.d("System trace ready: ${Workspace.systemTrace().length()} bytes")
        }
    }

    /**
     * 处理采集结果，支持两种模式：
     * - **合并模式**（默认）：系统 trace + app 采样 trace 合并为单个 .perfetto 文件
     * - **纯系统模式**（降级）：App 无法连接时，直接将系统 trace 作为输出，跳过 app 采样合并
     *
     * [systemOnly] 由 [CaptureCommand] 在 app HTTP 服务不可达时设置为 true。
     */
    var systemOnly: Boolean = false

    override fun process() {
        val sysTrace = Workspace.systemTrace()
        if (!sysTrace.exists()) {
            throw TraceError(
                "systrace file not found: $sysTrace",
                "your device may not support perfetto. retry with `-mode simple`"
            )
        }

        val sysTraceSize = sysTrace.length()
        Log.d("System trace: $sysTrace ($sysTraceSize bytes)")
        if (sysTraceSize == 0L) {
            throw TraceError(
                "system trace is empty: $sysTrace",
                "perfetto capture may have failed, check device connection"
            )
        }

        val output = Workspace.output()

        if (systemOnly) {
            // 降级模式：直接把系统 trace 复制为输出，不合并 app 采样
            Log.w("System-only mode: output contains system trace only (no app sampling data).")
            sysTrace.copyTo(output, overwrite = true)
            Log.green("System trace completed: ${output.absolutePath} ($sysTraceSize bytes)")
            return
        }

        val sampleTrace = SamplingDecoder.decode()
            ?: throw TraceError("decode app sample trace failed", null)

        Log.d("Writing trace: ${output.absolutePath}")
        Log.d("System trace at: ${sysTrace.absolutePath}")

        val appTrace = File(output.parent, "app_trace.pb")
        appTrace.outputStream().use { appOut ->
            sampleTrace.marshal(appOut)
        }
        Log.d("App trace: ${appTrace.absolutePath} (${appTrace.length()} bytes)")
        Log.green("Separate traces for debugging:")
        Log.green("  System: ${sysTrace.absolutePath} ($sysTraceSize bytes)")
        Log.green("  App:    ${appTrace.absolutePath} (${appTrace.length()} bytes)")

        // Perfetto trace = raw protobuf Trace messages concatenated;
        // each packet is [field_tag=0x0A][varint_len][TracePacket bytes].
        // Concatenation merges the repeated `packet` field per protobuf spec.
        output.outputStream().use { out ->
            sysTrace.inputStream().use { it.copyTo(out) }
            sampleTrace.marshal(out)
        }

        Log.d("Merged trace: ${output.absolutePath} (${output.length()} bytes)")
    }

    override fun cleanup() {
        stop()
    }

    override fun print(withError: Boolean, listener: (String) -> Unit) {
        process?.let { p ->
            Thread {
                p.inputStream.bufferedReader().forEachLine { line ->
                    if (started) {
                        listener(line)
                        Log.d(line)
                    }
                }
            }.start()

            if (withError) {
                Thread {
                    p.errorStream.bufferedReader().forEachLine { line ->
                        if (started) {
                            listener(line)
                            Log.e(line)
                        }
                    }
                }.start()
            }
        }
    }

    private fun isMacOS() = System.getProperty("os.name").lowercase().contains("mac")
    private fun isWindows() = System.getProperty("os.name").lowercase().contains("windows")
}
