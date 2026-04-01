package com.aspect.atrace.tool.trace

/**
 * 方法符号信息
 */
data class MethodSymbol(
    val className: String,
    val methodName: String,
    val signature: String
) {
    /**
     * 获取完整符号名
     */
    fun symbol(): String {
        return "$className.$methodName$signature"
    }
    
    /**
     * 获取简短显示名
     */
    fun shortName(): String {
        val simpleClassName = className.substringAfterLast('.')
        return "$simpleClassName.$methodName"
    }
    
    override fun toString(): String = symbol()
    
    companion object {
        /**
         * 从完整字符串解析
         */
        fun parse(fullName: String): MethodSymbol {
            // 格式: className.methodName(signature)returnType
            val lastDot = fullName.lastIndexOf('.')
            val parenStart = fullName.indexOf('(')
            
            return if (lastDot > 0 && parenStart > lastDot) {
                MethodSymbol(
                    className = fullName.substring(0, lastDot),
                    methodName = fullName.substring(lastDot + 1, parenStart),
                    signature = fullName.substring(parenStart)
                )
            } else if (lastDot > 0) {
                MethodSymbol(
                    className = fullName.substring(0, lastDot),
                    methodName = fullName.substring(lastDot + 1),
                    signature = ""
                )
            } else {
                MethodSymbol(
                    className = "",
                    methodName = fullName,
                    signature = ""
                )
            }
        }
    }
}
