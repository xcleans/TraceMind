package com.aspect.atrace.tool.command

import com.aspect.atrace.tool.adb.Adb
import com.aspect.atrace.tool.capture.LiteCapture
import com.aspect.atrace.tool.capture.PerfettoCapture
import com.aspect.atrace.tool.capture.SystemCapture
import com.aspect.atrace.tool.core.Arguments
import com.aspect.atrace.tool.core.GlobalArgs
import com.aspect.atrace.tool.core.JsonOutput
import com.aspect.atrace.tool.core.Log
import com.aspect.atrace.tool.core.TraceError
import com.aspect.atrace.tool.core.Workspace
import com.aspect.atrace.tool.http.HttpClient
import java.util.Scanner
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.locks.LockSupport

/**
 * `atrace-tool [capture] -a <pkg> -t <sec> [options]`
 *
 * Captures a merged Perfetto system trace + ATrace app sampling trace.
 * This is the default subcommand (backward-compatible with the original CLI).
 *
 * With --json emits a single JSON object:
 *   { "status": "success", "merged_trace": "...", "size_kb": N, ... }
 */
class CaptureCommand(private val args: Array<String>, private val globalArgs: GlobalArgs) {

    fun execute() {
        var adbForwarded = false
        var appConnected = false   // app HTTP 服务是否可达
        var capture: SystemCapture? = null

        try {
            val arg = Arguments.init(args)
            Log.debugEnabled = arg.debug

            Adb.init(arg.serial)

            capture = selectCapture(arg)

            val latch = CountDownLatch(1)
            val sysCapture = capture

            val captureThread = Thread {
                if (sysCapture is PerfettoCapture) {
                    try {
                        sysCapture.start(arg.systraceArgs)
                        sysCapture.print(true) { if (latch.count > 0) latch.countDown() }
                        sysCapture.waitForExit()
                    } catch (e: Throwable) {
                        Log.e(e.toString())
                    }
                } else {
                    sysCapture.start(arg.systraceArgs)
                    latch.countDown()
                }
            }
            captureThread.start()

            if (!latch.await(5, TimeUnit.SECONDS)) Log.d("Waiting for Perfetto to start...")

            Log.blue("Start tracing...")

            // 是否重启
            if (arg.restart) {
                Adb.forceStop(arg.appName)
                val launcher = arg.launcher ?: Adb.getLauncher(arg.appName)
                Adb.startApp(launcher)
                Thread.sleep(2000)
            }

            // 尝试连接 App HTTP 服务：失败时降级为纯系统 trace，不中断流程
            if (!arg.waitStart) {
                appConnected = HttpClient.trySetupForward()
                if (appConnected) {
                    adbForwarded = true
                    HttpClient.startTrace()
                } else {
                    Log.w("App sampling disabled. Only system trace will be captured.")
                    if (sysCapture is PerfettoCapture) sysCapture.systemOnly = true
                }
            }

            if (arg.interactiveTracing) {
                Log.blue("Press Enter to stop tracing...")
                Scanner(System.`in`).nextLine()
            } else {
                Log.blue("Tracing for ${arg.timeInSeconds} seconds...")
                LockSupport.parkNanos(arg.timeInSeconds!!.toLong() * 1_000_000_000L)
            }

            Log.blue("Stop tracing...")

            // waitStart 场景：等待采集结束后再尝试连接（也允许降级）
            if (arg.waitStart && !adbForwarded) {
                appConnected = HttpClient.trySetupForward()
                if (appConnected) {
                    adbForwarded = true
                } else {
                    if (sysCapture is PerfettoCapture) sysCapture.systemOnly = true
                }
            }

            if (appConnected) {
                HttpClient.stopTrace()
            }

            sysCapture.stop()
            captureThread.join()

            if (appConnected) {
                Log.blue("Downloading trace data...")
                HttpClient.download("sampling", Workspace.samplingTrace())
                HttpClient.download("sampling-mapping", Workspace.samplingMapping())
                showBufferUsage()
            }

            Log.blue("Processing trace data...")
            sysCapture.process()

            val output = Workspace.output()
            Log.green("Trace completed: ${output.absolutePath}")

            if (globalArgs.json) {
                println(
                    JsonOutput.success(
                        mapOf(
                            "merged_trace" to output.absolutePath,
                            "size_kb" to (output.length() / 1024),
                            "package" to arg.appName,
                            "duration_s" to (arg.timeInSeconds ?: 0),
                            "system_only" to !appConnected,
                        )
                    )
                )
            }
        } catch (e: Throwable) {
            val msg = e.message ?: e.toString()
            val hint = if (e is TraceError) e.prompt else null
            if (globalArgs.json) {
                println(JsonOutput.error(msg, hint))
            } else {
                when (e) {
                    is TraceError -> {
                        Log.e("Error: $msg")
                        hint?.let { Log.e("Tips: $it") }
                    }

                    else -> Log.e(e.stackTraceToString())
                }
            }
        } finally {
            capture?.cleanup()
            if (Adb.isConnected() && adbForwarded) {
                HttpClient.cleanTrace()
                HttpClient.removeForward()
            }
        }
    }

    private fun selectCapture(arg: Arguments): SystemCapture {
        return when (arg.mode) {
            "perfetto" -> PerfettoCapture()
            "simple", "lite" -> LiteCapture()
            null -> {
                val sdk = Adb.getSdkVersion()
                Log.d("Device SDK: $sdk")
                if (sdk >= 28) {
                    Log.i("Using Perfetto capture (API $sdk)")
                    PerfettoCapture()
                } else {
                    Log.i("Using Lite capture (API $sdk)")
                    LiteCapture()
                }
            }

            else -> throw TraceError(
                "unknown mode: ${arg.mode}",
                "only `-mode perfetto` or `-mode simple` supported"
            )
        }
    }

    private fun showBufferUsage() {
        try {
            if (Log.debugEnabled) {
                HttpClient.printDebugInfo()
            } else {
                val usage = HttpClient.getBufferUsage() ?: return
                if (!usage.isOverflow) {
                    Log.blue("Buffer usage: ${usage.used}/${usage.capacity} (${usage.percent}%)")
                } else {
                    Log.red("Buffer overflow! Used: ${usage.used}, Capacity: ${usage.capacity}")
                    Log.red("Increase buffer size with: -maxAppTraceBufferSize ${usage.used}")
                }
            }
        } catch (e: Throwable) {
            if (Log.debugEnabled) e.printStackTrace()
        }
    }
}
