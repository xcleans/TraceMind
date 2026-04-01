package com.aspect.atrace.tool.trace

import com.aspect.atrace.tool.core.Arguments
import com.aspect.atrace.tool.perfetto.TraceBuilder
import java.util.*

/**
 * 堆栈转换器 - 将采样数据转换为 Perfetto Trace
 */
object StackConvertor {
    
    private const val SINGLE_SAMPLING_DURATION = 10L // 单次采样持续时间(纳秒)
    
    /**
     * 转换采样数据为 Trace
     */
    fun convert(
        pid: Int,
        items: List<StackList>,
        threadNames: Map<Int, String>
    ): TraceBuilder {
        val sortedItems = items.sortedBy { it.nanoTime }
        val threadItemsMap = groupByThreadId(sortedItems)
        
        val trace = TraceBuilder()
        trace.setProcess(pid, Arguments.get().appName)
        
        // 设置线程
        for ((tid, _) in threadItemsMap) {
            val threadName = threadNames[tid] ?: "Thread-$tid"
            trace.setThread(pid, tid, threadName)
        }
        
        // 转换每个线程
        for ((tid, threadItems) in threadItemsMap) {
            convertSingleThread(trace, pid, tid, threadItems)
        }
        
        return trace
    }
    
    private fun convertSingleThread(
        trace: TraceBuilder,
        pid: Int,
        tid: Int,
        items: List<StackList>
    ) {
        val sectionItems = items.filter { it.isSection }
        val messageItems = items.filter { it.isMessage }
        val samplingItems = items.filter { !it.isSection && !it.isMessage }

        if (sectionItems.isNotEmpty()) {
            convertSections(trace, pid, tid, sectionItems)
        }

        if (messageItems.isNotEmpty()) {
            convertMessageSpans(trace, pid, tid, messageItems)
        }

        if (samplingItems.isNotEmpty()) {
            val root = decodeCallNode(samplingItems, pid == tid)
            for (child in root.children) {
                encodeTrace(trace, pid, tid, child)
            }
        }
    }

    /** kSectionBegin / kSectionEnd → 显式 slice 区间，名称来自 arg */
    private fun convertSections(
        trace: TraceBuilder,
        pid: Int,
        tid: Int,
        items: List<StackList>
    ) {
        val nameStack = ArrayDeque<String>()
        for (item in items) {
            if (item.isSectionBegin) {
                val name = item.arg ?: "Section"
                nameStack.push(name)
                trace.addSliceBegin(pid, tid, name, item.nanoTime, mapOf("Type" to "SectionBegin"))
            } else if (item.isSectionEnd) {
                val name = if (nameStack.isNotEmpty()) nameStack.pop() else "Section"
                trace.addSliceEnd(pid, tid, name, item.nanoTime)
            }
        }
        while (nameStack.isNotEmpty()) {
            val name = nameStack.pop()
            val lastTs = items.last().nanoTime + SINGLE_SAMPLING_DURATION
            trace.addSliceEnd(pid, tid, name, lastTs)
        }
    }

    /** kMessageBegin / kMessageEnd → 显式 slice 区间，便于在 Perfetto 中看到每条 Message 的起止 */
    private fun convertMessageSpans(
        trace: TraceBuilder,
        pid: Int,
        tid: Int,
        items: List<StackList>
    ) {
        val nameStack = ArrayDeque<String>()
        for (item in items) {
            if (item.isMessageBegin) {
                val name = "Message#${item.messageId}"
                nameStack.push(name)
                trace.addSliceBegin(
                    pid, tid, name, item.nanoTime,
                    mapOf("Type" to "MessageBegin", "MessageId" to item.messageId)
                )
            } else if (item.isMessageEnd) {
                val name = if (nameStack.isNotEmpty()) nameStack.pop() else "Message"
                trace.addSliceEnd(pid, tid, name, item.nanoTime)
            }
        }
        while (nameStack.isNotEmpty()) {
            val name = nameStack.pop()
            val lastTs = items.last().nanoTime + SINGLE_SAMPLING_DURATION
            trace.addSliceEnd(pid, tid, name, lastTs)
        }
    }
    
