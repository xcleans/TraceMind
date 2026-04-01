package com.aspect.atrace.tool.core

/**
 * Global flag parsing and subcommand detection.
 *
 * Strips `--json` and the subcommand keyword from the args array, returning
 * the rest to be parsed by the individual subcommand handler.
 *
 * Supports backward-compat: if no subcommand keyword is found, defaults to
 * "capture" and all args are forwarded unchanged.
 */
data class GlobalArgs(val json: Boolean)

data class ParsedCommand(
    val globalArgs: GlobalArgs,
    /** Normalised subcommand: "capture" | "cpu" | "heap" | "devices" */
    val subCommand: String,
    /** Args with --json and the subcommand keyword removed */
    val remaining: Array<String>,
)

private val SUBCOMMAND_KEYWORDS = mapOf(
    "capture"   to "capture",
    "cpu"       to "cpu",
    "simpleperf" to "cpu",
    "heap"      to "heap",
    "heapprofd" to "heap",
    "devices"   to "devices",
)

fun parseCommand(args: Array<String>): ParsedCommand {
    var json = false
    var subCommand = ""
    val remaining = mutableListOf<String>()

    for (arg in args) {
        val normalised = SUBCOMMAND_KEYWORDS[arg]
        when {
            arg == "--json"              -> json = true
            normalised != null && subCommand.isEmpty() -> subCommand = normalised
            else                        -> remaining.add(arg)
        }
    }

    // Backward-compat: no subcommand keyword → treat everything as "capture"
    if (subCommand.isEmpty()) {
        subCommand = "capture"
        remaining.clear()
        remaining.addAll(args.filter { it != "--json" })
    }

    return ParsedCommand(GlobalArgs(json), subCommand, remaining.toTypedArray())
}
