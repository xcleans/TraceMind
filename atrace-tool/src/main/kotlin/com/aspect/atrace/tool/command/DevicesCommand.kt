package com.aspect.atrace.tool.command

import com.aspect.atrace.tool.core.GlobalArgs
import com.aspect.atrace.tool.core.JsonOutput
import com.aspect.atrace.tool.core.Log
import java.io.File

/**
 * `atrace-tool devices [--json]`
 *
 * Lists connected Android devices with their model, SDK level and ABI.
 *
 * With --json emits:
 *   { "status": "success", "count": N, "devices": [ { "serial": ..., "model": ..., "sdk": N, "abi": ... }, ... ] }
 */
class DevicesCommand(private val globalArgs: GlobalArgs) {

    fun execute() {
        val adbPath = findAdb()
        if (adbPath == null) {
            emitError("adb not found", "add ANDROID_HOME/platform-tools to PATH")
            return
        }

        try {
            val raw = runAdb(adbPath, "devices", "-l")
            // adb devices: serial and "device" are separated by tab; adb devices -l uses spaces
            val deviceLines = raw.lines()
                .drop(1)
                .filter { it.isNotBlank() }
                .mapNotNull { line ->
                    val parts = line.trim().split(Regex("\\s+"), limit = 2)
                    if (parts.size >= 2 && parts[1].startsWith("device")) parts[0] else null
                }

            val devices = deviceLines.map { serial ->
                mapOf(
                    "serial" to serial,
                    "model"  to getProperty(adbPath, serial, "ro.product.model"),
                    "sdk"    to (getProperty(adbPath, serial, "ro.build.version.sdk").toIntOrNull() ?: 0),
                    "abi"    to getProperty(adbPath, serial, "ro.product.cpu.abi"),
                )
            }

            if (globalArgs.json) {
                println(JsonOutput.success(mapOf("count" to devices.size, "devices" to devices)))
            } else {
                println("Connected devices: ${devices.size}")
                devices.forEach { d ->
                    println("  ${d["serial"]}\t${d["model"]}\tSDK ${d["sdk"]}\t(${d["abi"]})")
                }
            }
        } catch (e: Exception) {
            emitError(e.message ?: "unknown error")
        }
    }

    private fun findAdb(): String? {
        val isWindows = System.getProperty("os.name").lowercase().contains("windows")
        val adbName   = if (isWindows) "adb.exe" else "adb"
        val sep       = if (isWindows) ";" else ":"

        (System.getenv("PATH") ?: "").split(sep).forEach { dir ->
            val f = File(dir, adbName)
            if (f.exists()) return f.absolutePath
        }
        listOf(System.getenv("ANDROID_HOME"), System.getenv("ANDROID_SDK_ROOT")).forEach { home ->
            if (home != null) {
                val f = File(home, "platform-tools/$adbName")
                if (f.exists()) return f.absolutePath
            }
        }
        return null
    }

    private fun runAdb(adbPath: String, vararg args: String): String {
        val p = ProcessBuilder(listOf(adbPath) + args.toList())
            .redirectErrorStream(true)
            .start()
        val out = p.inputStream.bufferedReader().readText()
        p.waitFor()
        return out
    }

    private fun getProperty(adbPath: String, serial: String, key: String): String {
        return try {
            val p = ProcessBuilder(listOf(adbPath, "-s", serial, "shell", "getprop", key))
                .redirectErrorStream(true)
                .start()
            val v = p.inputStream.bufferedReader().readText().trim()
            p.waitFor()
            v
        } catch (e: Exception) {
            ""
        }
    }

    private fun emitError(message: String, hint: String? = null) {
        if (globalArgs.json) println(JsonOutput.error(message, hint))
        else {
            Log.e(message)
            hint?.let { Log.e("Tips: $it") }
        }
    }
}
