/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.core.hook

import android.content.Context

/**
 * Art method hook backend abstraction.
 *
 * - Newer Android versions: native ArtMethodInstrumentation backend
 * - Older Android versions: SandHook + DexMaker backend (skeleton for now)
 */
internal interface ArtHookBackend {
    fun install(context: Context): Boolean
    fun addWatchedRule(scope: String, value: String)
    fun removeWatchedRule(entry: String)
    fun clearWatchedRules()
    fun watchedRuleCount(): Int
    fun getWatchedRules(): List<String>
    fun hookMethod(className: String, methodName: String, signature: String, isStatic: Boolean): Boolean
    fun unhookMethod(className: String, methodName: String, signature: String, isStatic: Boolean)
    fun scanAndHookClass(clazz: Class<*>): Int
}

