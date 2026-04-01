package com.aspect.atrace.tool.capture

import java.io.File

/**
 * 系统级 Trace 捕获接口
 */
interface SystemCapture {
    
    /**
     * 启动捕获
     */
    fun start(args: Array<String>)
    
    /**
     * 停止捕获
     */
    fun stop()
    
    /**
     * 等待捕获完成
     */
    fun waitForExit()
    
    /**
     * 处理 Trace 数据
     */
    fun process()
    
    /**
     * 清理资源
     */
    fun cleanup()
    
    /**
     * 打印输出
     */
    fun print(withError: Boolean, listener: (String) -> Unit)
}
