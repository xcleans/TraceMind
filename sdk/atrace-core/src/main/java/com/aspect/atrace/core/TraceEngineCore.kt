/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.core

import android.content.Context
import android.os.Build
import android.os.Looper
import android.os.Process
import com.aspect.atrace.ALog
import com.aspect.atrace.TraceConfig
import com.aspect.atrace.TraceEngine
import com.aspect.atrace.TraceEngineImpl
import com.aspect.atrace.core.config.ConfigBuilder
import com.aspect.atrace.core.hook.ArtHookBackend
import com.aspect.atrace.core.hook.NativeArtHookBackend
import com.aspect.atrace.core.hook.SandHookDexMakerBackend
import com.aspect.atrace.core.config.TraceProperties
import com.aspect.atrace.core.server.ServerManager
import com.aspect.atrace.plugin.PluginContext
import com.aspect.atrace.plugin.SampleType
import com.aspect.atrace.plugin.TracePlugin
import com.bytedance.shadowhook.ShadowHook
import java.io.File


/**
 * Hook 类型标志位，与 Native 层 FLAG_* 一一对应。
 * 通过位运算组合后一次 JNI 调用批量安装所有需要的 Hook。
 */
object HookFlags {
    const val BINDER: Long = 1L shl 0
    const val GC: Long = 1L shl 1
    const val LOCK: Long = 1L shl 2
    const val JNI_CALL: Long = 1L shl 3
    const val LOADLIB: Long = 1L shl 4
    const val ALLOC: Long = 1L shl 5
    const val MSGQUEUE: Long = 1L shl 6
    const val IO: Long = 1L shl 7

    private val ID_TO_FLAG = mapOf(
        "binder" to BINDER,
        "gc" to GC,
        "lock" to LOCK,
        "jni" to JNI_CALL,
        "loadlib" to LOADLIB,
        "alloc" to ALLOC,
        "msgqueue" to MSGQUEUE,
        "io" to IO,
    )

    fun fromPluginId(id: String): Long = ID_TO_FLAG[id] ?: 0L
}

/**
 * 追踪引擎核心实现
 */
