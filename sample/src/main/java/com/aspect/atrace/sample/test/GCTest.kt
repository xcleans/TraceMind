/*
 * Copyright (c) 2024 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.sample.test

import java.util.*

/**
 * GC 测试
 *
 * 通过大量分配对象触发 GC
 */
object GCTest {
    fun test() {
        Thread {
            val list = mutableListOf<ByteArray>()

            // 分配大量对象触发 GC
            repeat(100) {
                list.add(ByteArray(1024 * 1024)) // 1MB
                Thread.sleep(10)
            }

            // 清空引用，触发 GC
            list.clear()
            System.gc()

            // 再次分配
            repeat(50) {
                list.add(ByteArray(512 * 1024))
            }
        }.start()
    }
}
