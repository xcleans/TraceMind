/*
 * Copyright (c) 2024 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.test.trace

import com.aspect.atrace.plugin.TracePlugin

/** Release 构建：不启用任何 Trace 插件。 */
object Plugins {
    fun get(): Array<TracePlugin> = emptyArray()
}
