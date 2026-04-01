package com.aspect.atrace.tool.core

/**
 * 日志输出工具
 *
 * When [jsonMode] is `true` all stdout log calls are suppressed so that only
 * the single JSON object emitted by [JsonOutput] appears on stdout.  Error
 * messages are also suppressed (they are embedded in the JSON error response
 * instead of going to stderr).
 */
object Log {
    
    private const val RESET = "\u001B[0m"
    private const val RED = "\u001B[31m"
    private const val GREEN = "\u001B[32m"
    private const val YELLOW = "\u001B[33m"
    private const val BLUE = "\u001B[34m"
    private const val CYAN = "\u001B[36m"
    
    var debugEnabled = false
    /** Set to true when --json is active; suppresses all console output. */
    var jsonMode = false
    
    fun i(message: String) {
        if (!jsonMode) println(message)
    }
    
    fun d(message: String) {
        if (debugEnabled && !jsonMode) {
            println("${CYAN}[DEBUG] $message$RESET")
        }
    }
    
    fun e(message: String) {
        if (!jsonMode) System.err.println("${RED}[ERROR] $message$RESET")
    }
    
    fun w(message: String) {
        if (!jsonMode) println("${YELLOW}[WARN] $message$RESET")
    }
    
    fun blue(message: String) {
        if (!jsonMode) println("${BLUE}$message$RESET")
    }
    
    fun green(message: String) {
        if (!jsonMode) println("${GREEN}$message$RESET")
    }
    
    fun red(message: String) {
        if (!jsonMode) println("${RED}$message$RESET")
    }
}

