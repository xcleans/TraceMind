package com.aspect.atrace.tool.adb

import com.aspect.atrace.tool.core.Log
import com.aspect.atrace.tool.core.TraceError
import java.io.File
import java.io.StringWriter

/**
 * ADB 通信封装
 */
data class AdbResult(val exitCode: Int, val stdout: String, val stderr: String)

object Adb {

    private var serial: String? = null
    private var connected = false
    private lateinit var adbPath: String
    
    fun init(serial: String?) {
        this.serial = serial
        resolveAdbPath()
        checkDevices()
    }
    
    private fun resolveAdbPath() {
        val pathEnv = System.getenv("PATH") ?: ""
        val separator = if (isWindows()) ";" else ":"
        val adbName = if (isWindows()) "adb.exe" else "adb"
        
        for (path in pathEnv.split(separator)) {
            val file = File(path, adbName)
            if (file.exists()) {
                adbPath = file.absolutePath
                Log.d("Found adb: $adbPath")
                return
            }
        }
        
        // 尝试 ANDROID_HOME
        val androidHome = System.getenv("ANDROID_HOME") ?: System.getenv("ANDROID_SDK_ROOT")
        if (androidHome != null) {
            val file = File(androidHome, "platform-tools/$adbName")
            if (file.exists()) {
                adbPath = file.absolutePath
                Log.d("Found adb in ANDROID_HOME: $adbPath")
                return
            }
        }
        
        throw TraceError("adb not found in PATH", "export PATH with \$ANDROID_HOME/platform-tools")
    }
    
    private fun checkDevices() {
        val devices = callString("devices").trim()
        val lines = devices.split("\n").drop(1).filter { it.isNotBlank() && it.contains("device") }
        
        when {
            lines.isEmpty() -> throw TraceError("no device connected", "connect your device via USB")
            lines.size > 1 && serial == null -> throw TraceError(
                "multiple devices connected: ${lines.size}",
                "use -s <serial> to specify device"
            )
        }
        
        connected = true
        Log.d("ADB connected")
    }
    
    fun isConnected() = connected

    /** Expose the resolved adb binary path (e.g. for DevicesCommand). */
    fun getAdbPath(): String = adbPath

    /** Run `adb shell getprop <key>` and return trimmed value. */
    fun getProperty(key: String): String {
        return try { callString("shell", "getprop", key).trim() } catch (e: Exception) { "" }
    }
    
    private fun isWindows() = System.getProperty("os.name").lowercase().contains("windows")
    
    /**
     * 执行 ADB 命令并返回输出
     */
    fun callString(vararg cmd: String): String {
        val writer = StringWriter()
        call(writer, *cmd)
        return writer.toString()
    }
    
    /**
     * 执行 ADB 命令
     */
    fun call(vararg cmd: String) {
        call(null, *cmd)
    }
    
    /**
     * 安全执行 ADB 命令(忽略错误)
     */
    fun callSafe(vararg cmd: String) {
        try {
            call(null, *cmd)
        } catch (e: Exception) {
            Log.d("ADB call failed: ${e.message}")
        }
    }

    /** Run an ADB command and return exit code + stdout + stderr without throwing. */
    fun callWithResult(vararg cmds: String): AdbResult {
        val fullCmd = buildList {
            add(adbPath)
            if (serial != null) { add("-s"); add(serial!!) }
            addAll(cmds.toList())
        }
        val process = ProcessBuilder(fullCmd).redirectErrorStream(false).start()
        val stdout = process.inputStream.bufferedReader().readText()
        val stderr = process.errorStream.bufferedReader().readText()
        val code = process.waitFor()
        Log.d("adb ${cmds.joinToString(" ")} → exit=$code")
        return AdbResult(code, stdout, stderr)
    }

