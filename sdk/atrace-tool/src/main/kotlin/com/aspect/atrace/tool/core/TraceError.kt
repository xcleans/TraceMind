package com.aspect.atrace.tool.core

/**
 * Trace 错误异常
 */
class TraceError(
    message: String,
    val prompt: String? = null,
    cause: Throwable? = null
) : RuntimeException(message, cause) {
    
    override fun toString(): String {
        return buildString {
            append("TraceError: $message")
            if (prompt != null) {
                append("\n  Tips: $prompt")
            }
        }
    }
}

