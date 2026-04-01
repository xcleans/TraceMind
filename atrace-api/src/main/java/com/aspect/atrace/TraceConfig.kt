/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace

import com.aspect.atrace.plugin.TracePlugin

/**
 * 追踪配置
 *
 * 通过Builder DSL构建，支持链式调用和Kotlin DSL语法
 */
data class TraceConfig(
    /** 采样缓冲区容量 (条目数) */
    val bufferCapacity: Int,

    /** 主线程采样间隔 (纳秒) */
    val mainThreadSampleInterval: Long,

    /** 其他线程采样间隔 (纳秒) */
    val otherThreadSampleInterval: Long,

    /** 最大堆栈深度 */
    val maxStackDepth: Int,

    /** 启用的插件列表 */
    val plugins: List<TracePlugin>,

    /** 是否启用线程名记录 */
    val enableThreadNames: Boolean,

    /** 是否启用唤醒追踪 */
    val enableWakeupTrace: Boolean,

    /** 是否启用内存分配追踪 */
    val enableAllocTrace: Boolean,

    /** 是否启用资源使用统计 */
    val enableRusage: Boolean,

    /** 是否启用 HTTP 服务器 (用于 PC 工具通信) */
    val enableHttpServer: Boolean,

    /** 时钟类型 */
    val clockType: ClockType,

    /** 输出格式 */
    val outputFormat: OutputFormat,

    /** 调试模式 */
    val debugMode: Boolean,
    /**
     * 启动是否开启Trace
     */
    val startOnLaunch: Boolean = true,

    /** Shadow Pause 模式：stop 时不卸载 Hook，只停止采集，便于快速重启 */
    val shadowPause: Boolean,
    val libLoader: ILibLoader? = null
) {



    enum class ClockType(val value: Int) {
        MONOTONIC(1),       // CLOCK_MONOTONIC
        BOOTTIME(7),        // CLOCK_BOOTTIME
        REALTIME(0),        // CLOCK_REALTIME
    }

    enum class OutputFormat {
        PERFETTO,           // Perfetto protobuf 格式
        CHROME_TRACE,       // Chrome trace JSON 格式
        RAW,                // 原始二进制格式
    }

    companion object {
        const val DEFAULT_BUFFER_CAPACITY = 100_000
        const val DEFAULT_MAIN_THREAD_INTERVAL = 1_000_000L      // 1ms
        const val DEFAULT_OTHER_THREAD_INTERVAL = 5_000_000L     // 5ms
        const val DEFAULT_MAX_STACK_DEPTH = 64

        fun default() = Builder().build()
    }

    class Builder {
        /** 缓冲区容量 */
        var bufferCapacity: Int = DEFAULT_BUFFER_CAPACITY

        /** 采样间隔 (会同时设置主线程和其他线程) */
        var sampleInterval: Long = DEFAULT_MAIN_THREAD_INTERVAL
            set(value) {
                field = value
                mainThreadSampleInterval = value
                otherThreadSampleInterval = value * 5
            }

        /** 主线程采样间隔 */
        var mainThreadSampleInterval: Long = DEFAULT_MAIN_THREAD_INTERVAL

        /** 其他线程采样间隔 */
        var otherThreadSampleInterval: Long = DEFAULT_OTHER_THREAD_INTERVAL

        /** 最大堆栈深度 */
        var maxStackDepth: Int = DEFAULT_MAX_STACK_DEPTH

        /** 启用线程名 */
        var enableThreadNames: Boolean = true

        /** 启用唤醒追踪 */
        var enableWakeupTrace: Boolean = false

        /** 启用内存分配追踪 */
        var enableAllocTrace: Boolean = false

        /** 启用资源使用统计 */
        var enableRusage: Boolean = true

        /** 启用 HTTP 服务器 */
        var enableHttpServer: Boolean = true

        /** 时钟类型 */
        var clockType: ClockType = ClockType.BOOTTIME

        /** 输出格式 */
        var outputFormat: OutputFormat = OutputFormat.PERFETTO

        /** 调试模式 */
        var debugMode: Boolean = false

        /** Shadow Pause 模式 */
        var shadowPause: Boolean = false

        /**
         * 启动是否开启Trace
         */
        var startOnLaunch: Boolean = false

        private val plugins = mutableListOf<TracePlugin>()

        /**
         * 启用插件
         */
        fun enablePlugins(vararg plugins: TracePlugin) {
            this.plugins.addAll(plugins)
        }

        /**
         * 添加单个插件
         */
        fun addPlugin(plugin: TracePlugin) {
            plugins.add(plugin)
        }

        fun build(): TraceConfig = TraceConfig(
            bufferCapacity = bufferCapacity,
            mainThreadSampleInterval = mainThreadSampleInterval,
            otherThreadSampleInterval = otherThreadSampleInterval,
            maxStackDepth = maxStackDepth,
            plugins = plugins.toList(),
            enableThreadNames = enableThreadNames,
            enableWakeupTrace = enableWakeupTrace,
            enableAllocTrace = enableAllocTrace,
            enableRusage = enableRusage,
            enableHttpServer = enableHttpServer,
            clockType = clockType,
            outputFormat = outputFormat,
            debugMode = debugMode,
            startOnLaunch = startOnLaunch,
            shadowPause = shadowPause,
        )
    }
}