    private fun call(writer: StringWriter?, vararg cmds: String) {
        val fullCmd = buildList {
            add(adbPath)
            if (serial != null) {
                add("-s")
                add(serial!!)
            }
            addAll(cmds.toList())
        }
        
        Log.d("Run: ${fullCmd.joinToString(" ")}")
        
        val process = ProcessBuilder(fullCmd)
            .redirectErrorStream(false)
            .start()
        
        val output = process.inputStream.bufferedReader().readText()
        val error = process.errorStream.bufferedReader().readText()
        
        if (writer != null) {
            writer.write(output)
            if (error.isNotEmpty()) {
                writer.write(error)
            }
        } else {
            if (output.isNotEmpty()) Log.d(output.trim())
            if (error.isNotEmpty()) Log.d(error.trim())
        }
        
        val code = process.waitFor()
        if (code != 0 && writer == null) {
            throw TraceError(
                "adb ${cmds.joinToString(" ")} returned $code",
                "check device connection"
            )
        }
    }
    
    /**
     * 设置端口转发
     */
    fun forward(localPort: Int, remotePort: Int) {
        call("forward", "tcp:$localPort", "tcp:$remotePort")
        Log.d("Port forward: $localPort -> $remotePort")
    }
    
    /**
     * 移除端口转发
     */
    fun removeForward(localPort: Int) {
        callSafe("forward", "--remove", "tcp:$localPort")
    }
    
    /**
     * 获取设备 Android SDK 版本
     */
    fun getSdkVersion(): Int {
        val version = callString("shell", "getprop", "ro.build.version.sdk").trim()
        return version.toIntOrNull() ?: 0
    }
    
    /**
     * 获取应用 PID
     */
    fun getPid(packageName: String): Int? {
        val result = callString("shell", "pidof", packageName).trim()
        return result.toIntOrNull()
    }
    
    /**
     * 强制停止应用
     */
    fun forceStop(packageName: String) {
        call("shell", "am", "force-stop", packageName)
    }
    
    /**
     * 启动应用
     */
    fun startApp(launcher: String) {
        call("shell", "am", "start", "-n", launcher, "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER")
    }
    
    /**
     * 获取应用启动 Activity
     */
    fun getLauncher(packageName: String): String {
        // 尝试精确获取
        try {
            val dump = callString("shell", "cmd", "package", "resolve-activity",
                "-a", "android.intent.action.MAIN",
                "-c", "android.intent.category.LAUNCHER",
                packageName)
            
            for (line in dump.lines()) {
                val trimmed = line.trim()
                if (trimmed.startsWith("name=")) {
                    val activity = trimmed.substringAfter("name=")
                    if (!activity.contains("ResolverActivity")) {
                        return "$packageName/$activity"
                    }
                }
            }
        } catch (e: Exception) {
            Log.d("Precise launcher detection failed: ${e.message}")
        }
        
        // 备用方法
        return getLauncherBackup(packageName)
    }
    
    private fun getLauncherBackup(packageName: String): String {
        val dump = callString("shell", "dumpsys", "package", packageName)
        var foundAction = false
        var foundCategory = false
        var currentLauncher: String? = null
        
        for (line in dump.lines()) {
            val trimmed = line.trim()
            when {
                trimmed == "android.intent.action.MAIN:" -> {
                    foundAction = false
                    foundCategory = false
                    currentLauncher = null
                }
                trimmed.startsWith("Action:") && trimmed.contains("android.intent.action.MAIN") -> {
                    foundAction = true
                }
                trimmed.startsWith("Category:") && trimmed.contains("android.intent.category.LAUNCHER") -> {
                    foundCategory = true
                }
                currentLauncher == null && !trimmed.startsWith("Action:") && !trimmed.startsWith("Category:") -> {
                    val parts = trimmed.split(" ")
                    if (parts.size >= 2) {
                        currentLauncher = parts[1]
                    }
                }
            }
            
            if (foundAction && foundCategory && currentLauncher != null) {
                return currentLauncher
            }
        }
        
        throw TraceError(
            "cannot find launcher for $packageName",
            "have you installed your app? or pass a wrong package name?"
        )
    }
    
    /**
     * 读取应用目录下的文件列表
     */
    fun listFiles(dirPath: String): List<String> {
        val result = callString("shell", "ls", dirPath)
        return result.lines().filter { it.isNotBlank() }
    }
}

