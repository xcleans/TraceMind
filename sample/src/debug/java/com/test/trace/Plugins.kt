/*
 * Copyright (c) 2024 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.test.trace

import com.aspect.atrace.plugin.TracePlugin
import com.aspect.atrace.plugins.*

/**
 * Debug 构建：启用 atrace-core 内置插件
 */
object Plugins {
    fun get(): Array<TracePlugin> = arrayOf(
        MessageQueuePlugin,
        BinderPlugin,
        GCPlugin,
        LockPlugin.withWakeupTrace(true),
        JNIPlugin,
//        LoadLibraryPlugin,
        IOPlugin,
    )
}
