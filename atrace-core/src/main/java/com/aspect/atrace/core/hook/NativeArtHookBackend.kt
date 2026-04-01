/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.core.hook

import android.content.Context

internal class NativeArtHookBackend(
    private val installNative: () -> Boolean,
    private val addRuleNative: (scope: String, value: String) -> Unit,
    private val removeRuleNative: (entry: String) -> Unit,
    private val clearRulesNative: () -> Unit,
    private val countRulesNative: () -> Int,
    private val getRulesNative: () -> Array<String>,
    private val hookMethodNative: (className: String, methodName: String, signature: String, isStatic: Boolean) -> Boolean,
    private val unhookMethodNative: (className: String, methodName: String, signature: String, isStatic: Boolean) -> Unit,
    private val scanClassNative: (clazz: Class<*>) -> Int,
) : ArtHookBackend {
    override fun install(context: Context): Boolean = installNative.invoke()
    override fun addWatchedRule(scope: String, value: String) = addRuleNative(scope, value)
    override fun removeWatchedRule(entry: String) = removeRuleNative(entry)
    override fun clearWatchedRules() = clearRulesNative.invoke()
    override fun watchedRuleCount(): Int = countRulesNative.invoke()
    override fun getWatchedRules(): List<String> = getRulesNative.invoke().toList()
    override fun hookMethod(className: String, methodName: String, signature: String, isStatic: Boolean): Boolean =
        hookMethodNative(className, methodName, signature, isStatic)
    override fun unhookMethod(className: String, methodName: String, signature: String, isStatic: Boolean) =
        unhookMethodNative(className, methodName, signature, isStatic)
    override fun scanAndHookClass(clazz: Class<*>): Int = scanClassNative(clazz)
}

