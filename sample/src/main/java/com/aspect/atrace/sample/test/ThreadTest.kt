/*
 * Copyright (c) 2024 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.sample.test

import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * 多线程测试
 *
 * 创建多个线程执行任务，测试多线程采样
 */
object ThreadTest {
    private val executor = Executors.newFixedThreadPool(5)

    fun test() {
        val latch = CountDownLatch(5)

        // 创建 5 个工作线程
        repeat(5) { index ->
            executor.execute {
                doWork(index)
                latch.countDown()
            }
        }

        try {
            latch.await(5, TimeUnit.SECONDS)
        } catch (e: InterruptedException) {
            e.printStackTrace()
        }
    }

    private fun doWork(threadIndex: Int) {
        // 执行一些计算任务
        var sum = 0L
        for (i in 0 until 1_000_000) {
            sum += i
        }

        // 模拟一些等待
        try {
            Thread.sleep(100)
        } catch (e: InterruptedException) {
            e.printStackTrace()
        }

        // 递归调用
        fibonacci(20)
    }

    private fun fibonacci(n: Int): Int {
        if (n <= 1) return n
        return fibonacci(n - 1) + fibonacci(n - 2)
    }
}
