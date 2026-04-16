/*
 * Copyright (c) 2024 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.test.trace

import android.app.Application
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.aspect.atrace.ATrace
import com.aspect.atrace.TraceConfig
import com.aspect.atrace.core.TraceEngineCore
import java.util.concurrent.Executors

class App : Application() {

    private val executor = Executors.newCachedThreadPool()

    override fun attachBaseContext(base: Context?) {
        super.attachBaseContext(base)
    }

    override fun onCreate() {
        super.onCreate()
        initATrace()
        setupWatchRules()
        hookTargetMethods()
//        scheduleHookVerification()

        Log.d(TAG, "ATrace initialized in onCreate")
    }

    private fun initATrace() {
        ATrace.init(this, initTraceEngine = {
            TraceEngineCore.register()
        }) {
            bufferCapacity = 100_000_000
            mainThreadSampleInterval = 1_000_000L
            otherThreadSampleInterval = 5_000_000L
            maxStackDepth = 64
            enableThreadNames = true
            enableWakeupTrace = true
            enableAllocTrace = false
            enableRusage = true
            enableHttpServer = true
            clockType = TraceConfig.ClockType.BOOTTIME
            outputFormat = TraceConfig.OutputFormat.PERFETTO
            debugMode = true
            startOnLaunch = true
            shadowPause = false
            enablePlugins(*Plugins.get())
        }
    }

    private fun setupWatchRules() {
        ATrace.clearWatchedRules()
//        ATrace.addWatchedRule("package", "androidx.activity")
//        ATrace.addWatchedRule("package", "com.test.trace")
        ATrace.addWatchedRule("class", "com.test.trace.ArtMethodCallTest")
        Log.d(TAG, "Watch rules: ${ATrace.getWatchedRules()}")
    }

    private fun hookTargetMethods() {
        // P3: 使用 WatchList 自动 hook —— 扫描已加载类 + 安装 ClassLoader 代理
        val autoHooked = ATrace.scanLoadedClasses(this)
        ATrace.enableAutoHook(this)
        Log.i(TAG, "Auto-hook: scanned loaded classes, hooked $autoHooked methods")
    }

    /**
     * 延迟 1 秒后在后台线程执行验证，确保 ART 已稳定。
     * 覆盖场景：普通调用、JIT 高频调用、内联候选、递归调用。
     */
    private fun scheduleHookVerification() {
        Handler(Looper.getMainLooper()).postDelayed({
            executor.execute {
                Log.i(TAG, "═══ Hook Verification Start ═══")
                val t0 = System.nanoTime()
                val passed = ArtMethodCallTest.runAll()
                val elapsed = (System.nanoTime() - t0) / 1_000_000.0
                Log.i(TAG, "═══ Hook Verification End: $passed tests, %.1f ms ═══".format(elapsed))

                // 二次高频调用：验证 JIT 抑制在首次 50k 之后仍然有效
                Log.i(TAG, "── Round 2: JIT stress (再次 100k 调用) ──")
                val r2 = ArtMethodCallTest.testHotLoop(100_000)
                Log.i(TAG, "  testHotLoop(100000) → $r2")

                Log.i(TAG, "── Round 3: 延迟后递归 ──")
                Thread.sleep(500)
                val r3 = ArtMethodCallTest.testRecursive(50)
                Log.i(TAG, "  testRecursive(50) → $r3")

                Log.i(TAG, "═══ All rounds complete ═══")
            }
        }, 1000)
    }

    companion object {
        private const val TAG = "ATrace:Sample"
    }
}
