/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.plugins

import android.os.Build
import android.os.Looper
import android.util.Printer
import com.aspect.atrace.plugin.BasePlugin

/**
 * Binder IPC 追踪插件
 *
 * Hook 安装已由 TraceEngineCore.nativeInstallHooks 批量完成，
 * onAttach 仅负责生命周期管理，onStart/onStop 控制启用标志位。
 */
object BinderPlugin : BasePlugin() {
    override val id = "binder"
    override val name = "Binder IPC Trace"
    override val priority = 10

    override fun isSupported(sdkVersion: Int, arch: String): Boolean {
        return sdkVersion >= Build.VERSION_CODES.O && arch.contains("arm")
    }

    override fun onStart() {
        nativeEnable(true)
    }

    override fun onStop() {
        nativeEnable(false)
    }

    private external fun nativeEnable(enable: Boolean)
}

/**
 * GC 追踪插件
 */
object GCPlugin : BasePlugin() {
    override val id = "gc"
    override val name = "GC Wait Trace"
    override val priority = 20

    override fun isSupported(sdkVersion: Int, arch: String): Boolean {
        return sdkVersion >= Build.VERSION_CODES.O && arch.contains("arm")
    }

    override fun onStart() {
        nativeEnable(true)
    }

    override fun onStop() {
        nativeEnable(false)
    }

    private external fun nativeEnable(enable: Boolean)
}

/**
 * 锁竞争追踪插件
 *
 * 追踪 synchronized, Object.wait, Unsafe.park 等锁相关操作
 *
 * 包含:
 * - Monitor::MonitorEnter (PLT Hook)
 * - Object.wait/notify/notifyAll (JNI Hook)
 * - Unsafe.park/unpark (JNI Hook)
 */
object LockPlugin : BasePlugin() {
    override val id = "lock"
    override val name = "Lock Contention Trace"
    override val priority = 30

    private var enableWakeup = false

    override fun isSupported(sdkVersion: Int, arch: String): Boolean {
        return sdkVersion >= Build.VERSION_CODES.O
    }

    override fun onStart() {
        nativeEnable(true)
    }

    override fun onStop() {
        nativeEnable(false)
    }

    override fun getConfig(): Map<String, Any> = mapOf(
        "enableWakeup" to enableWakeup
    )

    fun withWakeupTrace(enable: Boolean): LockPlugin {
        enableWakeup = enable
        return this
    }

    private external fun nativeEnable(enable: Boolean)
}

/**
 * JNI 调用追踪插件
 */
object JNIPlugin : BasePlugin() {
    override val id = "jni"
    override val name = "JNI Call Trace"
    override val priority = 40

    override fun isSupported(sdkVersion: Int, arch: String): Boolean {
        return sdkVersion >= Build.VERSION_CODES.O && arch.contains("arm")
    }

    override fun onStart() {
        nativeEnable(true)
    }

    override fun onStop() {
        nativeEnable(false)
    }

    private external fun nativeEnable(enable: Boolean)
}

/**
 * SO 加载追踪插件
 */
object LoadLibraryPlugin : BasePlugin() {
    override val id = "loadlib"
    override val name = "Library Load Trace"
    override val priority = 50

    override fun isSupported(sdkVersion: Int, arch: String): Boolean {
        return sdkVersion >= Build.VERSION_CODES.O
    }

    override fun onStart() {
        nativeEnable(true)
    }

    override fun onStop() {
        nativeEnable(false)
    }

    private external fun nativeEnable(enable: Boolean)
}

/**
 * 对象分配追踪插件
 *
 * 追踪Java对象分配，开销较大，建议仅在需要时启用
 */
object AllocPlugin : BasePlugin() {
    override val id = "alloc"
    override val name = "Object Allocation Trace"
    override val priority = 100

    override fun isSupported(sdkVersion: Int, arch: String): Boolean {
        return sdkVersion >= Build.VERSION_CODES.O
    }

    override fun onStart() {
        nativeResetStats()
        nativeEnable(true)
    }

    override fun onStop() {
        nativeEnable(false)
    }

    fun getStats(): LongArray = nativeGetStats()

    fun resetStats() {
        nativeResetStats()
    }

    private external fun nativeEnable(enable: Boolean)
    private external fun nativeGetStats(): LongArray
    private external fun nativeResetStats()
}

/**
 * IO 追踪插件
 *
 * 追踪 read/write 系统调用
 */
object IOPlugin : BasePlugin() {
    override val id = "io"
    override val name = "IO Trace"
    override val priority = 60

    override fun isSupported(sdkVersion: Int, arch: String): Boolean {
        return sdkVersion >= Build.VERSION_CODES.O
    }

    override fun onStart() {
        nativeEnable(true)
    }

    override fun onStop() {
        nativeEnable(false)
    }

    private external fun nativeEnable(enable: Boolean)
}

/**
 * MessageQueue 追踪插件
 *
 * 追踪主线程 Message 处理，用于 Jank 检测。
 * - nativePollOnce Hook：记录「等消息」时长与唤醒瞬间堆栈
 * - Looper setMessageLogging：在「>>>>> Dispatching to」时采 kMessageBegin，在「<<<<< Finished to」时采 kMessageEnd
 */
object MessageQueuePlugin : BasePlugin() {
    override val id = "msgqueue"
    override val name = "MessageQueue Trace"
    override val priority = 5

    private const val DISPATCHING_PREFIX = ">>>>> Dispatching to"
    private const val FINISHED_PREFIX = "<<<<< Finished to"

    override fun isSupported(sdkVersion: Int, arch: String): Boolean {
        return sdkVersion >= Build.VERSION_CODES.O
    }

    override fun onStart() {
        nativeEnable(true)
        registerDispatchSampling()
    }

    override fun onStop() {
        unregisterDispatchSampling()
        nativeEnable(false)
    }

    /** 在 Looper 派发前/后各采一次样：kMessageBegin / kMessageEnd */
    private fun registerDispatchSampling() {
        Looper.getMainLooper()?.setMessageLogging(Printer { line ->
            when {
                line != null && line.startsWith(DISPATCHING_PREFIX) -> nativeSampleAtDispatchMessage()
                line != null && line.startsWith(FINISHED_PREFIX) -> nativeSampleAtMessageEnd()
            }
        })
    }

    private fun unregisterDispatchSampling() {
        Looper.getMainLooper()?.setMessageLogging(null)
    }

    private external fun nativeEnable(enable: Boolean)
    private external fun nativeSampleAtDispatchMessage()
    private external fun nativeSampleAtMessageEnd()
}

