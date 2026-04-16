package com.aspect.atrace.tool.command

import com.aspect.atrace.tool.adb.Adb
import com.aspect.atrace.tool.core.GlobalArgs
import com.aspect.atrace.tool.core.JsonOutput
import com.aspect.atrace.tool.core.Log
import com.aspect.atrace.tool.core.TraceError
import java.io.File

/**
 * `atrace-tool heap -a <pkg> -t <sec> [options]`
 *
 * Heap memory profiling via Perfetto.
 *
 * Modes (see https://perfetto.dev/docs/getting-started/memory-profiling):
 *   native     Native (C/C++) heap: samples malloc/free callstacks (heapprofd). Not retroactive.
 *   java-dump  Java/Kotlin heap: full heap dump with retention graph at trace end (java_hprof).
 *
 * Prerequisites: Android 10+ (API 29+), app must be Profileable or Debuggable in manifest.
 * Process name = package name (first component of process cmdline, e.g. adb shell ps -A NAME column).
 *
 * With --json emits:
 *   { "status": "success", "trace": "...", "size_kb": N, "package": "...", "mode": "native"|"java-dump", ... }
 */
class HeapCommand(private val args: Array<String>, private val globalArgs: GlobalArgs) {

    /** "native" = heapprofd (malloc/free sampling), "java-dump" = java_hprof (full heap dump) */
    private var mode: String            = "native"
    private var packageName: String?    = null
    private var durationSeconds: Int    = 10
    private var outputFile: String?     = null
    private var samplingBytes: Int      = 4096
    private var blockClient: Boolean    = true
    private var serial: String?         = null
    private var debug: Boolean          = false

    private val docUrl = "https://perfetto.dev/docs/getting-started/memory-profiling"
    private val profileableHint = "App must be Profileable or Debuggable (user builds). See: $docUrl"

    fun execute() {
        parseArgs()

        val pkg = packageName ?: return emitError(
            "missing -a <package>",
            "usage: atrace-tool heap -a <package> -t <seconds> [--mode native|java-dump]"
        )

        try {
            Adb.init(serial)
        } catch (e: TraceError) {
            return emitError(e.message ?: "ADB init failed", e.prompt)
        }

        val sdk = Adb.getSdkVersion()
        if (sdk < 29) {
            return emitError(
                "Heap profiling requires Android 10+ (API 29+), device API is $sdk",
                "Use a device/emulator with API 29 or higher. $docUrl"
            )
        }

        Log.debugEnabled = debug
        Log.d("Heap profiling: mode=$mode pkg=$pkg dur=${durationSeconds}s sampling=${samplingBytes}B block=$blockClient")

        val ts = System.currentTimeMillis() / 1000
        val suffix = if (mode == "java-dump") "heap_dump" else "heap"
        val defaultOut = "/tmp/atrace/${suffix}_$ts.perfetto"
        val localTrace = File(outputFile ?: defaultOut).also {
            it.parentFile?.mkdirs()
        }

        val config = if (mode == "java-dump") buildJavaHeapDumpConfig(pkg) else buildHeapprofdConfig(pkg)
        val scriptFile = File(System.getProperty("java.io.tmpdir"), "record_android_trace_heap_$ts")

        try {
            extractPerfettoScript(scriptFile)

            val cmd = listOf(
                scriptFile.absolutePath,
                "-o", localTrace.absolutePath,
                "-n",
                "-c", "-",
            )
            Log.d("Running: ${cmd.joinToString(" ")}")

            val process = ProcessBuilder(cmd)
                .redirectErrorStream(false)
                .start()

            process.outputStream.bufferedWriter().use { it.write(config) }

            val stdoutLines = mutableListOf<String>()
            val stderrLines = mutableListOf<String>()
            val t1 = Thread { process.inputStream.bufferedReader().forEachLine { line -> Log.d("[perfetto] $line"); stdoutLines += line } }
            val t2 = Thread { process.errorStream.bufferedReader().forEachLine { line -> Log.d("[perfetto-err] $line"); stderrLines += line } }
            t1.start(); t2.start()

            val exitCode = process.waitFor()
            t1.join(); t2.join()
            Log.d("record_android_trace exited: $exitCode")

            if (!localTrace.exists() || localTrace.length() == 0L) {
                val stderr = stderrLines.takeLast(8).joinToString("\n")
                return emitError(
                    "Heap trace not generated (exit=$exitCode)",
                    "$profileableHint. Check device connection. stderr: $stderr"
                )
            }

            Log.green("Heap profile: ${localTrace.absolutePath} (${localTrace.length() / 1024} KB)")

            if (globalArgs.json) {
                val payload = mutableMapOf<String, Any?>(
                    "trace"       to localTrace.absolutePath,
                    "size_kb"     to (localTrace.length() / 1024),
                    "package"     to pkg,
                    "duration_s"  to durationSeconds,
                    "mode"        to mode,
                    "ui_hint"     to "Open in https://ui.perfetto.dev (Query SQL for heap_profile_summary_tree / heap_graph)",
                    "doc"         to docUrl,
                )
                if (mode == "native") {
                    payload["sampling_interval_bytes"] = samplingBytes
                    payload["block_client"] = blockClient
                }
                println(JsonOutput.success(payload))
            }
        } finally {
            scriptFile.delete()
        }
    }

