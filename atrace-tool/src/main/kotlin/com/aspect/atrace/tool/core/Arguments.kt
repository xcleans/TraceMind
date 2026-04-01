package com.aspect.atrace.tool.core

import java.io.File

/**
 * 命令行参数解析
 */
class Arguments private constructor(args: Array<String>) {
    
    /** 应用包名 */
    val appName: String
    
    /** 采集时间(秒) */
    val timeInSeconds: Int?
    
    /** 交互式采集模式 */
    val interactiveTracing: Boolean
    
    /** 输出路径 */
    val outputPath: String
    
    /** 采集模式: perfetto / simple */
    val mode: String?
    
    /** 是否重启应用 */
    val restart: Boolean
    
    /** 是否等待应用启动 */
    val waitStart: Boolean
    
    /** 应用 Trace 缓冲区大小 */
    val maxAppTraceBufferSize: Int
    
    /** 采样间隔(纳秒) */
    val sampleIntervalNs: Long
    
    /** mapping 文件路径 */
    val mappingPath: String?
    
    /** 启动 Activity */
    val launcher: String?
    
    /** ADB 设备序列号 */
    val serial: String?
    
    /** 端口 */
    val port: Int
    
    /** 调试模式 */
    val debug: Boolean
    
    /** Perfetto 配置文件路径 */
    val perfettoConfig: String?
    
    /** Perfetto ring buffer 大小 (如 "64mb") */
    val bufferSize: String
    
    /** 传递给 systrace 的参数 */
    val systraceArgs: Array<String>
    
    init {
        val parser = Parser(args)
        
        appName = parser.appName 
            ?: throw TraceError("missing -a \$appName", usage())
        timeInSeconds = parser.timeInSeconds
        interactiveTracing = parser.timeInSeconds == null
        outputPath = Workspace.initDefault(appName, parser.outputPath)
        mode = parser.mode
        restart = parser.restart
        waitStart = parser.waitStart
        maxAppTraceBufferSize = parser.maxAppTraceBufferSize
        sampleIntervalNs = parser.sampleIntervalNs
        mappingPath = parser.mappingPath
        launcher = parser.launcher
        serial = parser.serial
        port = parser.port
        debug = parser.debug
        perfettoConfig = parser.perfettoConfig
        bufferSize = parser.bufferSize
        systraceArgs = parser.getSystraceArgs()
        
        // 验证参数
        if (perfettoConfig != null && !File(perfettoConfig).exists()) {
            throw TraceError("config file not exist: $perfettoConfig", "check your config file path")
        }
        
        if (mappingPath != null && !File(mappingPath).exists()) {
            throw TraceError("mapping file not exist: $mappingPath", "check your mapping file path")
        }
        
        if (timeInSeconds != null && timeInSeconds <= 0) {
            throw TraceError("-t must >= 0", null)
        }
    }
    
    private class Parser(args: Array<String>) {
        var appName: String? = null
        var timeInSeconds: Int? = null
        var outputPath: String? = null
        var mode: String? = null
        var restart = false
        var waitStart = false
        var maxAppTraceBufferSize = 100 * 1024 * 1024 // 100MB
        var sampleIntervalNs = 0L
        var mappingPath: String? = null
        var launcher: String? = null
        var serial: String? = null
        var port = 9090
        var debug = false
        var perfettoConfig: String? = null
        var bufferSize = "64mb"
        
        private val systraceArgList = mutableListOf<String>()
        
        init {
            parse(args)
        }
        
