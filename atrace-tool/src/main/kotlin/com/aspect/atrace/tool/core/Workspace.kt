package com.aspect.atrace.tool.core

import java.io.File
import java.text.SimpleDateFormat
import java.util.*

/**
 * 工作空间管理
 */
object Workspace {
    
    private lateinit var root: File
    
    fun init(workspaceDir: File) {
        root = workspaceDir
        if (!root.exists()) {
            root.mkdirs()
        }
    }
    
    private lateinit var outputFile: File
    
    fun initDefault(appName: String, outputPath: String?): String {
        outputFile = if (outputPath != null) {
            File(outputPath).absoluteFile
        } else {
            File(getDefaultOutputPath(appName)).absoluteFile
        }
        
        val workspaceDir = File(outputFile.parentFile ?: File("."), "atrace.workspace")
        init(workspaceDir)
        
        return outputFile.absolutePath
    }
    
    private fun getDefaultOutputPath(appName: String): String {
        val dateTime = SimpleDateFormat("yyyy_MM_dd_HH_mm_ss").format(Date())
        return "${appName}_$dateTime.pb"
    }
    
    fun samplingTrace(): File = File(root, "sampling.trace")
    
    fun samplingMapping(): File = File(root, "sampling.mapping")
    
    fun systemTrace(): File = File(root, "system.trace")
    
    fun output(): File = outputFile
    
    fun perfettoBinary(): File = File(root, "record_android_trace")
    
    fun cleanup() {
        if (root.exists()) {
            root.deleteRecursively()
        }
    }
}

