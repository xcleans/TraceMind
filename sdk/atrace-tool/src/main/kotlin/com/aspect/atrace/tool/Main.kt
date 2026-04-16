package com.aspect.atrace.tool

import com.aspect.atrace.tool.command.CaptureCommand
import com.aspect.atrace.tool.command.CpuCommand
import com.aspect.atrace.tool.command.DevicesCommand
import com.aspect.atrace.tool.command.HeapCommand
import com.aspect.atrace.tool.core.JsonOutput
import com.aspect.atrace.tool.core.Log
import com.aspect.atrace.tool.core.parseCommand

const val VERSION = "1.0.0"

/**
 * Entry point – thin subcommand router.
 *
 * Usage:
 *   atrace-tool [--json] <command> [options]
 *
 * Commands:
 *   capture   System + app merged trace (default, backward-compatible)
 *   cpu       CPU profiling via simpleperf
 *   heap      Heap profiling via heapprofd
 *   devices   List connected Android devices
 *
 * The --json flag can appear anywhere before the subcommand keyword.
 * It suppresses all human-readable log output and emits a single JSON
 * object on stdout, suitable for MCP or CI consumption.
 */
fun main(args: Array<String>) {
    if (args.isEmpty() || args.contains("-v") || args.contains("--version")) {
        println("atrace-tool version $VERSION")
        println(helpText())
        return
    }

    val parsed = parseCommand(args)

    // Only show top-level help when invoked without a real subcommand
    if (args.none { it in setOf("capture", "cpu", "simpleperf", "heap", "heapprofd", "devices") }
        && (args.contains("-h") || args.contains("--help"))) {
        println(helpText())
        return
    }
    Log.jsonMode = parsed.globalArgs.json

    when (parsed.subCommand) {
        "capture" -> CaptureCommand(parsed.remaining, parsed.globalArgs).execute()
        "cpu"     -> CpuCommand(parsed.remaining, parsed.globalArgs).execute()
        "heap"    -> HeapCommand(parsed.remaining, parsed.globalArgs).execute()
        "devices" -> DevicesCommand(parsed.globalArgs).execute()
        else      -> {
            val msg = "unknown subcommand: ${parsed.subCommand}"
            if (parsed.globalArgs.json) println(JsonOutput.error(msg))
            else System.err.println("Error: $msg\n\n${helpText()}")
            kotlin.system.exitProcess(1)
        }
    }
}

private fun helpText() = """
    |Usage: atrace-tool [--json] <command> [options]
    |
    |Commands:
    |  capture   System + app merged Perfetto trace (default)
    |  cpu       CPU profiling via simpleperf
    |  heap      Heap memory profiling via heapprofd
    |  devices   List connected Android devices
    |
    |Global flags:
    |  --json          Machine-readable JSON output (MCP / CI friendly)
    |  -v, --version   Print version
    |  -h, --help      Show this help
    |
    |Run 'atrace-tool <command> -h' for command-specific options.
    |
    |Examples:
    |  atrace-tool capture -a com.example.app -t 10
    |  atrace-tool cpu -a com.example.app -t 10 --json
    |  atrace-tool heap -a com.example.app -t 30 --sampling-bytes 8192
    |  atrace-tool devices --json
""".trimMargin()
