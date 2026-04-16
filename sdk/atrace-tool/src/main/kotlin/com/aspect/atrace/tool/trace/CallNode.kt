package com.aspect.atrace.tool.trace

/**
 * 调用节点 - 表示一次函数调用
 */
class CallNode(
    val tid: Int,
    val item: StackItem?,
    var beginTime: Long,
    var beginCPUTime: Long,
    val beginIndex: Int,
    val parent: CallNode?,
    val gapTime: Long,
    val gapCpuTime: Long,
    val type: Int
) {
    var endTime: Long = 0
    var endCPUTime: Long = 0
    var endIndex: Int = 0
    var messageId: Int = 0
    var blockTime: Long = 0
    var selfDuration: Long = 0
    var selfCpuDuration: Long = 0
    
    var begin: StackList? = null
    var end: StackList? = null
    
    val children = mutableListOf<CallNode>()
    
    init {
        parent?.children?.add(this)
    }
    
    fun end(endTime: Long, endCPUTime: Long, endIndex: Int): CallNode {
        this.endTime = endTime
        this.endCPUTime = endCPUTime
        this.endIndex = endIndex
        return this
    }
    
    fun setMessageId(messageId: Int): CallNode {
        this.messageId = messageId
        return this
    }
    
    fun setBegin(stack: StackList): CallNode {
        this.begin = stack
        return this
    }
    
    fun setEnd(stack: StackList): CallNode {
        this.end = stack
        return this
    }
    
    /**
     * 计算自身耗时
     */
    fun calculateSelfDurations() {
        val totalDuration = endTime - beginTime
        val totalCpuDuration = endCPUTime - beginCPUTime
        
        var childrenDuration = 0L
        var childrenCpuDuration = 0L
        
        for (child in children) {
            child.calculateSelfDurations()
            childrenDuration += (child.endTime - child.beginTime)
            childrenCpuDuration += (child.endCPUTime - child.beginCPUTime)
        }
        
        selfDuration = maxOf(0, totalDuration - childrenDuration)
        selfCpuDuration = maxOf(0, totalCpuDuration - childrenCpuDuration)
    }
    
    /**
     * 类型描述
     */
    fun typeAsString(): String {
        return when (type) {
            StackList.TYPE_CUSTOM -> "Custom"
            StackList.TYPE_BINDER -> "Binder"
            StackList.TYPE_GC -> "GC"
            StackList.TYPE_MONITOR_ENTER -> "MonitorEnter"
            StackList.TYPE_OBJECT_WAIT -> "ObjectWait"
            StackList.TYPE_UNSAFE_PARK -> "UnsafePark"
            StackList.TYPE_JNI -> "JNI"
            StackList.TYPE_LOAD_LIB -> "LoadLib"
            StackList.TYPE_ALLOC -> "Alloc"
            StackList.TYPE_IO_READ -> "IORead"
            StackList.TYPE_IO_WRITE -> "IOWrite"
            StackList.TYPE_NATIVE_POLL -> "NativePoll"
            StackList.TYPE_WAKEUP -> "Wakeup"
            StackList.TYPE_MESSAGE_BEGIN -> "MessageBegin"
            StackList.TYPE_MESSAGE_END -> "MessageEnd"
            StackList.TYPE_SECTION_BEGIN -> "SectionBegin"
            StackList.TYPE_SECTION_END -> "SectionEnd"
            else -> "Unknown($type)"
        }
    }
}
