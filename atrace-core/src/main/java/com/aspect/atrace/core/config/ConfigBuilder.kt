/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.core.config

import android.util.Log
import com.aspect.atrace.TraceConfig
import com.aspect.atrace.plugin.TracePlugin

/**
 * 配置构建器
 *
 * 支持从多个来源构建配置:
 * 1. 代码中直接设置 (最高优先级)
 * 2. SystemProperties (运行时配置)
 * 3. 默认值
 */
object ConfigBuilder {

    private const val TAG = "ATrace:Config"

    /**
     * 从 SystemProperties 构建配置
     *
     * @param pluginResolver 插件解析器，根据 ID 返回插件实例
     */
    @JvmStatic
    fun fromSystemProperties(
        pluginResolver: ((String) -> TracePlugin?)? = null
    ): TraceConfig {
        return TraceConfig.Builder().apply {
            // 从系统属性读取配置
            bufferCapacity = TraceProperties.getBufferSize(bufferCapacity)
            sampleInterval = TraceProperties.getSampleInterval(mainThreadSampleInterval)
            maxStackDepth = TraceProperties.getMaxStackDepth(maxStackDepth)
            enableWakeupTrace = TraceProperties.isWakeupEnabled()
            enableAllocTrace = TraceProperties.isAllocEnabled()
            enableHttpServer = TraceProperties.isServerEnabled()
            debugMode = TraceProperties.isDebugEnabled()
            shadowPause = TraceProperties.isShadowPauseEnabled()

            // 解析插件
            if (pluginResolver != null) {
                val pluginIds = TraceProperties.getEnabledPlugins()
                for (id in pluginIds) {
                    val plugin = pluginResolver(id)
                    if (plugin != null) {
                        addPlugin(plugin)
                        Log.d(TAG, "Plugin enabled from props: $id")
                    } else {
                        Log.w(TAG, "Plugin not found: $id")
                    }
                }
            }
        }.build()
    }

    /**
     * 合并配置
     *
     * 代码配置优先，未设置的项从系统属性读取
     *
     * @param codeConfig 代码中设置的配置
     * @param useSystemPropsAsDefault 是否使用系统属性作为默认值
     */
    @JvmStatic
    fun merge(
        codeConfig: TraceConfig,
        useSystemPropsAsDefault: Boolean = true
    ): TraceConfig {
        if (!useSystemPropsAsDefault) {
            return codeConfig
        }

        // 如果代码配置使用了默认值，则从系统属性覆盖
        return TraceConfig(
            bufferCapacity = if (codeConfig.bufferCapacity == TraceConfig.DEFAULT_BUFFER_CAPACITY) {
                TraceProperties.getBufferSize(codeConfig.bufferCapacity)
            } else {
                codeConfig.bufferCapacity
            },
            mainThreadSampleInterval = if (codeConfig.mainThreadSampleInterval == TraceConfig.DEFAULT_MAIN_THREAD_INTERVAL) {
                TraceProperties.getSampleInterval(codeConfig.mainThreadSampleInterval)
            } else {
                codeConfig.mainThreadSampleInterval
            },
            otherThreadSampleInterval = if (codeConfig.otherThreadSampleInterval == TraceConfig.DEFAULT_OTHER_THREAD_INTERVAL) {
                TraceProperties.getSampleInterval(codeConfig.otherThreadSampleInterval) * 5
            } else {
                codeConfig.otherThreadSampleInterval
            },
            maxStackDepth = if (codeConfig.maxStackDepth == TraceConfig.DEFAULT_MAX_STACK_DEPTH) {
                TraceProperties.getMaxStackDepth(codeConfig.maxStackDepth)
            } else {
                codeConfig.maxStackDepth
            },
            plugins = codeConfig.plugins,
            enableThreadNames = codeConfig.enableThreadNames,
            enableWakeupTrace = codeConfig.enableWakeupTrace || TraceProperties.isWakeupEnabled(),
            enableAllocTrace = codeConfig.enableAllocTrace || TraceProperties.isAllocEnabled(),
            enableRusage = codeConfig.enableRusage,
            enableHttpServer = codeConfig.enableHttpServer && TraceProperties.isServerEnabled(),
            clockType = codeConfig.clockType,
            outputFormat = codeConfig.outputFormat,
            debugMode = codeConfig.debugMode || TraceProperties.isDebugEnabled(),
            shadowPause = codeConfig.shadowPause || TraceProperties.isShadowPauseEnabled(),
        )
    }

    /**
     * 创建调试用配置
     */
    @JvmStatic
    fun debug(vararg plugins: TracePlugin): TraceConfig {
        return TraceConfig.Builder().apply {
            debugMode = true
            bufferCapacity = 50_000
            sampleInterval = 500_000L  // 0.5ms
            enablePlugins(*plugins)
        }.build()
    }

    /**
     * 创建生产用配置
     */
    @JvmStatic
    fun production(vararg plugins: TracePlugin): TraceConfig {
        return TraceConfig.Builder().apply {
            debugMode = false
            bufferCapacity = 200_000
            sampleInterval = 1_000_000L  // 1ms
            enableHttpServer = false  // 生产环境禁用服务器
            enablePlugins(*plugins)
        }.build()
    }
}

