package com.aspect.atrace.tool.trace

import com.aspect.atrace.tool.core.Log
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * 符号映射解码器
 */
class MappingDecoder(private val mappingBytes: ByteArray) {
    
    /** 方法ID -> 方法符号映射 */
    val symbolMapping = mutableMapOf<Long, MethodSymbol>()
    
    /** 线程ID -> 线程名映射 */
    val threadNames = mutableMapOf<Int, String>()
    
    /**
     * 解码 mapping 文件
     *
     * 格式 (与 TraceEngine::ExportMapping 一致):
     *   magic(u64) + version(u32) + count(u32)
     *   + [method_ptr(u64) + nameLen(u16) + name(nameLen bytes)] * count
     *   + [tid(u16) + nameLen(u8) + name(nameLen bytes)] * N (线程名, 无数量前缀)
     */
    fun decode(): MappingDecoder {
        val buffer = ByteBuffer.wrap(mappingBytes).order(ByteOrder.LITTLE_ENDIAN)
        
        // magic(8) + version(4) + count(4) = 16 bytes
        if (buffer.remaining() < 16) {
            Log.w("Mapping file too small: ${mappingBytes.size} bytes")
            return this
        }
        
        val magic = buffer.long              // uint64_t magic
        val version = buffer.int             // uint32_t version
        
        Log.d("Mapping magic: 0x${java.lang.Long.toHexString(magic)}, version: $version")
        
        val methodCount = buffer.int         // uint32_t count
        Log.d("Method count: $methodCount")
        
        for (i in 0 until methodCount) {
            if (buffer.remaining() < 10) break   // method_ptr(8) + nameLen(2)
            
            val methodId = buffer.long                             // uint64_t method_ptr
            val nameLen = buffer.short.toInt() and 0xFFFF          // uint16_t len
            
            if (nameLen <= 0 || nameLen > 10000 || buffer.remaining() < nameLen) break
            
            val nameBytes = ByteArray(nameLen)
            buffer.get(nameBytes)
            val fullName = String(nameBytes, Charsets.UTF_8)
            
            symbolMapping[methodId] = MethodSymbol.parse(fullName)
        }
        
        // 读取线程名 (格式: tid(2字节) + len(1字节) + name)
        // 线程名紧跟在方法映射之后，没有数量前缀
        while (buffer.remaining() >= 3) {
            val tid = buffer.short.toInt() and 0xFFFF  // uint16_t
            val nameLen = buffer.get().toInt() and 0xFF  // uint8_t
            
            if (nameLen <= 0 || nameLen > 16 || buffer.remaining() < nameLen) break
            
            val nameBytes = ByteArray(nameLen)
            buffer.get(nameBytes)
            var name = String(nameBytes, Charsets.UTF_8)
            
            // 移除可能的换行符
            if (name.endsWith("\n")) {
                name = name.dropLast(1)
            }
            
            threadNames[tid] = name
        }
        
        Log.d("Decoded ${symbolMapping.size} methods, ${threadNames.size} threads")
        return this
    }
    
    /**
     * 应用 Proguard 反混淆
     */
    fun retrace(proguardDecoder: ProguardMappingDecoder) {
        for ((id, symbol) in symbolMapping) {
            val deobfuscated = proguardDecoder.deobfuscate(symbol)
            if (deobfuscated != symbol) {
                symbolMapping[id] = deobfuscated
            }
        }
    }
    
    companion object {
        fun decode(file: File): MappingDecoder {
            return MappingDecoder(file.readBytes()).decode()
        }
    }
}

/**
 * Proguard 映射解码器
 */
class ProguardMappingDecoder {
    
    private val classMapping = mutableMapOf<String, String>()
    private val methodMapping = mutableMapOf<String, MutableMap<String, String>>()
    
    fun decode(file: File): ProguardMappingDecoder {
        if (!file.exists()) return this
        
        var currentClass: String? = null
        var currentOriginalClass: String? = null
        
        file.forEachLine { line ->
            if (line.isBlank() || line.startsWith("#")) return@forEachLine
            
            if (!line.startsWith(" ") && line.contains(" -> ")) {
                // 类映射
                val parts = line.split(" -> ")
                if (parts.size == 2) {
                    val original = parts[0].trim()
                    val obfuscated = parts[1].trimEnd(':').trim()
                    classMapping[obfuscated] = original
                    currentClass = obfuscated
                    currentOriginalClass = original
                }
            } else if (line.startsWith("    ") && currentClass != null) {
                // 方法映射
                val trimmed = line.trim()
                if (trimmed.contains(" -> ")) {
                    val parts = trimmed.split(" -> ")
                    if (parts.size == 2) {
                        val methodPart = parts[0]
                        val obfuscatedMethod = parts[1].trim()
                        
                        // 解析原始方法名
                        val colonIndex = methodPart.indexOf(':')
                        val methodDef = if (colonIndex >= 0) {
                            methodPart.substringAfter(':').substringAfter(':').trim()
                        } else {
                            methodPart.trim()
                        }
                        
                        val parenIndex = methodDef.indexOf('(')
                        if (parenIndex > 0) {
                            val returnAndName = methodDef.substring(0, parenIndex)
                            val spaceIndex = returnAndName.lastIndexOf(' ')
                            if (spaceIndex > 0) {
                                val originalMethod = returnAndName.substring(spaceIndex + 1)
                                methodMapping.getOrPut(currentClass!!) { mutableMapOf() }[obfuscatedMethod] = originalMethod
                            }
                        }
                    }
                }
            }
        }
        
        Log.d("Loaded ${classMapping.size} class mappings, ${methodMapping.size} method mappings")
        return this
    }
    
    fun decode(): ProguardMappingDecoder {
        val args = com.aspect.atrace.tool.core.Arguments.get()
        if (args.mappingPath != null) {
            decode(File(args.mappingPath))
        }
        return this
    }
    
    fun deobfuscate(symbol: MethodSymbol): MethodSymbol {
        val originalClass = classMapping[symbol.className] ?: symbol.className
        val classMethods = methodMapping[symbol.className]
        val originalMethod = classMethods?.get(symbol.methodName) ?: symbol.methodName
        
        return MethodSymbol(originalClass, originalMethod, symbol.signature)
    }
}
