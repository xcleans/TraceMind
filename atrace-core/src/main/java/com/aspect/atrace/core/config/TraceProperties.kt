/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.core.config

import android.annotation.SuppressLint
import android.util.Log
import com.aspect.atrace.ALog
import java.lang.reflect.Method

/**
 * 系统属性配置读取器
 *
 * 通过 Android SystemProperties 读取追踪配置，支持运行时动态配置。
 *
 * 配置项 (通过 adb shell setprop 设置):
 * - debug.atrace.startOnLaunch    应用启动时自动开始追踪 (1=启用)
 * - debug.atrace.bufferSize       采样缓冲区大小
 * - debug.atrace.sampleInterval   采样间隔 (纳秒)
 * - debug.atrace.maxStackDepth    最大堆栈深度
 * - debug.atrace.enablePlugins    启用的插件列表 (逗号分隔)
 * - debug.atrace.serverPort       HTTP 服务器端口 (0=随机)
 * - debug.atrace.waitTimeout      等待追踪超时 (秒)
 * - debug.atrace.debug            调试模式 (1=启用)
 *
 * 示例:
 * ```
 * adb shell setprop debug.atrace.startOnLaunch 1
 * adb shell setprop debug.atrace.bufferSize 200000
 * adb shell setprop debug.atrace.sampleInterval 500000
 * ```
 */
object TraceProperties {

    private const val TAG = "ATrace:Props"

    // 属性键定义
    private const val KEY_PREFIX = "debug.atrace."
    private const val KEY_START_ON_LAUNCH = "${KEY_PREFIX}startOnLaunch"
    private const val KEY_BUFFER_SIZE = "${KEY_PREFIX}bufferSize"
    private const val KEY_SAMPLE_INTERVAL = "${KEY_PREFIX}sampleInterval"
    private const val KEY_MAX_STACK_DEPTH = "${KEY_PREFIX}maxStackDepth"
    private const val KEY_ENABLE_PLUGINS = "${KEY_PREFIX}enablePlugins"
    private const val KEY_SERVER_PORT = "${KEY_PREFIX}serverPort"
    private const val KEY_WAIT_TIMEOUT = "${KEY_PREFIX}waitTimeout"
    private const val KEY_DEBUG = "${KEY_PREFIX}debug"
    private const val KEY_ENABLE_SERVER = "${KEY_PREFIX}enableServer"
    private const val KEY_ENABLE_WAKEUP = "${KEY_PREFIX}enableWakeup"
    private const val KEY_ENABLE_ALLOC = "${KEY_PREFIX}enableAlloc"
    private const val KEY_SHADOW_PAUSE = "${KEY_PREFIX}shadowPause"

    // 默认值
    private const val DEFAULT_BUFFER_SIZE = 100_000
    private const val DEFAULT_SAMPLE_INTERVAL = 1_000_000L  // 1ms
    private const val DEFAULT_MAX_STACK_DEPTH = 64
    private const val DEFAULT_WAIT_TIMEOUT = 30

    /**
     * 是否在应用启动时自动开始追踪
     */
    @JvmStatic
    fun shouldStartOnLaunch(): Boolean {
        return getBoolean(KEY_START_ON_LAUNCH, false)
    }

    /**
     * 获取缓冲区大小
     */
    @JvmStatic
    fun getBufferSize(default: Int = DEFAULT_BUFFER_SIZE): Int {
        return getInt(KEY_BUFFER_SIZE, default)
    }

    /**
     * 获取采样间隔 (纳秒)
     */
    @JvmStatic
    fun getSampleInterval(default: Long = DEFAULT_SAMPLE_INTERVAL): Long {
        return getLong(KEY_SAMPLE_INTERVAL, default)
    }

    /**
     * 获取最大堆栈深度
     */
    @JvmStatic
    fun getMaxStackDepth(default: Int = DEFAULT_MAX_STACK_DEPTH): Int {
        return getInt(KEY_MAX_STACK_DEPTH, default)
    }

    /**
     * 获取启用的插件列表
     *
     * @return 插件 ID 列表，如 ["binder", "gc", "lock"]
     */
    @JvmStatic
    fun getEnabledPlugins(): List<String> {
        val value = getString(KEY_ENABLE_PLUGINS, "")
        return if (value.isEmpty()) {
            emptyList()
        } else {
            value.split(",").map { it.trim() }.filter { it.isNotEmpty() }
        }
    }

    /**
     * 获取 HTTP 服务器端口
     *
     * @return 端口号，0 表示随机端口
     */
    @JvmStatic
    fun getServerPort(): Int {
        return getInt(KEY_SERVER_PORT, 0)
    }

    /**
     * 获取等待追踪超时时间 (秒)
     */
    @JvmStatic
    fun getWaitTimeout(default: Int = DEFAULT_WAIT_TIMEOUT): Int {
        return getInt(KEY_WAIT_TIMEOUT, default)
    }

    /**
     * 是否启用调试模式
     */
    @JvmStatic
    fun isDebugEnabled(): Boolean {
        return getBoolean(KEY_DEBUG, false)
    }

    /**
     * 是否启用 HTTP 服务器
     */
    @JvmStatic
    fun isServerEnabled(): Boolean {
        return getBoolean(KEY_ENABLE_SERVER, true)
    }

