package com.aspect.atrace.tool.capture

import com.aspect.atrace.tool.core.Log
import com.aspect.atrace.tool.core.TraceError
import com.aspect.atrace.tool.core.Workspace
import com.aspect.atrace.tool.trace.SamplingDecoder

/**
 * 简单模式 Trace 捕获 (Android 8 及以下)
 * 不依赖 Perfetto，只采集应用层数据
 */
class LiteCapture : SystemCapture {
    
    private var started = false
    
    override fun start(args: Array<String>) {
        Log.blue("Using lite capture mode (no system trace)")
        started = true
    }
    
    override fun stop() {
        started = false
    }
    
    override fun waitForExit() {
        // Lite 模式无需等待
    }
    
    override fun process() {
        // 解码应用采样数据
        val sampleTrace = SamplingDecoder.decode()
            ?: throw TraceError("decode app sample trace failed", null)
        
        // 只输出应用 Trace
        val output = Workspace.output()
        Log.red("Writing trace: ${output.absolutePath}")
        
        output.outputStream().use { out ->
            sampleTrace.marshal(out)
        }
    }
    
    override fun cleanup() {
        stop()
    }
    
    override fun print(withError: Boolean, listener: (String) -> Unit) {
        // Lite 模式无输出
    }
}
