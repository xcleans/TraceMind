/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.plugin

/**
 * 追踪插件接口
 *
 * 通过插件机制实现可扩展的Hook能力，每个插件负责一类追踪点。
 *
 * 生命周期:
 * 1. onAttach() - 引擎初始化时调用
 * 2. onStart()  - 追踪开始时调用
 * 3. onStop()   - 追踪停止时调用
 * 4. onDetach() - 引擎释放时调用
 */
interface TracePlugin {

    /**
     * 插件唯一标识
     */
    val id: String

    /**
     * 插件名称 (用于调试)
     */
    val name: String

    /**
     * 插件优先级 (数值越小优先级越高)
     */
    val priority: Int get() = 100

    /**
     * 检查当前环境是否支持此插件
     *
     * @param sdkVersion Android SDK版本
     * @param arch CPU架构 (arm64-v8a, armeabi-v7a, x86_64, x86)
     * @return 是否支持
     */
    fun isSupported(sdkVersion: Int, arch: String): Boolean

    /**
     * 附加到追踪引擎
     *
     * @param context 插件上下文
     */
    fun onAttach(context: PluginContext)

    /**
     * 追踪开始
     */
    fun onStart()

    /**
     * 追踪停止
     */
    fun onStop()

    /**
     * 从追踪引擎分离
     */
    fun onDetach()

    /**
     * 获取插件配置
     */
    fun getConfig(): Map<String, Any> = emptyMap()
}

/**
 * 插件上下文
 */
interface PluginContext {

    /**
     * Android SDK 版本
     */
    val sdkVersion: Int

    /**
     * CPU 架构
     */
    val arch: String

    /**
     * 主线程ID
     */
    val mainThreadId: Int

    /**
     * Native采样器指针
     */
    val samplerPtr: Long

    /**
     * 请求一次采样
     *
     * @param type 采样类型
     * @param force 是否强制采样
     * @param captureAtEnd 是否在调用结束时捕获
     * @param beginNano 开始时间 (纳秒)
     */
    fun requestSample(
        type: SampleType,
        force: Boolean = false,
        captureAtEnd: Boolean = false,
        beginNano: Long = 0
    )

    /**
     * 记录标记
     */
    fun mark(type: SampleType, name: String, vararg args: Any)
}

/**
 * 采样类型枚举
 */
enum class SampleType(val value: Int) {
    CUSTOM(1),              // 自定义采样
    BINDER(2),              // Binder IPC
    GC_WAIT(3),             // GC等待
    MONITOR_ENTER(4),       // Monitor锁
    OBJECT_WAIT(5),         // Object.wait
    UNSAFE_PARK(6),         // Unsafe.park
    JNI_CALL(7),            // JNI调用
    LOAD_LIBRARY(8),        // SO加载
    OBJECT_ALLOC(9),        // 对象分配
    IO_READ(10),            // IO读
    IO_WRITE(11),           // IO写
    NATIVE_POLL(12),        // MessageQueue等待
    WAKEUP(20),             // 唤醒事件
    MESSAGE_BEGIN(30),      // Message开始
    MESSAGE_END(31),        // Message结束
    SECTION_BEGIN(40),      // 自定义区间开始
    SECTION_END(41),        // 自定义区间结束
}

/**
 * 基础插件实现
 *
 * 提供默认的生命周期管理，子类只需覆写需要的方法
 */
abstract class BasePlugin : TracePlugin {

    protected var context: PluginContext? = null
        private set

    override val priority: Int = 100

    override fun onAttach(context: PluginContext) {
        this.context = context
    }

    override fun onDetach() {
        this.context = null
    }

    override fun onStart() {}

    override fun onStop() {}

    override fun getConfig(): Map<String, Any> = emptyMap()
}

