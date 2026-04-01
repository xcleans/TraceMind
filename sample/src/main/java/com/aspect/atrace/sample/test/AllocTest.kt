/*
 * Copyright (c) 2024 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.sample.test

/**
 * 对象分配测试
 *
 * 大量分配对象以测试 AllocPlugin
 */
object AllocTest {
    fun test() {
        Thread {
            // 分配各种类型的对象
            val strings = mutableListOf<String>()
            val integers = mutableListOf<Int>()
            val arrays = mutableListOf<ByteArray>()

            repeat(1000) {
                strings.add("String $it")
                integers.add(it)
                arrays.add(ByteArray(1024))
            }

            // 清空触发 GC
            strings.clear()
            integers.clear()
            arrays.clear()

            // 再次分配
            repeat(500) {
                strings.add("String2 $it")
                arrays.add(ByteArray(2048))
            }
        }.start()
    }
}
