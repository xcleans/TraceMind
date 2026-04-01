/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.core

import java.lang.reflect.Method

/**
 * JNI Hook 辅助类
 *
 * 用于初始化 JNI 方法级 Hook 机制
 */
internal object JNIHookHelper {

    private var initialized = false

    /**
     * 初始化 JNI Hook 机制
     *
     * 需要在其他 JNI Hook 之前调用
     */
    @JvmStatic
    fun init(): Boolean {
        if (initialized) return true

        try {
            nativePlaceholder()
            // 获取占位方法的反射对象
            val sampleMethod: Method = JNIHookHelper::class.java
                .getDeclaredMethod("nativePlaceholder")

            // 通过占位方法确定 ArtMethod 中 JNI 入口的偏移
            initialized = nativeInit(sampleMethod)
            return initialized
        } catch (e: Exception) {
            e.printStackTrace()
            return false
        }
    }

    /**
     * 检查是否已初始化
     */
    @JvmStatic
    fun isInitialized(): Boolean = initialized

    /**
     * 占位 native 方法
     *
     * 仅用于确定 JNI 入口偏移，不会被实际调用
     */
    @JvmStatic
    private external fun nativePlaceholder()

    /**
     * Native 初始化
     */
    @JvmStatic
    private external fun nativeInit(sampleMethod: Method): Boolean
}