class TraceEngineCore private constructor(
    private val context: Context,
    private val config: TraceConfig
) : TraceEngine {


    companion object {
        private const val TAG = "ATrace"

        fun register() {
            ALog.d("ATrace", "register")
            TraceEngineImpl.registerFactory { context, config ->
                create(context, config)!!
            }
        }

        /**
         * 创建引擎实例
         */
        fun create(context: Context, config: TraceConfig): TraceEngineCore? {
            ALog.d("ATrace", "create START")
            // 检查系统版本
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
                ALog.d("ATrace", "ATrace requires Android 8.0+, current: ${Build.VERSION.SDK_INT}")
                return null
            }

            // 合并 SystemProperties 配置
            val mergedConfig = ConfigBuilder.merge(config, useSystemPropsAsDefault = true)

            // 打印配置 (调试模式)
            if (mergedConfig.debugMode) {
                TraceProperties.dump()
            }

            val engine = TraceEngineCore(context, mergedConfig)
            if (!engine.init()) {
                ALog.e(TAG, "Failed to initialize trace engine")
                return null
            }

            // 检查是否需要自动启动
            if (TraceProperties.shouldStartOnLaunch()||mergedConfig.startOnLaunch) {
                ALog.i(TAG, "Auto-starting trace (from system property)")
                engine.start()
            }

            return engine
        }

        /** 类名级预过滤：快速判断某个 className 是否可能匹配某条规则 */
        internal fun classCouldMatchRules(className: String, rules: List<String>): Boolean {
            for (rule in rules) {
                when {
                    rule.startsWith("pkg:") ->
                        if (className.startsWith(rule.substring(4))) return true
                    rule.startsWith("cls:") ->
                        if (className == rule.substring(4)) return true
                    rule.startsWith("mth:") -> {
                        val cls = rule.substring(4).substringBeforeLast('.')
                        if (className == cls) return true
                    }
                    else ->
                        if (className.contains(rule)) return true
                }
            }
            return false
        }

        /** 枚举 ClassLoader 关联的 DexFile 中的类名 */
        internal fun enumerateDexClassNames(classLoader: ClassLoader): List<String> {
            val result = mutableListOf<String>()
            try {
                val pathListField = Class.forName("dalvik.system.BaseDexClassLoader")
                    .getDeclaredField("pathList")
                pathListField.isAccessible = true
                val pathList = pathListField.get(classLoader) ?: return result

                val dexElementsField = pathList.javaClass.getDeclaredField("dexElements")
                dexElementsField.isAccessible = true
                val dexElements = dexElementsField.get(pathList) as? Array<*> ?: return result

                for (element in dexElements) {
                    if (element == null) continue
                    val dexFileField = element.javaClass.getDeclaredField("dexFile")
                    dexFileField.isAccessible = true
                    val dexFile = dexFileField.get(element) ?: continue

                    val entriesMethod = dexFile.javaClass.getDeclaredMethod("entries")
                    @Suppress("UNCHECKED_CAST")
                    val entries = entriesMethod.invoke(dexFile) as? java.util.Enumeration<String>
                        ?: continue
                    while (entries.hasMoreElements()) {
                        result.add(entries.nextElement())
                    }
                }
            } catch (e: Exception) {
                ALog.w(TAG, "enumerateDexClassNames failed: ${e.message}")
            }
            return result
        }
    }

    init {
        try {
            ALog.i(TAG, "load so START")
            ShadowHook.init(
                ShadowHook.ConfigBuilder()
                    .setMode(ShadowHook.Mode.SHARED)
                    .setLibLoader { libName ->
                        if (config?.libLoader != null) {
                            config?.libLoader?.loadLibrary(libName)
                        } else {
                            System.loadLibrary(libName)
                        }
                    }
                    .build()
            )
            System.loadLibrary("atrace")
            ALog.i(TAG, "load so END")
        } catch (e: UnsatisfiedLinkError) {
            ALog.e(TAG, "Failed to load native library", e)
        }
    }

    private var nativePtr: Long = 0
    private var tracing: Boolean = false
    private var startToken: Long = 0
    private var endToken: Long = -1
    private val plugins = mutableListOf<TracePlugin>()
    private val pluginContext = PluginContextImpl()
    private var artHookBackend: ArtHookBackend? = null

    /**
     * 初始化引擎
     */
    private fun init(): Boolean {
        // 初始化 JNI Hook 机制 (用于 Object.wait/Unsafe.park 等 Hook)
        if (!JNIHookHelper.init()) {
            ALog.w(TAG, "JNI Hook initialization failed, some features may not work")
        }
        // 初始化Native层
        val mainThread = Looper.getMainLooper().thread
        nativePtr = nativeCreate(
            mainThread,
            config.bufferCapacity,
            config.mainThreadSampleInterval,
            config.otherThreadSampleInterval,
            config.maxStackDepth,
            config.clockType.value,
            config.enableThreadNames,
            config.enableWakeupTrace,
            config.enableAllocTrace,
            config.enableRusage,
            config.debugMode,
            config.shadowPause
        )

        if (nativePtr == 0L) {
            ALog.e(TAG, "Native engine creation failed")
            return false
        }

        // 初始化插件
        initPlugins()
        initArtHookBackend()
        attachJvmtiInstrumentation()

        // 启动 HTTP 服务器 (用于 PC 工具通信)
        if (config.enableHttpServer) {
            ServerManager.init(context, autoStart = true)
        }

        ALog.i(
            TAG,
            "ATrace initialized, SDK=${Build.VERSION.SDK_INT}, arch=${Build.SUPPORTED_ABIS[0]}"
        )
        return true
    }

    private fun initPlugins() {
        val arch = Build.SUPPORTED_ABIS.firstOrNull() ?: "unknown"
        val sdk = Build.VERSION.SDK_INT

        // 1) 收集支持的插件，计算合并后的 Hook 标志位
        var hookFlags = 0L
        val supportedPlugins = mutableListOf<TracePlugin>()

        for (plugin in config.plugins) {
            if (plugin.isSupported(sdk, arch)) {
                supportedPlugins.add(plugin)
                hookFlags = hookFlags or HookFlags.fromPluginId(plugin.id)
            } else {
                ALog.w(TAG, "Plugin not supported: ${plugin.name}")
            }
        }

        // 2) 一次 JNI 调用批量安装所有 Hook
        if (hookFlags != 0L && nativePtr != 0L) {
            val mainThread = Looper.getMainLooper().thread
            nativeInstallHooks(nativePtr, hookFlags, sdk, config.enableWakeupTrace, mainThread)
        }

        // 3) 通知 Plugin 生命周期 (onAttach 不再执行 nativeInit)
        for (plugin in supportedPlugins) {
            try {
                plugin.onAttach(pluginContext)
                plugins.add(plugin)
                ALog.d(TAG, "Plugin attached: ${plugin.name}")
            } catch (e: Exception) {
                ALog.e(TAG, "Failed to attach plugin: ${plugin.name}", e)
            }
        }

        plugins.sortBy { it.priority }
    }

    override fun start(): Long {
        if (tracing) {
            ALog.w(TAG, "Already tracing")
            return startToken
        }

        // 启动插件
        plugins.forEach {
            try {
                it.onStart()
            } catch (e: Exception) {
                ALog.e(TAG, "Plugin start failed: ${it.name}", e)
            }
        }

        // 启动Native追踪
        startToken = nativeStart(nativePtr)
        endToken = -1
        tracing = true
        ALog.i(TAG, "Tracing started, token=$startToken")
        return startToken
    }

    override fun stop(): Long {
        if (!tracing) {
            ALog.w(TAG, "Not tracing")
            return -1
        }

        // 停止插件
        plugins.forEach {
            try {
                it.onStop()
            } catch (e: Exception) {
                ALog.e(TAG, "Plugin stop failed: ${it.name}", e)
            }
        }

        // 停止Native追踪
        endToken = nativeStop(nativePtr)
        tracing = false
        ALog.i(TAG, "Tracing stopped, token=$endToken")
        return endToken
    }

    override fun capture(force: Boolean) {
        if (tracing) {
            nativeCapture(nativePtr, force)
        }
    }

    override fun mark(name: String, args: Array<out Any>) {
        if (tracing) {
            nativeMark(nativePtr, name, args.joinToString(","))
        }
    }

    /**
     * 动态方法插桩入口：通过 Hook ART 的 art_quick_invoke_*_stub 实现方法进入/退出时
     * 记录 SectionBegin/SectionEnd，替代原 JVMTI MethodEntry/MethodExit 方案。
     * 无需 debuggable，无 agent.so 提取与 attach。
     */
    private fun attachJvmtiInstrumentation(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            ALog.w(TAG, "attachJvmtiInstrumentation requires Android 8.0 (API 26)+")
            return false
        }
        if (nativePtr == 0L) {
            ALog.w(
                TAG,
                "attachJvmtiInstrumentation: engine not created yet, call after ATrace init"
            )
            return false
        }
        val ok = artHookBackend?.install(context) == true
        ALog.d(TAG, "attachJvmtiInstrumentation backend=${artHookBackend?.javaClass?.simpleName}: $ok")
        return ok
    }

    private fun initArtHookBackend() {
        artHookBackend = if (Build.VERSION.SDK_INT >= 33) {
            NativeArtHookBackend(
                installNative = ::nativeInstallArtMethodInstrumentation,
                addRuleNative = ::nativeAddWatchedRule,
                removeRuleNative = ::nativeRemoveWatchedRule,
                clearRulesNative = ::nativeClearWatchedRules,
                countRulesNative = ::nativeWatchedRuleCount,
                getRulesNative = ::nativeGetWatchedRules,
                hookMethodNative = ::nativeHookMethod,
                unhookMethodNative = ::nativeUnhookMethod,
                scanClassNative = ::nativeScanClassAndHook,
            )
        } else {
            SandHookDexMakerBackend()
        }
    }


    override fun beginSection(name: String): Long {
        if (!tracing) return -1
        return nativeBeginSection(nativePtr, name)
    }

    override fun endSection(token: Long) {
        if (tracing && token >= 0) {
            nativeEndSection(nativePtr, token)
        }
    }

    override fun export(outputPath: String?): File? {
        val dir = outputPath ?: (context.filesDir.absolutePath + "/atrace")
        val dirFile = File(dir)
        if (!dirFile.exists()) {
            dirFile.mkdirs()
        }

        val timestamp = System.currentTimeMillis()
        val tracePath = "$dir/trace_$timestamp.perfetto"
        // Native层自动生成 mapping 文件: $tracePath.mapping

        val extra = buildExtraInfo()
        if (tracing) {
            endToken = nativeStop(nativePtr)
            tracing = false
        }
        if (endToken < 0) {
            ALog.e(TAG, "No valid end token, was tracing started/stopped properly?")
            return null
        }
        val result = nativeExport(nativePtr, startToken, endToken, tracePath, tracePath, extra)

        return if (result == 0) {
            ALog.i(TAG, "Trace exported: $tracePath, mapping: $tracePath.mapping")
            File(tracePath)
        } else {
            ALog.e(TAG, "Export failed: $result")
            null
        }
    }

    override fun isTracing(): Boolean = tracing

    /**
     * 暂停采样（不卸载 Hook，仅跳过采样点）
     */
    fun pause() {
        if (nativePtr != 0L) {
            nativePause(nativePtr)
            ALog.i(TAG, "Sampling paused")
        }
    }

    /**
     * 恢复采样
     */
    fun resume() {
        if (nativePtr != 0L) {
            nativeResume(nativePtr)
            ALog.i(TAG, "Sampling resumed")
        }
    }

    /**
     * 查询暂停状态
     */
    fun isPaused(): Boolean {
        return nativePtr != 0L && nativeIsPaused(nativePtr)
    }

    /**
     * 动态更新采样间隔
     *
     * @param mainIntervalNs 主线程间隔（纳秒），0 表示不修改
     * @param otherIntervalNs 其他线程间隔（纳秒），0 表示不修改
     */
    fun setSamplingInterval(mainIntervalNs: Long = 0, otherIntervalNs: Long = 0) {
        if (nativePtr != 0L) {
            nativeSetSamplingInterval(nativePtr, mainIntervalNs, otherIntervalNs)
            ALog.i(
                TAG,
                "Sampling interval updated: main=${mainIntervalNs}ns, other=${otherIntervalNs}ns"
            )
        }
    }

    /**
     * 获取已启用的插件列表
     */
    fun getPlugins(): List<Map<String, Any>> {
        return plugins.map { plugin ->
            mapOf(
                "id" to plugin.id,
                "name" to plugin.name,
                "priority" to plugin.priority,
                "config" to plugin.getConfig()
            )
        }
    }

    /**
     * 在运行时切换单个插件的启用/禁用
     *
     * 仅在 tracing 状态下有效。enable=true 调 onStart()，enable=false 调 onStop()。
     */
    fun togglePlugin(pluginId: String, enable: Boolean): Boolean {
        val plugin = plugins.find { it.id == pluginId } ?: return false
        try {
            if (enable) plugin.onStart() else plugin.onStop()
            ALog.i(TAG, "Plugin toggled: ${plugin.name} -> $enable")
            return true
        } catch (e: Exception) {
            ALog.e(TAG, "Failed to toggle plugin: ${plugin.name}", e)
            return false
        }
    }

    /**
     * 获取进程内所有线程信息
     */
    fun getThreadList(): List<Map<String, Any>> {
        val threads = mutableListOf<Map<String, Any>>()
        val taskDir = File("/proc/self/task")
        val mainTid = Process.myPid()

        taskDir.listFiles()?.forEach { tidDir ->
            val tid = tidDir.name.toIntOrNull() ?: return@forEach
            val commFile = File(tidDir, "comm")
            val name = try {
                commFile.readText().trim()
            } catch (_: Exception) {
                "unknown"
            }
            threads.add(
                mapOf(
                    "tid" to tid,
                    "name" to name,
                    "isMainThread" to (tid == mainTid)
                )
            )
        }
        return threads.sortedBy { it["tid"] as Int }
    }

    /**
     * 获取调试信息 (JSON 格式)
     */
    fun getDebugInfo(): org.json.JSONObject {
        val json = org.json.JSONObject()

        // 采样缓冲区信息
        val sampling = org.json.JSONObject()
        if (nativePtr != 0L) {
            val info = nativeGetBufferInfo(nativePtr)
            sampling.put("currentTicket", info[0])
            sampling.put("capacity", info[1])
            sampling.put("start", startToken)
            sampling.put("end", if (endToken >= 0) endToken else info[0])
        }
        json.put("sampling", sampling)

        // 引擎状态
        val state = org.json.JSONObject()
        state.put("tracing", tracing)
        state.put("startToken", startToken)
        state.put("endToken", endToken)
        state.put("pid", Process.myPid())
        state.put("pluginCount", plugins.size)
        state.put("plugins", plugins.joinToString(",") { it.name })
        json.put("state", state)

        // 配置信息
        val configJson = org.json.JSONObject()
        configJson.put("bufferCapacity", config.bufferCapacity)
        configJson.put("mainThreadInterval", config.mainThreadSampleInterval)
        configJson.put("otherThreadInterval", config.otherThreadSampleInterval)
        configJson.put("maxStackDepth", config.maxStackDepth)
        configJson.put("clockType", config.clockType.name)
        configJson.put("debugMode", config.debugMode)
        configJson.put("shadowPause", config.shadowPause)
        configJson.put("enableWakeup", config.enableWakeupTrace)
        configJson.put("enableAlloc", config.enableAllocTrace)
        configJson.put("enableRusage", config.enableRusage)
        json.put("config", configJson)

        // 设备信息
        val device = org.json.JSONObject()
        device.put("sdk", Build.VERSION.SDK_INT)
        device.put("arch", Build.SUPPORTED_ABIS.firstOrNull() ?: "unknown")
        device.put("model", Build.MODEL)
        json.put("device", device)

        return json
    }

    override fun release() {
        if (tracing) {
            stop()
        }

        // 停止 HTTP 服务器
        ServerManager.stop()

        plugins.forEach {
            try {
                it.onDetach()
            } catch (e: Exception) {
                ALog.e(TAG, "Plugin detach failed: ${it.name}", e)
            }
        }
        plugins.clear()

        if (nativePtr != 0L) {
            nativeRelease(nativePtr)
            nativePtr = 0
        }

        ALog.i(TAG, "ATrace released")
    }

    private fun buildExtraInfo(): String {
        return """{"processId":${Process.myPid()},"package":"${context.packageName}"}"""
    }

    /**
     * 插件上下文实现
     */
    private inner class PluginContextImpl : PluginContext {
        override val sdkVersion: Int = Build.VERSION.SDK_INT
        override val arch: String = Build.SUPPORTED_ABIS.firstOrNull() ?: "unknown"
        override val mainThreadId: Int = Process.myPid()
        override val samplerPtr: Long get() = nativePtr

        override fun requestSample(
            type: SampleType,
            force: Boolean,
            captureAtEnd: Boolean,
            beginNano: Long
        ) {
            if (tracing && nativePtr != 0L) {
                nativeRequestSample(nativePtr, type.value, force, captureAtEnd, beginNano)
            }
        }

        override fun mark(type: SampleType, name: String, vararg args: Any) {
            if (tracing && nativePtr != 0L) {
                nativeMark(nativePtr, name, args.joinToString(","))
            }
        }
    }

    // Native 方法
    private external fun nativeInstallHooks(
        enginePtr: Long,
        flags: Long,
        sdkVersion: Int,
        enableWakeup: Boolean,
        mainThread: Thread
    )

    private external fun nativeCreate(
        mainThread: Thread,
        bufferCapacity: Int,
        mainThreadInterval: Long,
        otherThreadInterval: Long,
        maxStackDepth: Int,
        clockType: Int,
        enableThreadNames: Boolean,
        enableWakeup: Boolean,
        enableAlloc: Boolean,
        enableRusage: Boolean,
        debugMode: Boolean,
        shadowPause: Boolean
    ): Long

    private external fun nativeStart(ptr: Long): Long
    private external fun nativeStop(ptr: Long): Long
    private external fun nativeCapture(ptr: Long, force: Boolean)
    private external fun nativeMark(ptr: Long, name: String, args: String)
    private external fun nativeBeginSection(ptr: Long, name: String): Long
    private external fun nativeEndSection(ptr: Long, token: Long)
    private external fun nativeRequestSample(
        ptr: Long,
        type: Int,
        force: Boolean,
        captureAtEnd: Boolean,
        beginNano: Long
    )

    private external fun nativeExport(
        ptr: Long,
        startToken: Long,
        endToken: Long,
        tracePath: String,
        mappingPath: String,
        extra: String
    ): Int

    private external fun nativeGetBufferInfo(ptr: Long): LongArray
    private external fun nativePause(ptr: Long)
    private external fun nativeResume(ptr: Long)
    private external fun nativeIsPaused(ptr: Long): Boolean
    private external fun nativeSetSamplingInterval(
        ptr: Long,
        mainIntervalNs: Long,
        otherIntervalNs: Long
    )

    private external fun nativeRelease(ptr: Long)
    private external fun nativeInstallArtMethodInstrumentation(): Boolean

    // ── WatchList JNI bindings ─────────────────────────────────────────────────
    private external fun nativeAddWatchedRule(scope: String, value: String)
    private external fun nativeRemoveWatchedRule(entry: String)
    private external fun nativeClearWatchedRules()
    private external fun nativeWatchedRuleCount(): Int
    private external fun nativeGetWatchedRules(): Array<String>

    // ── 精确 Hook JNI bindings ────────────────────────────────────────────────
    private external fun nativeHookMethod(
        className: String, methodName: String, signature: String, isStatic: Boolean
    ): Boolean
    private external fun nativeUnhookMethod(
        className: String, methodName: String, signature: String, isStatic: Boolean
    )

    // ── 类扫描自动 Hook JNI binding ──────────────────────────────────────────
    private external fun nativeScanClassAndHook(cls: Class<*>): Int

    // ── WatchList 公开 API ─────────────────────────────────────────────────────

    /**
     * @param scope `package` / `class` / `method` / `substring`（默认）
     * @param value 包前缀、全限定类名、或 `Fqcn.methodName`（内部类 FQCN 用 `$`）
     *
     * 启用 autoHook 时会自动扫描已加载类。
     */
    override fun addWatchedRule(scope: String, value: String) {
        try {
            artHookBackend?.addWatchedRule(scope, value)
            if (autoHookEnabled) scanLoadedClasses(context)
        } catch (e: Exception) {
            ALog.w(TAG, "addWatchedRule failed: ${e.message}")
        }
    }

    override fun removeWatchedRule(entry: String) {
        try { artHookBackend?.removeWatchedRule(entry) }
        catch (e: Exception) { ALog.w(TAG, "removeWatchedRule failed: ${e.message}") }
    }

    override fun clearWatchedRules() {
        try { artHookBackend?.clearWatchedRules() }
        catch (e: Exception) { ALog.w(TAG, "clearWatchedRules failed: ${e.message}") }
    }

    override fun watchedRuleCount(): Int = try { artHookBackend?.watchedRuleCount() ?: 0 } catch (_: Exception) { 0 }

    override fun getWatchedRules(): List<String> = try { artHookBackend?.getWatchedRules() ?: emptyList() } catch (_: Exception) { emptyList() }

    // ── 精确 Hook 公开 API ────────────────────────────────────────────────────

    override fun hookMethod(
        className: String, methodName: String, signature: String, isStatic: Boolean
    ): Boolean = artHookBackend?.hookMethod(className, methodName, signature, isStatic) ?: false

    override fun unhookMethod(
        className: String, methodName: String, signature: String, isStatic: Boolean
    ) = artHookBackend?.unhookMethod(className, methodName, signature, isStatic)

    // ── 类扫描自动 Hook 公开 API ────────────────────────────────────────────

    override fun scanAndHookClass(clazz: Class<*>): Int {
        return try { artHookBackend?.scanAndHookClass(clazz) ?: 0 }
        catch (e: Exception) { ALog.w(TAG, "scanAndHookClass failed: ${e.message}"); 0 }
    }

    @Volatile
    private var autoHookEnabled = false
    private var classLoadWatcher: ClassLoadWatcher? = null

    override fun enableAutoHook(context: Context) {
        if (autoHookEnabled) return
        try {
            autoHookEnabled = true
            classLoadWatcher = ClassLoadWatcher(context) { cls ->
                try { artHookBackend?.scanAndHookClass(cls) ?: 0 }
                catch (e: Exception) { ALog.w(TAG, "autoHook scan failed: ${e.message}"); 0 }
            }.also { it.install() }
            ALog.i(TAG, "Auto-hook enabled")
        } catch (e: Exception) {
            autoHookEnabled = false
            ALog.w(TAG, "enableAutoHook failed: ${e.message}")
        }
    }

    override fun disableAutoHook() {
        if (!autoHookEnabled) return
        autoHookEnabled = false
        try { classLoadWatcher?.uninstall() }
        catch (e: Exception) { ALog.w(TAG, "disableAutoHook failed: ${e.message}") }
        classLoadWatcher = null
        ALog.i(TAG, "Auto-hook disabled")
    }

    override fun scanLoadedClasses(context: Context): Int {
        return try {
            val cl = context.classLoader ?: return 0
            val rules = getWatchedRules()
            if (rules.isEmpty()) return 0

            var total = 0
            val findLoaded = ClassLoader::class.java
                .getDeclaredMethod("findLoadedClass", String::class.java)
            findLoaded.isAccessible = true

            for (className in enumerateDexClassNames(cl)) {
                if (!classCouldMatchRules(className, rules)) continue
                try {
                    val clazz = findLoaded.invoke(cl, className) as? Class<*> ?: continue
                    total += artHookBackend?.scanAndHookClass(clazz) ?: 0
                } catch (_: Exception) { /* skip single class */ }
            }
            if (total > 0) ALog.i(TAG, "scanLoadedClasses: auto-hooked $total methods")
            total
        } catch (e: Exception) {
            ALog.w(TAG, "scanLoadedClasses failed: ${e.message}")
            0
        }
    }

}
