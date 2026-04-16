/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace

import android.content.Context
import java.io.File

/**
 * ATrace - Advanced Android Trace Tool
 *
 * 公开API入口，提供简洁易用的追踪接口。
 *
 * 使用示例:
 * ```kotlin
 * // 初始化
 * ATrace.init(context) {
 *     bufferSize = 100_000
 *     sampleInterval = 1_000_000L
 *     enablePlugins(BinderPlugin, GCPlugin)
 * }
 *
 * // 开始追踪
 * ATrace.start()
 *
 * // 停止并导出
 * val file = ATrace.stopAndExport()
 * ```
 */
object ATrace {

    private var engine: TraceEngine? = null
    private var config: TraceConfig = TraceConfig.default()

    /**
     * 初始化 ATrace
     *
     * @param context Application Context
     * @param block 配置DSL
     */
    @JvmStatic
    fun init(
        context: Context,
        initTraceEngine: (() -> Unit),
        block: TraceConfig.Builder.() -> Unit = {}
    ) {
        ALog.d("ATrace", "init START")
        initTraceEngine.invoke()
        if (engine != null) {
            ALog.d("ATrace", "inited")
            return
        }
        config = TraceConfig.Builder().apply(block).build()
        engine = TraceEngineImpl.create(context, config)
        ALog.d("ATrace", "init END")
    }

    /**
     * 开始追踪
     *
     * @return 追踪会话Token，用于后续stop
     */
    @JvmStatic
    fun start(): Long {
        return engine?.start() ?: -1L
    }

    /**
     * 停止追踪
     *
     * @return 追踪会话结束Token
     */
    @JvmStatic
    fun stop(): Long {
        return engine?.stop() ?: -1L
    }

    /**
     * 停止追踪并导出数据
     *
     * @param outputPath 输出路径，为空则使用默认路径
     * @return 导出的文件
     */
    @JvmStatic
    fun stopAndExport(outputPath: String? = null): File? {
        val endToken = stop()
        if (endToken < 0) return null
        return engine?.export(outputPath)
    }

    /**
     * 手动捕获一次堆栈 (可在关键位置调用)
     *
     * @param force 是否强制采样（忽略间隔限制）
     */
    @JvmStatic
    fun capture(force: Boolean = false) {
        engine?.capture(force)
    }

    /**
     * 添加自定义标记点
     *
     * @param name 标记名称
     * @param args 附加参数
     */
    @JvmStatic
    fun mark(name: String, vararg args: Any) {
        engine?.mark(name, args)
    }

    /**
     * 开始一个自定义区间
     *
     * @param name 区间名称
     * @return 区间Token，用于endSection
     */
    @JvmStatic
    fun beginSection(name: String): Long {
        return engine?.beginSection(name) ?: -1L
    }

    /**
     * 结束自定义区间
     *
     * @param token beginSection返回的Token
     */
    @JvmStatic
    fun endSection(token: Long) {
        engine?.endSection(token)
    }

    /**
     * 检查是否正在追踪
     */
    @JvmStatic
    fun isTracing(): Boolean {
        return engine?.isTracing() ?: false
    }

    /**
     * 获取当前配置
     */
    @JvmStatic
    fun getConfig(): TraceConfig = config

    /**
     * 释放资源
     */
    @JvmStatic
    fun release() {
        engine?.release()
        engine = null
    }


    /**
     * 添加 ArtMethod 监控规则。
     * 启用 [enableAutoHook] 后，新增规则会自动扫描已加载类并 hook 匹配方法。
     *
     * @param scope `package` | `class` | `method` | `substring`（默认子串）
     * @param value 包前缀 `com.foo.`、全限定类名、或 `com.foo.Bar.methodName`
     */
    @JvmStatic
    fun addWatchedRule(scope: String, value: String) {
        engine?.addWatchedRule(scope, value)
    }

    @JvmStatic
    fun removeWatchedRule(entry: String) {
        engine?.removeWatchedRule(entry)
    }

    @JvmStatic
    fun clearWatchedRules() {
        engine?.clearWatchedRules()
    }

    @JvmStatic
    fun getWatchedRules(): List<String> =
        engine?.getWatchedRules() ?: emptyList()

    @JvmStatic
    fun hookMethod(className: String, methodName: String, signature: String, isStatic: Boolean): Boolean =
        engine?.hookMethod(className, methodName, signature, isStatic) ?: false

