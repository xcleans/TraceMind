/*
 * Copyright (c) 2024 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.sample.test

import android.content.Context
import android.content.pm.PackageManager

/**
 * Binder IPC 测试
 *
 * 通过调用系统服务触发 Binder 调用
 */
object BinderTest {
    fun test(context: Context) {
        Thread {
            // 调用 PackageManager 会触发 Binder IPC
            val pm = context.packageManager
            pm.getInstalledPackages(PackageManager.GET_META_DATA)
            pm.getInstalledApplications(PackageManager.GET_META_DATA)

            // 调用 ActivityManager
            val am = context.getSystemService(Context.ACTIVITY_SERVICE)

            // 调用 WindowManager
            val wm = context.getSystemService(Context.WINDOW_SERVICE)

            // 调用 PowerManager
            val powerManager = context.getSystemService(Context.POWER_SERVICE)

            // 多次调用以产生更多采样点
            repeat(10) {
                pm.getInstalledPackages(0)
            }
        }.start()
    }
}