    /**
     * 解码调用树
     */
    fun decodeCallNode(items: List<StackList>, isMainThread: Boolean): CallNode {
        if (items.isEmpty()) {
            return CallNode(0, null, 0, 0, 0, null, 0, 0, -1)
        }
        
        val first = items[0]
        val root = CallNode(first.tid, null, first.nanoTime, 0, 0, null, 0, 0, -1)
        val stack = Stack<CallNode>()
        stack.push(root)
        
        var nanoTime = 0L
        var nanoCPUTime = 0L
        
        for (i in items.indices) {
            val curStackList = items[i]
            nanoTime = curStackList.nanoTime
            nanoCPUTime = curStackList.nanoCPUTime
            
            if (i == 0) {
                // 首次采样,直接构建堆栈
                for (item in curStackList.stackTrace) {
                    stack.push(
                        CallNode(
                            curStackList.tid, item, nanoTime, nanoCPUTime, i,
                            stack.peek(), nanoTime, nanoCPUTime, curStackList.type
                        ).setMessageId(curStackList.messageId).setBegin(curStackList)
                    )
                }
            } else {
                val preStackList = items[i - 1]
                var preIndex = 0
                var curIndex = 0
                
                // 找到第一个不同的位置
                while (preIndex < preStackList.size && curIndex < curStackList.size) {
                    if (preStackList.getName(preIndex) != curStackList.getName(curIndex)) {
                        break
                    }
                    preIndex++
                    curIndex++
                }
                
                // Pop 已结束的调用
                while (preIndex < preStackList.size) {
                    val endTime = minOf(nanoTime, preStackList.nanoTime + SINGLE_SAMPLING_DURATION)
                    val endCpuTime = minOf(nanoCPUTime, preStackList.nanoCPUTime + SINGLE_SAMPLING_DURATION)
                    stack.pop().end(endTime, endCpuTime, i).setEnd(curStackList)
                    preIndex++
                }
                
                // Push 新的调用
                while (curIndex < curStackList.size) {
                    val item = curStackList[curIndex]!!
                    stack.push(
                        CallNode(
                            curStackList.tid, item, nanoTime, nanoCPUTime, i,
                            stack.peek(), preStackList.nanoTime, preStackList.nanoCPUTime, curStackList.type
                        ).setMessageId(curStackList.messageId).setBegin(curStackList)
                    )
                    curIndex++
                }
            }
            
            // 累加阻塞时间
            for (callNode in stack) {
                callNode.blockTime += curStackList.blockDuration
            }
        }
        
        // 结束所有未关闭的调用
        while (stack.isNotEmpty()) {
            stack.pop().end(
                nanoTime + SINGLE_SAMPLING_DURATION,
                nanoCPUTime + SINGLE_SAMPLING_DURATION,
                items.size
            ).setEnd(items.last())
        }
        
        root.calculateSelfDurations()
        return root
    }
    
    private fun encodeTrace(trace: TraceBuilder, pid: Int, tid: Int, node: CallNode) {
        if (node.item == null) return
        
        val debugInfo = buildDebugInfo(node)
        trace.addSliceBegin(pid, tid, node.item.method.symbol(), node.beginTime, debugInfo)
        
        for (child in node.children) {
            encodeTrace(trace, pid, tid, child)
        }
        
        trace.addSliceEnd(pid, tid, node.item.method.symbol(), node.endTime)
    }
    
    /**
     * 构建调试信息
     */
    fun buildDebugInfo(node: CallNode): Map<String, Any> {
        val map = mutableMapOf<String, Any>()
        
        node.begin?.let { begin ->
            if (begin.wakeupTid != 0) {
                map["WakeUpBy"] = begin.wakeupTid
            }
        }
        
        map["BlockTime"] = node.blockTime / 1_000_000.0
        map["CPUTime"] = (node.endCPUTime - node.beginCPUTime) / 1_000_000.0
        map["Count"] = node.endIndex - node.beginIndex
        map["Gap"] = node.gapTime / 1_000_000.0
        map["Gap.CPU"] = node.gapCpuTime / 1_000_000.0
        map["SelfTime"] = node.selfDuration / 1_000_000.0
        map["SelfCpuTime"] = node.selfCpuDuration / 1_000_000.0
        map["Type"] = node.typeAsString()
        map["MessageId"] = node.messageId
        
        node.begin?.let { begin ->
            node.end?.let { end ->
                map["AllocatedObjects"] = end.allocatedObjects - begin.allocatedObjects
                map["AllocatedBytes"] = formatBytes(end.allocatedBytes - begin.allocatedBytes)
                map["AllocatedBytesNum"] = end.allocatedBytes - begin.allocatedBytes
                map["MajFlt"] = end.majFlt - begin.majFlt
                map["NvCsw"] = end.nvCsw - begin.nvCsw
                map["NivCsw"] = end.nivCsw - begin.nivCsw
            }
        }
        
        map["_Begin"] = node.beginTime / 1_000_000.0
        map["_End"] = node.endTime / 1_000_000.0
        
        node.item?.arg?.let { arg ->
            map["Arg"] = arg
        }
        
        return map
    }
    
    private fun formatBytes(bytes: Long): String {
        return when {
            bytes < 1024 -> "$bytes B"
            bytes < 1024 * 1024 -> "${bytes / 1024} KB"
            bytes < 1024 * 1024 * 1024 -> "${bytes / (1024 * 1024)} MB"
            else -> "${bytes / (1024 * 1024 * 1024)} GB"
        }
    }
    
    private fun groupByThreadId(items: List<StackList>): Map<Int, List<StackList>> {
        return items.groupBy { it.tid }
    }
}
