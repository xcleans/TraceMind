package com.aspect.atrace.tool.trace

import java.nio.ByteBuffer

/**
 * 堆栈列表 - 一次采样的完整堆栈
 */
class StackList(
    val tid: Int,
    val nanoTime: Long,
    val nanoCPUTime: Long,
    val type: Int,
    val messageId: Int,
    val blockDuration: Long,
    val allocatedObjects: Int,
    val allocatedBytes: Long,
    val majFlt: Int,
    val nvCsw: Int,
    val nivCsw: Int,
    val wakeupTid: Int,
    val isDurationStack: Boolean,
    val arg: String? = null
) {
    val stackTrace = mutableListOf<StackItem>()
    
    val size: Int get() = stackTrace.size
    
    fun getName(index: Int): String {
        return stackTrace.getOrNull(index)?.method?.symbol() ?: ""
    }
    
    operator fun get(index: Int): StackItem? = stackTrace.getOrNull(index)
    
    val isSectionBegin: Boolean get() = type == TYPE_SECTION_BEGIN
    val isSectionEnd: Boolean get() = type == TYPE_SECTION_END
    val isSection: Boolean get() = isSectionBegin || isSectionEnd

    val isMessageBegin: Boolean get() = type == TYPE_MESSAGE_BEGIN
    val isMessageEnd: Boolean get() = type == TYPE_MESSAGE_END
    val isMessage: Boolean get() = isMessageBegin || isMessageEnd
    
    companion object {
        // 采样类型常量 (与 native SampleType 枚举值一致)
        const val TYPE_CUSTOM = 1
        const val TYPE_BINDER = 2
        const val TYPE_GC = 3
        const val TYPE_MONITOR_ENTER = 4
        const val TYPE_OBJECT_WAIT = 5
        const val TYPE_UNSAFE_PARK = 6
        const val TYPE_JNI = 7
        const val TYPE_LOAD_LIB = 8
        const val TYPE_ALLOC = 9
        const val TYPE_IO_READ = 10
        const val TYPE_IO_WRITE = 11
        const val TYPE_NATIVE_POLL = 12
        const val TYPE_WAKEUP = 20
        const val TYPE_MESSAGE_BEGIN = 30
        const val TYPE_MESSAGE_END = 31
        /** Section name is in [arg]; native Mark(name, kSectionBegin) sets SetArg(name). */
        const val TYPE_SECTION_BEGIN = 40
        /** SECTION_END has no arg; pair with SECTION_BEGIN by name stack in convertSections. */
        const val TYPE_SECTION_END = 41
        
        /**
         * 解码采样数据
         */
        fun decode(
            version: Int,
            mapping: Map<Long, MethodSymbol>,
            buffer: ByteBuffer,
            items: MutableList<StackList>,
            traceBeginTime: Long,
            pid: Int
        ) {
            while (buffer.remaining() >= 8) {
                try {
                    val item = decodeSingle(version, mapping, buffer, traceBeginTime, pid)
                    if (item != null) {
                        items.add(item)
                    }
                } catch (e: Exception) {
                    break
                }
            }
        }
        
        /**
         * 解码单条记录
         *
         * 二进制格式 (与 SampleRecord::EncodeTo 一致):
         *   type(u16) + tid(u16) + messageId(u32)
         *   + nanoTime(u64) + endNanoTime(u64) + cpuTime(u64) + endCpuTime(u64)
         *   + allocObj(u64) + allocBytes(u64)
         *   + majFlt(u32) + volCsw(u32) + involCsw(u32)
         *   + wakeupTid(u16) + argLen(u16) + [arg bytes]
         *   + savedDepth(u8) + actualDepth(u8)
         *   + [frames: method_ptr(u64) ...]
         */
        private fun decodeSingle(
            version: Int,
            mapping: Map<Long, MethodSymbol>,
            buffer: ByteBuffer,
            traceBeginTime: Long,
            pid: Int
        ): StackList? {
            if (buffer.remaining() < 2) return null
            
            val type = buffer.short.toInt() and 0xFFFF          // uint16_t type
            val tid = buffer.short.toInt() and 0xFFFF            // uint16_t tid
            val messageId = buffer.int                           // uint32_t message_id
            val nanoTime = buffer.long + traceBeginTime          // uint64_t nano_time
            val endNanoTime = buffer.long                        // uint64_t end_nano_time
            val cpuTime = buffer.long                            // uint64_t cpu_time
            val endCpuTime = buffer.long                         // uint64_t end_cpu_time
            val allocatedObjects = buffer.long.toInt()           // uint64_t allocated_objects
            val allocatedBytes = buffer.long                     // uint64_t allocated_bytes
            val majFlt = buffer.int                              // uint32_t major_faults
            val nvCsw = buffer.int                               // uint32_t voluntary_csw
            val nivCsw = buffer.int                              // uint32_t involuntary_csw
            val wakeupTid = buffer.short.toInt() and 0xFFFF      // uint16_t wakeup_tid
            val argLen = buffer.short.toInt() and 0xFFFF         // uint16_t arg_length

            val arg = if (argLen > 0 && argLen <= 64 && buffer.remaining() >= argLen) {
                val argBytes = ByteArray(argLen)
                buffer.get(argBytes)
                String(argBytes, Charsets.UTF_8)
            } else {
                if (argLen > 64) return null
                // Skip arg bytes to keep stream in sync (e.g. argLen > 0 but remaining < argLen)
                if (argLen > 0 && buffer.remaining() >= argLen) {
                    buffer.position(buffer.position() + argLen)
                }
                null
            }

            if (buffer.remaining() < 2) return null
            val savedDepth = buffer.get().toInt() and 0xFF       // uint8_t saved_depth
            buffer.get()                                          // uint8_t actual_depth (skip)
            
            if (savedDepth < 0 || savedDepth > kMaxStackDepth) {
                return null
            }
            
            val isDurationStack = endNanoTime > 0
            val blockDuration = if (isDurationStack) endNanoTime - nanoTime + traceBeginTime else 0L
            
            val stackList = StackList(
                tid = tid,
                nanoTime = nanoTime,
                nanoCPUTime = cpuTime,
                type = type,
                messageId = messageId,
                blockDuration = blockDuration,
                allocatedObjects = allocatedObjects,
                allocatedBytes = allocatedBytes,
                majFlt = majFlt,
                nvCsw = nvCsw,
                nivCsw = nivCsw,
                wakeupTid = wakeupTid,
                isDurationStack = isDurationStack,
                arg = arg
            )
            
            // 读取堆栈帧: 每帧只有 method_ptr(u64)
            if (buffer.remaining() < savedDepth * 8) return null
            for (i in 0 until savedDepth) {
                val methodPtr = buffer.long                      // uint64_t method_ptr
                val method = mapping[methodPtr]
                if (method != null) {
                    stackList.stackTrace.add(StackItem(method, if (i == 0) arg else null))
                }
            }
            
            return stackList
        }
        
        private const val kMaxStackDepth = 64
    }
}
