/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.core.server

import android.content.Context
import android.util.Log
import java.io.File

/**
 * HTTP Server 管理器
 *
 * 负责服务器的生命周期管理
 */
object ServerManager {

    private const val TAG = "ATrace:ServerMgr"

    private var traceDir: File? = null
    private var serverEnabled = false

    /**
     * 初始化并启动服务器
     *
     * @param context 应用上下文
     * @param outputDir 追踪输出目录
     * @param autoStart 是否自动启动
     */
    @JvmStatic
    fun init(context: Context, outputDir: File? = null, autoStart: Boolean = true) {
        Log.d(TAG, "init: outputDir=$outputDir autoStart=$autoStart")
        traceDir = outputDir ?: File(context.filesDir, "atrace")
        val created = !traceDir!!.exists() && traceDir!!.mkdirs()
        Log.d(TAG, "traceDir=${traceDir!!.absolutePath} created=$created")

        if (autoStart) {
            start(context)
        }
    }

    /**
     * 启动服务器
     */
    @JvmStatic
    fun start(context: Context): Boolean {
        Log.d(TAG, "start: traceDir=$traceDir")
        if (traceDir == null) {
            traceDir = File(context.filesDir, "atrace")
            val created = !traceDir!!.exists() && traceDir!!.mkdirs()
            Log.d(TAG, "traceDir initialized to ${traceDir!!.absolutePath} created=$created")
        }

        val server = TraceServer.start(context, traceDir!!)
        serverEnabled = server != null

        if (serverEnabled) {
            Log.i(TAG, "Server started on port ${server?.listeningPort}")
        } else {
            Log.e(TAG, "Server failed to start")
        }

        return serverEnabled
    }

    /**
     * 停止服务器
     */
    @JvmStatic
    fun stop() {
        val port = getPort()
        Log.d(TAG, "stop: current port=$port")
        TraceServer.shutdown()
        serverEnabled = false
        Log.i(TAG, "Server stopped (was on port=$port)")
    }

    /**
     * 是否运行中
     */
    @JvmStatic
    fun isRunning(): Boolean {
        val alive = TraceServer.getInstance()?.isAlive == true
        Log.d(TAG, "isRunning=$alive")
        return alive
    }

    /**
     * 获取服务器端口
     */
    @JvmStatic
    fun getPort(): Int {
        val port = TraceServer.getInstance()?.listeningPort ?: -1
        Log.d(TAG, "getPort=$port")
        return port
    }

    /**
     * 获取追踪目录
     */
    @JvmStatic
    fun getTraceDir(): File? {
        Log.d(TAG, "getTraceDir=${traceDir?.absolutePath}")
        return traceDir
    }

    /**
     * 通知追踪导出完成
     */
    @JvmStatic
    fun notifyDumpFinished(code: Int, file: File?) {
        Log.d(TAG, "notifyDumpFinished: code=$code file=${file?.absolutePath}")
        TraceServer.getInstance()?.onTraceDumpFinished(code, file)
    }
}

