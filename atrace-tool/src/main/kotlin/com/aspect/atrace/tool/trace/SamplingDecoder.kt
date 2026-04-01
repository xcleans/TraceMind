package com.aspect.atrace.tool.trace

import com.aspect.atrace.tool.core.Arguments
import com.aspect.atrace.tool.core.Log
import com.aspect.atrace.tool.core.TraceError
import com.aspect.atrace.tool.core.Workspace
import com.aspect.atrace.tool.perfetto.TraceBuilder
import org.json.JSONObject
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * 采样数据解码器
 */
object SamplingDecoder {
    
    private var pid = 0
    
    fun getPid(): Int = pid
    
    /**
     * 解码采样数据
     */
    fun decode(): TraceBuilder? {
        // 解码符号映射
        val mappingDecoder = MappingDecoder.decode(Workspace.samplingMapping())
        
        // 应用 Proguard 反混淆
        Arguments.get().mappingPath?.let {
            val proguardDecoder = ProguardMappingDecoder().decode()
            mappingDecoder.retrace(proguardDecoder)
        }
        
        // 解码采样数据
        val samplingTrace = mutableListOf<StackList>()
        val extra = decodeSampling(
            Workspace.samplingTrace(),
            mappingDecoder.symbolMapping,
            samplingTrace
        )
        
        if (samplingTrace.isEmpty()) {
            Log.red("Sampling record empty")
            return null
        }
        
        if (!extra.has("processId")) {
            Log.red("Missing pid value from extra")
            return null
        }
        
        pid = extra.getInt("processId")
        
        // 转换为 Perfetto Trace
        return StackConvertor.convert(pid, samplingTrace, mappingDecoder.threadNames)
    }
    
    private fun decodeSampling(
        samplingFile: File,
        mapping: Map<Long, MethodSymbol>,
        items: MutableList<StackList>
    ): JSONObject {
        val samplingBytes = samplingFile.readBytes()
        val buffer = ByteBuffer.wrap(samplingBytes).order(ByteOrder.LITTLE_ENDIAN)
        
        Log.d("Sampling file: ${samplingFile.name}, size: ${samplingBytes.size} bytes")
        
        if (samplingBytes.isEmpty()) {
            throw TraceError(
                "sample trace file is empty: ${samplingFile.name}",
                "app may not have collected any sampling data, check if TraceEngine is started"
            )
        }
        
        // 文件头: magic(4) + version(4) + timestamp(8) + count(4) + extraLen(4) = 24 bytes
        if (buffer.remaining() < 24) {
            Log.red("Sampling file too small (${samplingBytes.size} bytes), expected >= 24")
            throw TraceError(
                "sample trace file is corrupted: ${samplingFile.name} (${samplingBytes.size} bytes)",
                "the download may have failed or the app didn't produce trace data"
            )
        }
        
        // 读取头部 (与 TraceEngine::ExportToFile 写入格式一致)
        val magic = buffer.int           // uint32_t magic = 0x41545243 ("ATRC")
        val version = buffer.int         // uint32_t version
        val timestamp = buffer.long      // uint64_t timestamp
        val count = buffer.int           // uint32_t count
        val extraLength = buffer.int     // int32_t extra_len
        
        Log.d("Sampling magic: 0x${Integer.toHexString(magic)}, version: $version, count: $count, extraLength: $extraLength, timestamp: $timestamp")
        
        if (magic != 0x41545243) {
            throw TraceError(
                "invalid sampling file magic: 0x${Integer.toHexString(magic)}, expected 0x41545243 (ATRC)",
                "the downloaded file may not be a valid sampling trace"
            )
        }
        
        if (extraLength < 0 || extraLength > buffer.remaining()) {
            throw TraceError(
                "sample trace header invalid: extraLength=$extraLength but remaining=${buffer.remaining()}",
                "the sampling data may be corrupted or the binary format version is mismatched"
            )
        }
        
        // 读取扩展数据
        val extra = if (extraLength > 0) {
            val extraBytes = ByteArray(extraLength)
            buffer.get(extraBytes)
            JSONObject(String(extraBytes, Charsets.UTF_8))
        } else {
            JSONObject()
        }
        
        val pid = extra.optInt("processId", 0)
        val traceBeginTime = extra.optLong("startTime", 0) * 1_000_000
        
        // 解码采样记录
        StackList.decode(version, mapping, buffer, items, traceBeginTime, pid)
        
        Log.d("Decoded ${items.size} sampling records")
        return extra
    }
}