    @JvmStatic
    fun unhookMethod(className: String, methodName: String, signature: String, isStatic: Boolean) {
        engine?.unhookMethod(className, methodName, signature, isStatic)
    }

    /**
     * 扫描 [clazz] 的全部 declared methods，匹配 WatchList 规则后自动 hook。
     * @return 本次新增 hook 数量
     */
    @JvmStatic
    fun scanAndHookClass(clazz: Class<*>): Int =
        engine?.scanAndHookClass(clazz) ?: 0

    /**
     * 启用自动 hook：安装 ClassLoader 代理 + 扫描已加载类。
     * 后续新加载的类会自动与 WatchList 规则匹配并 hook。
     */
    @JvmStatic
    fun enableAutoHook(context: android.content.Context) {
        engine?.enableAutoHook(context)
    }

    /** 关闭自动 hook。 */
    @JvmStatic
    fun disableAutoHook() {
        engine?.disableAutoHook()
    }

    /**
     * 扫描所有已加载的类，与 WatchList 规则匹配后自动 hook。
     * @return 本次新增 hook 数量
     */
    @JvmStatic
    fun scanLoadedClasses(context: android.content.Context): Int =
        engine?.scanLoadedClasses(context) ?: 0

    fun getEngine(): TraceEngine? = engine
}

/**
 * 追踪引擎接口
 */
interface TraceEngine {
    fun start(): Long
    fun stop(): Long
    fun capture(force: Boolean)
    fun mark(name: String, args: Array<out Any>)
    fun beginSection(name: String): Long
    fun endSection(token: Long)
    fun export(outputPath: String?): File?

    fun isTracing(): Boolean
    fun release()
    fun addWatchedRule(scope: String, value: String)
    fun removeWatchedRule(entry: String)
    fun clearWatchedRules()
    fun watchedRuleCount(): Int
    fun getWatchedRules(): List<String> = emptyList()

    /**
     * 精确 hook 指定方法（替换 entry_point_from_quick_compiled_code_）。
     * 方法进入时会自动记录 SectionBegin 事件。
     *
     * @param className  JNI 格式类名（如 "com/example/Foo"）
     * @param methodName 方法名
     * @param signature  JNI 方法签名（如 "(I)V"）
     * @param isStatic   是否静态方法
     * @return 是否成功
     */
    fun hookMethod(className: String, methodName: String, signature: String, isStatic: Boolean): Boolean = false

    /**
     * 恢复指定方法的原始 entry_point。
     */
     fun unhookMethod(className: String, methodName: String, signature: String, isStatic: Boolean):Unit? {
         return null
     }

    // ── 类扫描自动 Hook ───────────────────────────────────────────────────────

    /**
     * 扫描 [clazz] 的全部 declared methods，与 WatchList 规则匹配后自动 hook。
     * @return 本次新增 hook 数量
     */
    fun scanAndHookClass(clazz: Class<*>): Int = 0

    /**
     * 启用自动 hook：替换 ClassLoader 代理，后续加载的类自动与 WatchList 规则匹配。
     * 同时立即扫描已加载的类。
     */
    fun enableAutoHook(context: android.content.Context) {}

    /** 关闭自动 hook，恢复原始 ClassLoader。 */
    fun disableAutoHook() {}

    /**
     * 扫描当前 ClassLoader 中所有已加载的类，与 WatchList 规则匹配后自动 hook。
     * @return 本次新增 hook 数量
     */
    fun scanLoadedClasses(context: android.content.Context): Int = 0
}

/**
 * 追踪引擎实现占位 (实际实现在 atrace-core 模块)
 */
object TraceEngineImpl {
    private var factory: ((Context, TraceConfig) -> TraceEngine)? = null

    fun registerFactory(factory: (Context, TraceConfig) -> TraceEngine) {
        this.factory = factory
    }

    fun create(context: Context, config: TraceConfig): TraceEngine? {
        if (factory == null) {
            ALog.e(
                "ATrace",
                "TraceEngineImpl: no engine factory registered. " +
                        "Call TraceEngineCore.register() in Application.attachBaseContext() " +
                        "BEFORE ATrace.init(), or register a custom TraceEngine via TraceEngineImpl.registerFactory."
            )
            return null
        }
        return factory?.invoke(context, config)
    }
}

