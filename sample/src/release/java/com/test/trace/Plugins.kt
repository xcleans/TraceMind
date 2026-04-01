/*
 * Copyright (c) 2024 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.test.trace

import com.aspect.atrace.plugin.TracePlugin

/**
 * Release 构建：不启用任何插件（atrace-noop 空实现，无开销）
 */
object Plugins {
    fun get(): Array<TracePlugin> = emptyArray()
}
