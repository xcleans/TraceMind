package com.aspect.atrace.tool.trace

/**
 * 堆栈项
 */
data class StackItem(
    val method: MethodSymbol,
    val arg: String? = null
) {
    override fun toString(): String {
        return if (arg != null) {
            "${method.symbol()} [$arg]"
        } else {
            method.symbol()
        }
    }
}