        private fun parse(args: Array<String>) {
            var i = 0
            while (i < args.size) {
                val arg = args[i++]
                when (arg) {
                    "-a" -> {
                        ensureValue(args, i)
                        appName = args[i++]
                    }
                    "-t" -> {
                        ensureValue(args, i)
                        val time = args[i++]
                        timeInSeconds = try {
                            if (time.endsWith("s")) {
                                time.dropLast(1).toInt()
                            } else {
                                time.toInt()
                            }
                        } catch (e: NumberFormatException) {
                            throw TraceError("can not parse `-t $time`", "please -t with valid number")
                        }
                    }
                    "-o" -> {
                        ensureValue(args, i)
                        outputPath = args[i++]
                    }
                    "-m" -> {
                        ensureValue(args, i)
                        mappingPath = args[i++]
                    }
                    "-mode" -> {
                        ensureValue(args, i)
                        mode = args[i++]
                    }
                    "-s" -> {
                        ensureValue(args, i)
                        serial = args[i++]
                    }
                    "-port" -> {
                        ensureValue(args, i)
                        port = args[i++].toInt()
                    }
                    "-sampleInterval" -> {
                        ensureValue(args, i)
                        sampleIntervalNs = args[i++].toLong()
                    }
                    "-maxAppTraceBufferSize" -> {
                        ensureValue(args, i)
                        maxAppTraceBufferSize = args[i++].toInt()
                    }
                    "-launcher" -> {
                        ensureValue(args, i)
                        launcher = args[i++]
                    }
                    "-c", "--config" -> {
                        ensureValue(args, i)
                        perfettoConfig = args[i++]
                    }
                    "-b", "--buffer" -> {
                        ensureValue(args, i)
                        bufferSize = args[i++]
                    }
                    "-r" -> restart = true
                    "-w" -> waitStart = true
                    "-debug" -> debug = true
                    "-v", "--version" -> {
                        // 版本信息在 Main 中处理
                    }
                    "-h", "--help" -> {
                        println(usage())
                        System.exit(0)
                    }
                    else -> {
                        // 其他参数传递给 systrace
                        if (!arg.startsWith("-") || isKnownSystraceArg(arg)) {
                            systraceArgList.add(arg)
                        }
                    }
                }
            }
        }
        
        private fun isKnownSystraceArg(arg: String): Boolean {
            return arg in listOf("-k", "--ktrace")
        }
        
        private fun ensureValue(args: Array<String>, index: Int) {
            if (index >= args.size) {
                throw TraceError("value not present for key: ${args[index - 1]}", "check your command")
            }
        }
        
        fun getSystraceArgs(): Array<String> {
            // 如果没有指定 category，添加默认的 sched
            val hasCategory = systraceArgList.any { !it.startsWith("-") }
            if (!hasCategory) {
                systraceArgList.add("sched")
            }
            return systraceArgList.toTypedArray()
        }
    }
    
    companion object {
        private var instance: Arguments? = null
        
        fun init(args: Array<String>): Arguments {
            instance = Arguments(args)
            return instance!!
        }
        
        fun get(): Arguments {
            return instance ?: throw TraceError("Arguments not initialized", null)
        }
        
        fun usage(): String = """
            |Usage: java -jar atrace-tool.jar [options] [systrace-categories]
            |
            |Options:
            |  -a <package>      Target application package name (required)
            |  -t <seconds>      Trace duration in seconds (interactive mode if not set)
            |  -o <path>         Output trace file path (.pb)
            |  -m <path>         Proguard mapping file path
            |  -mode <mode>      Capture mode: perfetto (Android 9+) or simple
            |  -c <config>       Perfetto config file (.txtpb / .pbtxt)
            |  -b <size>         Perfetto ring buffer size (e.g. 64mb, default: 64mb)
            |  -s <serial>       Target device serial number
            |  -port <port>      Local port for adb forward + HTTP client (default: 9090); device port is discovered via ContentProvider or atrace-port dir
            |  -r                Restart the app before tracing
            |  -w                Wait for app to start
            |  -debug            Enable debug output
            |  -launcher <name>  Specify launch activity
            |  -sampleInterval   Sample interval in nanoseconds
            |  -maxAppTraceBufferSize  Max app trace buffer size
            |  -h, --help        Show this help
            |  -v, --version     Show version
            |
            |Systrace Categories:
            |  sched, freq, idle, am, wm, gfx, view, webview, sm, etc.
            |
            |Examples:
            |  java -jar atrace-tool.jar -a com.example.app -t 10
            |  java -jar atrace-tool.jar -a com.example.app -t 10 -o output.pb sched gfx view
            |  java -jar atrace-tool.jar -a com.example.app -t 10 -b 64mb -c config.txtpb
        """.trimMargin()
    }
}

