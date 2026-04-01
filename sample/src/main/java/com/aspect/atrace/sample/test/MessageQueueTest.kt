/*
 * Copyright (c) 2024 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.sample.test

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.Message

/**
 * MessageQueue 测试
 *
 * 测试主线程 Message 处理
 */
object MessageQueueTest {
    private val mainHandler = Handler(Looper.getMainLooper())

    fun test(context: Context) {
        // 发送多个 Message 到主线程
        repeat(10) { index ->
            mainHandler.post {
                // 处理 Message
                processMessage(index)
            }
        }

        // 发送延迟 Message
        mainHandler.postDelayed({
            processMessage(100)
        }, 500)

        // 发送带 Message 对象的任务
        val msg = Message.obtain(mainHandler) {
            processMessage(200)
        }
        mainHandler.sendMessageDelayed(msg, 1000)
    }

    private fun processMessage(index: Int) {
        // 模拟一些处理
        var sum = 0L
        for (i in 0 until 100_000) {
            sum += i
        }
    }
}