    /** Native heap: sample malloc/free callstacks. Not retroactive — only allocations after trace start. */
    private fun buildHeapprofdConfig(pkg: String): String = buildString {
        appendLine("duration_ms: ${durationSeconds * 1000}")
        appendLine("buffers { size_kb: 65536  fill_policy: RING_BUFFER }")
        appendLine("buffers { size_kb: 4096   fill_policy: RING_BUFFER }")
        appendLine("data_sources {")
        appendLine("  config {")
        appendLine("    name: \"android.heapprofd\"")
        appendLine("    target_buffer: 0")
        appendLine("    heapprofd_config {")
        appendLine("      sampling_interval_bytes: $samplingBytes")
        appendLine("      process_cmdline: \"$pkg\"")
        appendLine("      shmem_size_bytes: 8388608")
        appendLine("      block_client: ${if (blockClient) "true" else "false"}")
        appendLine("      all_heaps: true")
        appendLine("    }")
        appendLine("  }")
        appendLine("}")
    }

    /** Java/Kotlin heap: full dump at end of trace. Duration can be short (dump emitted at stop). */
    private fun buildJavaHeapDumpConfig(pkg: String): String = buildString {
        val durationMs = minOf(durationSeconds * 1000, 15_000)
        appendLine("duration_ms: $durationMs")
        appendLine("buffers { size_kb: 262144  fill_policy: RING_BUFFER }")
        appendLine("data_sources {")
        appendLine("  config {")
        appendLine("    name: \"android.java_hprof\"")
        appendLine("    java_hprof_config {")
        appendLine("      process_cmdline: \"$pkg\"")
        appendLine("    }")
        appendLine("  }")
        appendLine("}")
    }

    private fun extractPerfettoScript(destination: File) {
        val isWindows    = System.getProperty("os.name").lowercase().contains("windows")
        val resourceName = if (isWindows) "record_android_trace_win" else "record_android_trace"

        val stream = javaClass.getResourceAsStream("/$resourceName")
        if (stream != null) {
            stream.use { it.copyTo(destination.outputStream()) }
        } else {
            val sep = if (isWindows) ";" else ":"
            val found = (System.getenv("PATH") ?: "").split(sep)
                .map { File(it, resourceName) }
                .firstOrNull { it.exists() && it.canExecute() }
                ?: throw TraceError(
                    "record_android_trace not found",
                    "ensure it is in PATH or inside atrace-tool.jar resources"
                )
            found.copyTo(destination, overwrite = true)
        }
        destination.setExecutable(true)
    }

    private fun emitError(message: String, hint: String? = null) {
        if (globalArgs.json) println(JsonOutput.error(message, hint))
        else {
            Log.e(message)
            hint?.let { Log.e("Tips: $it") }
        }
    }

    private fun parseArgs() {
        var i = 0
        while (i < args.size) {
            when (val arg = args[i++]) {
                "-a"               -> packageName    = args.getOrNull(i++)
                "-t"               -> durationSeconds = args.getOrNull(i++)?.toIntOrNull() ?: durationSeconds
                "-o"               -> outputFile      = args.getOrNull(i++)
                "--mode"           -> mode            = args.getOrNull(i++)?.lowercase()?.takeIf { it in setOf("native", "java-dump") } ?: mode
                "--sampling-bytes" -> samplingBytes   = args.getOrNull(i++)?.toIntOrNull() ?: samplingBytes
                "--no-block"       -> blockClient     = false
                "-s"               -> serial          = args.getOrNull(i++)
                "-debug"           -> debug           = true
                "-h", "--help"     -> {
                    println(
                        """
                        |Usage: atrace-tool heap -a <package> [options]
                        |
                        |  -a <package>            Target app package (required)
                        |  -t <seconds>            Duration (default: 10)
                        |  -o <file.perfetto>      Output file path
                        |  --mode <native|java-dump>  native = malloc/free sampling (heapprofd);
                        |                          java-dump = full Java heap dump at end (java_hprof)
                        |  --sampling-bytes <N>     [native] Sampling interval bytes (default: 4096)
                        |  --no-block              [native] Non-blocking (may miss allocations)
                        |  -s <serial>             ADB device serial
                        |  --json                  Machine-readable output
                        |
                        |Prerequisites: Android 10+ (API 29+), app Profileable or Debuggable.
                        |See: $docUrl
                        """.trimMargin()
                    )
                    kotlin.system.exitProcess(0)
                }
                else -> Log.d("Unknown heap arg: $arg")
            }
        }
    }
}
