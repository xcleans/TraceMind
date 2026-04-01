/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.core

import android.content.Context
import com.aspect.atrace.ALog

/**
 * 类加载监听器：拦截 ClassLoader.loadClass，对新加载的类
 * 自动执行 WatchList 规则匹配 + hook。
 *
 * 实现方式：通过反射替换 LoadedApk.mClassLoader 为代理 ClassLoader，
 * 代理在 loadClass 后调用 [scanCallback] 扫描新类的方法。
 */
internal class ClassLoadWatcher(
    private val context: Context,
    private val scanCallback: (Class<*>) -> Int
) {
    private var originalLoader: ClassLoader? = null
    private var proxyInstalled = false

    fun install() {
        if (proxyInstalled) return
        try {
            val baseContext = getContextImpl(context) ?: run {
                ALog.w(TAG, "Cannot access ContextImpl, class-load watcher not installed")
                return
            }
            val loadedApk = getLoadedApk(baseContext) ?: run {
                ALog.w(TAG, "Cannot access LoadedApk, class-load watcher not installed")
                return
            }

            val clField = loadedApk.javaClass.getDeclaredField("mClassLoader")
            clField.isAccessible = true
            val original = clField.get(loadedApk) as? ClassLoader ?: return

            originalLoader = original
            val proxy = WatchingClassLoader(original, scanCallback)
            clField.set(loadedApk, proxy)
            proxyInstalled = true
            ALog.i(TAG, "ClassLoadWatcher installed via LoadedApk.mClassLoader proxy")
        } catch (e: Exception) {
            ALog.w(TAG, "ClassLoadWatcher install failed: ${e.message}")
        }
    }

    fun uninstall() {
        if (!proxyInstalled) return
        try {
            val baseContext = getContextImpl(context) ?: return
            val loadedApk = getLoadedApk(baseContext) ?: return
            val clField = loadedApk.javaClass.getDeclaredField("mClassLoader")
            clField.isAccessible = true
            originalLoader?.let { clField.set(loadedApk, it) }
            proxyInstalled = false
            ALog.i(TAG, "ClassLoadWatcher uninstalled")
        } catch (e: Exception) {
            ALog.w(TAG, "ClassLoadWatcher uninstall failed: ${e.message}")
        }
    }

    private fun getContextImpl(ctx: Context): Any? {
        var c: Context = ctx
        while (c is android.content.ContextWrapper) {
            c = c.baseContext
        }
        return if (c.javaClass.name == "android.app.ContextImpl") c else null
    }

    private fun getLoadedApk(contextImpl: Any): Any? {
        return try {
            val field = contextImpl.javaClass.getDeclaredField("mPackageInfo")
            field.isAccessible = true
            field.get(contextImpl)
        } catch (_: Exception) { null }
    }

    /**
     * 代理 ClassLoader：委托原始 ClassLoader 完成加载后，
     * 对新加载的类执行 WatchList 规则扫描。
     *
     * 通过 ThreadLocal 防止递归：scanCallback 内部可能触发新类加载，
     * 此时跳过扫描避免死循环。
     */
    private class WatchingClassLoader(
        private val delegate: ClassLoader,
        private val scanCallback: (Class<*>) -> Int
    ) : ClassLoader(delegate) {

        private val scanning = ThreadLocal<Boolean>()

        override fun loadClass(name: String, resolve: Boolean): Class<*> {
            val clazz = delegate.loadClass(name)
            if (scanning.get() == true) return clazz
            try {
                if (shouldScan(name)) {
                    scanning.set(true)
                    try { scanCallback(clazz) }
                    finally { scanning.set(false) }
                }
            } catch (e: Exception) {
                ALog.w(TAG, "loadClass scan error for $name: ${e.message}")
            }
            return clazz
        }

        private fun shouldScan(className: String): Boolean {
            if (className.startsWith("java.") ||
                className.startsWith("javax.") ||
                className.startsWith("android.") ||
                className.startsWith("androidx.") ||
                className.startsWith("kotlin.") ||
                className.startsWith("kotlinx.") ||
                className.startsWith("dalvik.") ||
                className.startsWith("com.android.") ||
                className.startsWith("com.google.android.") ||
                className.startsWith("com.aspect.atrace.")
            ) return false
            return true
        }
    }

    companion object {
        private const val TAG = "ClassLoadWatcher"
    }
}
