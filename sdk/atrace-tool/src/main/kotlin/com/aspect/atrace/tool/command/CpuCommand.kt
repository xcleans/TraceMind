package com.aspect.atrace.tool.command

import com.aspect.atrace.tool.adb.Adb
import com.aspect.atrace.tool.core.GlobalArgs
import com.aspect.atrace.tool.core.JsonOutput
import com.aspect.atrace.tool.core.Log
import com.aspect.atrace.tool.core.TraceError
import java.io.File

/**
 * `atrace-tool cpu -a <pkg> -t <sec> [options]`
 *
 * CPU profiling via on-device simpleperf.
 *
 * Event fallback chain: cpu-cycles → task-clock → instructions → cpu-clock
 * so the command works on emulators and devices with restricted PMU access.
 *
 * With --json emits:
 *   { "status": "success", "perf_data": "...", "report": "...", "event": "...", ... }
 */
class CpuCommand(private val args: Array<String>, private val globalArgs: GlobalArgs) {

    private var packageName: String? = null
    private var durationSeconds: Int  = 10
    private var outputDir: String     = "/tmp/atrace"
    private var event: String         = "cpu-cycles"
    private var callGraph: String     = "dwarf"
    private var freq: Int             = 1000
    private var serial: String?       = null
    private var debug: Boolean        = false

    fun execute() {
        parseArgs()

        val pkg = packageName ?: return emitError(
            "missing -a <package>",
            "usage: atrace-tool cpu -a <package> -t <seconds>"
        )

        try {
            Adb.init(serial)
        } catch (e: TraceError) {
            return emitError(e.message ?: "ADB init failed", e.prompt)
        }

        Log.debugEnabled = debug
        Log.d("CPU profiling: pkg=$pkg dur=${durationSeconds}s event=$event cg=$callGraph freq=$freq")

        val pid = Adb.getPid(pkg) ?: return emitError(
            "Process not found: $pkg",
            "make sure the app is running before profiling"
        )

        val out = File(outputDir).apply { mkdirs() }
        val ts  = System.currentTimeMillis() / 1000
        val remotePath  = "/data/local/tmp/perf_$ts.data"
        val localPerf   = File(out, "perf_$ts.data")
        val localReport = File(out, "perf_${ts}_report.txt")

        val simpleperfCmd = findSimpleperf()

        // Event fallback: start from the requested event, then try alternatives
        val fallbackChain = listOf("cpu-cycles", "task-clock", "instructions", "cpu-clock")
        val eventsToTry = if (event in fallbackChain)
            fallbackChain.dropWhile { it != event }
        else
            listOf(event) + fallbackChain

        var usedEvent = event
        var lastError = ""
        var recorded  = false

        for (tryEvent in eventsToTry) {
            Log.d("Trying event: $tryEvent")
            val r = Adb.callWithResult(
                "shell", simpleperfCmd, "record",
                "-p", "$pid",
                "-e", tryEvent,
                "-f", "$freq",
                "--call-graph", callGraph,
                "--duration", "$durationSeconds",
                "-o", remotePath,
            )
            if (r.exitCode == 0) {
                usedEvent = tryEvent
                recorded  = true
                break
            }
            lastError = r.stderr.trim()
            Adb.callSafe("shell", "rm", "-f", remotePath)
            // Hard fail on permission errors; soft fail on unsupported events
            if ("Permission denied" in lastError || "is not supported" !in lastError) {
                return emitError("simpleperf record failed: $lastError")
            }
        }

        if (!recorded) {
            return emitError("simpleperf record failed (no supported event): $lastError")
        }

        Adb.callSafe("pull", remotePath, localPerf.absolutePath)
        if (!localPerf.exists()) {
            return emitError("Failed to pull perf.data from device")
        }

        // Generate on-device text report
        val reportResult = Adb.callWithResult(
            "shell", simpleperfCmd, "report",
            "-i", remotePath,
            "--sort", "comm,dso,symbol",
            "-n", "--percent-limit", "0.5",
        )
        localReport.writeText(reportResult.stdout)
        Adb.callSafe("shell", "rm", "-f", remotePath)

        val reportPreview = reportResult.stdout.lines().take(80).joinToString("\n")

        Log.green("CPU profile: ${localPerf.absolutePath}")
        Log.green("Report:      ${localReport.absolutePath}")

        if (globalArgs.json) {
            println(
                JsonOutput.success(
                    mapOf(
                        "perf_data"      to localPerf.absolutePath,
                        "report"         to localReport.absolutePath,
                        "report_preview" to reportPreview,
                        "event"          to usedEvent,
                        "duration_s"     to durationSeconds,
                        "pid"            to pid,
                        "call_graph"     to callGraph,
                        "freq"           to freq,
                    )
                )
            )
        }
    }

    // Try /system/bin/simpleperf, fall back to bare name
    private fun findSimpleperf(): String {
        val r = Adb.callWithResult("shell", "test", "-x", "/system/bin/simpleperf")
        return if (r.exitCode == 0) "/system/bin/simpleperf" else "simpleperf"
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
                "-a"            -> packageName    = args.getOrNull(i++)
                "-t"            -> durationSeconds = args.getOrNull(i++)?.toIntOrNull() ?: durationSeconds
                "-o"            -> outputDir       = args.getOrNull(i++) ?: outputDir
                "-e"            -> event           = args.getOrNull(i++) ?: event
                "-f"            -> freq            = args.getOrNull(i++)?.toIntOrNull() ?: freq
                "-s"            -> serial          = args.getOrNull(i++)
                "--call-graph"  -> callGraph       = args.getOrNull(i++) ?: callGraph
                "-debug"        -> debug           = true
                "-h", "--help"  -> {
                    println(
                        """
                        |Usage: atrace-tool cpu -a <package> [options]
                        |
                        |  -a <package>         Target app package (required)
                        |  -t <seconds>         Duration (default: 10)
                        |  -o <dir>             Output directory (default: /tmp/atrace)
                        |  -e <event>           PMU event (default: cpu-cycles)
                        |  -f <freq>            Sampling frequency Hz (default: 1000)
                        |  --call-graph <mode>  dwarf (default) or fp
                        |  -s <serial>          ADB device serial
                        |  --json               Machine-readable output
                        """.trimMargin()
                    )
                    kotlin.system.exitProcess(0)
                }
                else -> Log.d("Unknown cpu arg: $arg")
            }
        }
    }
}