    /**
     * 是否启用唤醒追踪
     */
    @JvmStatic
    fun isWakeupEnabled(): Boolean {
        return getBoolean(KEY_ENABLE_WAKEUP, false)
    }

    /**
     * 是否启用内存分配追踪
     */
    @JvmStatic
    fun isAllocEnabled(): Boolean {
        return getBoolean(KEY_ENABLE_ALLOC, false)
    }

    /**
     * 是否启用 Shadow Pause 模式
     */
    @JvmStatic
    fun isShadowPauseEnabled(): Boolean {
        return getBoolean(KEY_SHADOW_PAUSE, false)
    }

    /**
     * 获取所有配置项
     */
    @JvmStatic
    fun getAllProperties(): Map<String, String> {
        return mapOf(
            KEY_START_ON_LAUNCH to getString(KEY_START_ON_LAUNCH, ""),
            KEY_BUFFER_SIZE to getString(KEY_BUFFER_SIZE, ""),
            KEY_SAMPLE_INTERVAL to getString(KEY_SAMPLE_INTERVAL, ""),
            KEY_MAX_STACK_DEPTH to getString(KEY_MAX_STACK_DEPTH, ""),
            KEY_ENABLE_PLUGINS to getString(KEY_ENABLE_PLUGINS, ""),
            KEY_SERVER_PORT to getString(KEY_SERVER_PORT, ""),
            KEY_WAIT_TIMEOUT to getString(KEY_WAIT_TIMEOUT, ""),
            KEY_DEBUG to getString(KEY_DEBUG, ""),
            KEY_ENABLE_SERVER to getString(KEY_ENABLE_SERVER, ""),
            KEY_ENABLE_WAKEUP to getString(KEY_ENABLE_WAKEUP, ""),
            KEY_ENABLE_ALLOC to getString(KEY_ENABLE_ALLOC, ""),
            KEY_SHADOW_PAUSE to getString(KEY_SHADOW_PAUSE, ""),
        ).filter { it.value.isNotEmpty() }
    }

    /**
     * 打印当前配置
     */
    @JvmStatic
    fun dump() {
        ALog.i(TAG, "=== ATrace Properties ===")
        ALog.i(TAG, "startOnLaunch: ${shouldStartOnLaunch()}")
        ALog.i(TAG, "bufferSize: ${getBufferSize()}")
        ALog.i(TAG, "sampleInterval: ${getSampleInterval()}")
        ALog.i(TAG, "maxStackDepth: ${getMaxStackDepth()}")
        ALog.i(TAG, "enablePlugins: ${getEnabledPlugins()}")
        ALog.i(TAG, "serverPort: ${getServerPort()}")
        ALog.i(TAG, "waitTimeout: ${getWaitTimeout()}")
        ALog.i(TAG, "debug: ${isDebugEnabled()}")
        ALog.i(TAG, "enableServer: ${isServerEnabled()}")
        ALog.i(TAG, "enableWakeup: ${isWakeupEnabled()}")
        ALog.i(TAG, "enableAlloc: ${isAllocEnabled()}")
        ALog.i(TAG, "shadowPause: ${isShadowPauseEnabled()}")
        ALog.i(TAG, "=== ATrace Properties === END")
    }

    // ===== 基础类型获取方法 =====

    private fun getString(key: String, default: String): String {
        return SystemPropertiesFetcher.get(key) ?: default
    }

    private fun getInt(key: String, default: Int): Int {
        val value = SystemPropertiesFetcher.get(key) ?: return default
        return try {
            val intValue = value.toInt()
            if (intValue > 0) intValue else default
        } catch (e: NumberFormatException) {
            default
        }
    }

    private fun getLong(key: String, default: Long): Long {
        val value = SystemPropertiesFetcher.get(key) ?: return default
        return try {
            val longValue = value.toLong()
            if (longValue > 0) longValue else default
        } catch (e: NumberFormatException) {
            default
        }
    }

    private fun getBoolean(key: String, default: Boolean): Boolean {
        val value = SystemPropertiesFetcher.get(key) ?: return default
        return value == "1" || value.equals("true", ignoreCase = true)
    }
}

/**
 * SystemProperties 访问器
 *
 * 通过反射访问 android.os.SystemProperties
 */
private object SystemPropertiesFetcher {

    private var getMethod: Method? = null
    private var setMethod: Method? = null
    private var initialized = false

    @SuppressLint("PrivateApi")
    private fun init() {
        if (initialized) return
        initialized = true

        try {
            val clazz = Class.forName("android.os.SystemProperties")
            getMethod = clazz.getMethod("get", String::class.java)
            setMethod = clazz.getMethod("set", String::class.java, String::class.java)
        } catch (e: Exception) {
            // 忽略
        }
    }

    /**
     * 获取系统属性
     */
    fun get(key: String): String? {
        init()
        return try {
            val result = getMethod?.invoke(null, key) as? String
            if (result.isNullOrEmpty()) null else result
        } catch (e: Exception) {
            null
        }
    }

    /**
     * 设置系统属性 (需要 root 权限)
     */
    fun set(key: String, value: String): Boolean {
        init()
        return try {
            setMethod?.invoke(null, key, value)
            true
        } catch (e: Exception) {
            false
        }
    }
}

