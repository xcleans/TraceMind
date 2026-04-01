/*
 * Copyright (c) 2024 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.test.trace

import androidx.compose.runtime.Composable
import androidx.compose.material3.MaterialTheme

/**
 * Demo 使用 Material3 默认主题容器。
 */
@Composable
fun ATraceSampleTheme(content: @Composable () -> Unit) {
    MaterialTheme(content = content)
}
