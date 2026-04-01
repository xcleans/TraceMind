/*
 * Copyright (c) 2024 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.sample.test

import android.os.Build
import android.util.Log
import java.util.Locale

/**
 * JNI 测试
 *
 * 通过调用系统 JNI 方法测试 JNI Hook
 */
object JNITest {
    fun test() {
        Thread {
            // 调用 String 的 native 方法
            val str = "Hello JNI Test"
            str.hashCode()
            str.length
            str.lowercase(Locale.ROOT)
            str.uppercase(Locale.ROOT)

            // 调用 System 的 native 方法
            System.currentTimeMillis()
            System.nanoTime()

            // 调用 Object 的 native 方法
            val obj = Any()
            obj.hashCode()
            obj.toString()

            // 多次调用
            repeat(100) {
                str.hashCode()
                System.currentTimeMillis()
            }
        }.start()
    }
}
